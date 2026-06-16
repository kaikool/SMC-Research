"""
Setup Engine — Signal Rule Engine chính.

Đọc events.csv, snapshots.csv, objects.csv từ Layer 1,
áp dụng rule để tạo setup giao dịch.

Strategy mặc định: Sweep → CHOCH → OB Retest
  SHORT: buy-side sweep + bearish CHOCH + bearish OB
  LONG:  sell-side sweep + bullish CHOCH + bullish OB
"""

import csv
from collections import defaultdict
from typing import Optional

from .models import (
    Setup, StrategyDecision,
    SETUP_STATUS_CREATED, SETUP_STATUS_PENDING,
    SETUP_STATUS_ARMED, SETUP_STATUS_TRIGGERED,
    SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED,
    DIRECTION_LONG, DIRECTION_SHORT, DIRECTION_NONE,
)
from .config import StrategyConfig


class SetupEngine:
    """Đọc Layer 1 events → sinh Setup candidates.

    Hỗ trợ nhiều pattern:
      - sweep + structure (BOS/CHOCH) + OB (strict)
      - sweep + structure (flexible)
      - structure + OB (flexible)
      - sweep + OB (flexible)
    """

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.setup_counter = 0

        # Internal caches (bar-by-bar)
        self._events: list[dict] = []
        self._snapshots: dict[int, dict] = {}     # bar_index → snapshot
        self._objects: dict[str, dict] = {}        # object_id → object
        self._current_bar: int = 0

        # Track events within lookback window
        self._recent_sweeps: list[dict] = []       # liquidity sweeps, newest first
        self._recent_structures: list[dict] = []   # BOS/CHOCH events
        self._recent_obs_created: list[dict] = []  # OB created events
        self._obs_by_id: dict[str, dict] = {}      # OB status tracking

        # Active setups (by bar tracked)
        self.active_setups: list[Setup] = []

    def load_layer1_data(self, events_path: str, snapshots_path: str,
                         objects_path: str) -> None:
        """Load 3 file CSV từ Layer 1."""
        import csv
        # Load events
        with open(events_path) as f:
            reader = csv.DictReader(f)
            self._events = []
            for row in reader:
                # Parse metadata field (may contain commas inside quotes)
                event_type = row.get("event_type", "")
                self._events.append({
                    "timestamp": row.get("timestamp", "0"),
                    "bar_index": int(row.get("bar_index", 0)),
                    "event_type": event_type,
                    "direction": row.get("direction", "0"),
                    "price": row.get("price", "0"),
                    "level_top": row.get("level_top", "0"),
                    "level_bottom": row.get("level_bottom", "0"),
                    "source_object_id": row.get("source_object_id", ""),
                    "object_id": row.get("object_id", ""),
                    "status": row.get("status", ""),
                    "confirmed": row.get("confirmed", "False"),
                    "metadata": row.get("metadata", ""),
                })

        # Load snapshots
        with open(snapshots_path) as f:
            for row in csv.DictReader(f):
                bi = int(row.get("bar_index", 0))
                self._snapshots[bi] = dict(row)

        # Load objects
        with open(objects_path) as f:
            for row in csv.DictReader(f):
                oid = row.get("object_id", "")
                if oid:
                    self._objects[oid] = dict(row)

    def get_max_bar(self) -> int:
        if not self._events:
            return 0
        return max(int(e.get("bar_index", 0)) for e in self._events)

    def process_bar(self, bar_index: int, timestamp: int,
                    bar_events: list[dict]) -> list[Setup]:
        """Xử lý một bar: cập nhật caches + tạo setup mới.

        Returns: danh sách Setup mới tạo.
        """
        self._current_bar = bar_index
        new_setups: list[Setup] = []

        # ── 1. Cập nhật recent events ──
        for ev in bar_events:
            etype = ev.get("event_type", "")

            if "LIQUIDITY_SWEEP" in etype:
                self._recent_sweeps.insert(0, ev)

            if "BOS" in etype or "CHOCH" in etype:
                self._recent_structures.insert(0, ev)

            if "ORDER_BLOCK_CREATED" in etype:
                self._recent_obs_created.insert(0, ev)
                obj_id = ev.get("object_id", "")
                if obj_id and obj_id in self._objects:
                    self._obs_by_id[obj_id] = self._objects[obj_id]

            if etype in ("OB_MITIGATED", "OB_INVALIDATED"):
                obj_id = ev.get("object_id", "")
                if obj_id in self._obs_by_id:
                    new_st = "mitigated" if "MITIGATED" in etype else "invalidated"
                    self._obs_by_id[obj_id] = dict(self._obs_by_id[obj_id])
                    self._obs_by_id[obj_id]["status"] = new_st

        # ── 2. Trim old events ──
        window = max(self.config.max_bars_sweep_to_choch,
                     self.config.max_bars_wait_entry,
                     50) + 10
        self._trim_old(self._recent_sweeps, window, bar_index)
        self._trim_old(self._recent_structures, window, bar_index)
        self._trim_old(self._recent_obs_created, window, bar_index)

        # ── 3. Kiểm tra tạo setup mới ──
        snap = self._snapshots.get(bar_index, {})
        bar_event_types = {e.get("event_type", "") for e in bar_events}

        if self.config.allow_short:
            s = self._try_create_short_setup(bar_index, timestamp, bar_events,
                                              bar_event_types, snap)
            if s:
                new_setups.append(s)

        if self.config.allow_long:
            s = self._try_create_long_setup(bar_index, timestamp, bar_events,
                                             bar_event_types, snap)
            if s:
                new_setups.append(s)

        return new_setups

    # ── helpers ────────────────────────────────────────────────

    def _direction(self, ev: dict, target: int) -> bool:
        """Kiểm tra direction của event (1=long/bullish, -1=short/bearish)."""
        d = ev.get("direction", "0").strip()
        if target == 1:
            return d in ("1", "1.0", "bullish")
        elif target == -1:
            return d in ("-1", "-1.0", "bearish")
        return False

    def _swept_side(self, ev: dict, side: str) -> bool:
        """Kiểm tra swept_side từ metadata của sweep event."""
        meta = ev.get("metadata", "")
        return f"swept_side={side}" in meta or f"swept_side={side.lower()}" in meta

    def _find_structure(self, bar_index: int, window: int,
                        direction: int) -> list[dict]:
        """Tìm BOS/CHOCH events theo hướng."""
        result = []
        for ev in self._recent_structures:
            bi = int(ev.get("bar_index", 0))
            if bar_index - bi > window:
                continue
            if not self._direction(ev, direction):
                continue
            etype = ev.get("event_type", "").upper()
            if direction == -1 and ("BEARISH" not in etype):
                continue
            if direction == 1 and ("BULLISH" not in etype):
                continue
            result.append(ev)
        return result

    def _find_obs(self, bar_index: int, window: int,
                  direction: int) -> list[dict]:
        """Tìm OB_CREATED events theo hướng."""
        result = []
        for ev in self._recent_obs_created:
            bi = int(ev.get("bar_index", 0))
            if bar_index - bi > window:
                continue
            if not self._direction(ev, direction):
                continue
            obj_id = ev.get("object_id", "")
            # Check OB not invalidated
            if obj_id and obj_id in self._obs_by_id:
                st = self._obs_by_id[obj_id].get("status", "")
                if st in ("invalidated", "expired"):
                    continue
            result.append(ev)
        return result

    def _find_sweeps(self, bar_index: int, window: int,
                     direction: int, swept_side: str = "") -> list[dict]:
        """Tìm sweep events."""
        result = []
        for ev in self._recent_sweeps:
            bi = int(ev.get("bar_index", 0))
            if bar_index - bi > window:
                continue
            if not self._direction(ev, direction):
                continue
            if swept_side and not self._swept_side(ev, swept_side):
                continue
            result.append(ev)
        return result

    # ── Setup creation ─────────────────────────────────────────

    def _try_create_short_setup(self, bar_index: int, timestamp: int,
                                 bar_events: list[dict],
                                 bar_event_types: set,
                                 snap: dict) -> Optional[Setup]:
        """Tạo SHORT setup: buy-side sweep + bearish structure + bearish OB.

        V1 flexible: cần ít nhất 2 trong 3 yếu tố.
        """
        window = self.config.max_bars_sweep_to_choch

        sweeps = self._find_sweeps(bar_index, window, -1, "buy_side")
        structs = self._find_structure(bar_index, window, -1)
        obs = self._find_obs(bar_index, window, -1)

        # Cần ít nhất 2/3
        have_sweep = len(sweeps) > 0
        have_struct = len(structs) > 0
        have_ob = len(obs) > 0
        score = sum([have_sweep, have_struct, have_ob])

        if score < 2:
            return None

        # Lấy các source events
        source_events = []
        source_objects = []
        entry_top = 0.0
        entry_bottom = 0.0

        if have_ob:
            ob_ev = obs[0]
            source_events.append(ob_ev.get("source_object_id", "OB"))
            oid = ob_ev.get("object_id", "")
            if oid:
                source_objects.append(oid)
            entry_top = float(ob_ev.get("level_top", 0) or 0)
            entry_bottom = float(ob_ev.get("level_bottom", 0) or 0)
        elif have_struct:
            st_ev = structs[0]
            source_events.append(st_ev.get("event_type", "STRUCTURE"))
            entry_top = float(st_ev.get("level_top", 0) or st_ev.get("price", 0))
            entry_bottom = float(st_ev.get("level_bottom", 0) or 0)

        if have_sweep:
            sw_ev = sweeps[0]
            source_events.append(f"SWEEP_{sw_ev.get('bar_index', '')}")
            if not entry_top:
                entry_top = float(sw_ev.get("level_top", 0) or sw_ev.get("price", 0))
            if not entry_bottom:
                entry_bottom = float(sw_ev.get("level_bottom", 0) or 0)

        if not entry_top and not entry_bottom:
            return None

        return self._create_setup(
            setup_type="sweep_structure_ob",
            direction=DIRECTION_SHORT,
            bar_index=bar_index,
            timestamp=timestamp,
            source_events=source_events,
            source_objects=source_objects,
            entry_top=entry_top,
            entry_bottom=entry_bottom,
            snap=snap,
            meta=f"sweep={have_sweep},struct={have_struct},ob={have_ob}",
        )

    def _try_create_long_setup(self, bar_index: int, timestamp: int,
                                bar_events: list[dict],
                                bar_event_types: set,
                                snap: dict) -> Optional[Setup]:
        """Tạo LONG setup: sell-side sweep + bullish structure + bullish OB.

        V1 flexible: cần ít nhất 2 trong 3 yếu tố.
        """
        window = self.config.max_bars_sweep_to_choch

        sweeps = self._find_sweeps(bar_index, window, 1, "sell_side")
        structs = self._find_structure(bar_index, window, 1)
        obs = self._find_obs(bar_index, window, 1)

        have_sweep = len(sweeps) > 0
        have_struct = len(structs) > 0
        have_ob = len(obs) > 0
        score = sum([have_sweep, have_struct, have_ob])

        if score < 2:
            return None

        source_events = []
        source_objects = []
        entry_top = 0.0
        entry_bottom = 0.0

        if have_ob:
            ob_ev = obs[0]
            source_events.append(ob_ev.get("source_object_id", "OB"))
            oid = ob_ev.get("object_id", "")
            if oid:
                source_objects.append(oid)
            entry_top = float(ob_ev.get("level_top", 0) or 0)
            entry_bottom = float(ob_ev.get("level_bottom", 0) or 0)
        elif have_struct:
            st_ev = structs[0]
            source_events.append(st_ev.get("event_type", "STRUCTURE"))
            entry_top = float(st_ev.get("level_top", 0) or st_ev.get("price", 0))
            entry_bottom = float(st_ev.get("level_bottom", 0) or 0)

        if have_sweep:
            sw_ev = sweeps[0]
            source_events.append(f"SWEEP_{sw_ev.get('bar_index', '')}")
            if not entry_top:
                entry_top = float(sw_ev.get("level_top", 0) or sw_ev.get("price", 0))
            if not entry_bottom:
                entry_bottom = float(sw_ev.get("level_bottom", 0) or 0)

        if not entry_top and not entry_bottom:
            return None

        return self._create_setup(
            setup_type="sweep_structure_ob",
            direction=DIRECTION_LONG,
            bar_index=bar_index,
            timestamp=timestamp,
            source_events=source_events,
            source_objects=source_objects,
            entry_top=entry_top,
            entry_bottom=entry_bottom,
            snap=snap,
            meta=f"sweep={have_sweep},struct={have_struct},ob={have_ob}",
        )

    def _create_setup(self, setup_type: str, direction: int,
                      bar_index: int, timestamp: int,
                      source_events: list[str],
                      source_objects: list[str],
                      entry_top: float, entry_bottom: float,
                      snap: dict,
                      meta: str = "") -> Setup:
        """Tạo một Setup object."""
        self.setup_counter += 1

        entry_mid = (entry_top + entry_bottom) / 2 if entry_top and entry_bottom else 0

        # Tính sl_price và tp_price tạm thời (sẽ được update sau bởi sl/tp models)
        try:
            last_swing_high = float(snap.get("last_swing_high", 0) or 0)
        except (ValueError, TypeError):
            last_swing_high = 0
        try:
            last_swing_low = float(snap.get("last_swing_low", 0) or 0)
        except (ValueError, TypeError):
            last_swing_low = 0

        if direction == DIRECTION_SHORT:
            sl_price = last_swing_high
        else:
            sl_price = last_swing_low

        # Tính confidence cơ bản
        confidence = 0.5
        if entry_mid and sl_price:
            rr = abs(sl_price - entry_mid) / (abs(entry_mid) + 0.0001) * 100
            confidence = min(0.9, 0.5 + rr * 0.01)

        setup = Setup(
            setup_id=f"SETUP_{self.setup_counter:04d}",
            created_at=timestamp,
            direction=direction,
            setup_type=setup_type,
            source_events=source_events,
            source_objects=source_objects,
            entry_zone_top=entry_top,
            entry_zone_bottom=entry_bottom,
            entry_zone_mid=entry_mid,
            sl_price=float(sl_price) if sl_price else 0,
            tp_price=0.0,  # sẽ tính sau
            confidence=round(confidence, 2),
            status=SETUP_STATUS_CREATED,
            created_bar=bar_index,
            last_active_bar=bar_index,
        )

        return setup

    def _update_active_setups(self, bar_index: int, timestamp: int,
                              bar_events: list[dict]) -> None:
        """Cập nhật trạng thái các active setup."""
        # Lọc các event quan trọng trên bar này
        bar_event_types = {e["event_type"] for e in bar_events}

        for setup in self.active_setups:
            if setup.status in (SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED,
                               SETUP_STATUS_COMPLETED):
                continue

            # Kiểm tra invalidate: có event ngược chiều phá setup
            self._check_invalidation(setup, bar_index, bar_event_types, timestamp)

    def _check_invalidation(self, setup: Setup, bar_index: int,
                            bar_event_types: set, timestamp: int) -> None:
        """Kiểm tra xem setup có bị invalidate không."""
        # SHORT setup bị invalidate nếu có bullish BOS
        if setup.direction == DIRECTION_SHORT:
            if "BOS_BULLISH" in bar_event_types:
                setup.status = SETUP_STATUS_CANCELLED
                setup.last_active_bar = bar_index
        # LONG setup bị invalidate nếu có bearish BOS
        elif setup.direction == DIRECTION_LONG:
            if "BOS_BEARISH" in bar_event_types:
                setup.status = SETUP_STATUS_CANCELLED
                setup.last_active_bar = bar_index

    def _find_recent(self, lst: list[dict], current_bar: int,
                     max_bars: int, filter_fn=None) -> list[dict]:
        """Tìm các event trong window bars."""
        result = []
        for ev in lst:
            ev_bar = int(ev.get("bar_index", 0))
            if current_bar - ev_bar > max_bars:
                continue
            if filter_fn and not filter_fn(ev):
                continue
            result.append(ev)
        return result

    def _trim_old(self, lst: list[dict], max_bars: int, current_bar: int) -> None:
        """Xóa event quá cũ."""
        while lst and current_bar - int(lst[-1].get("bar_index", 0)) > max_bars:
            lst.pop()
