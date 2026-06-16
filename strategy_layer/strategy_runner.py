"""
Strategy Runner — Orchestrator chính của Strategy Layer.

Chạy bar-by-bar:
  1. Đọc Layer 1 events trên bar hiện tại
  2. Setup Engine tạo setup mới
  3. Filter Engine kiểm tra setup
  4. State Machine cập nhật vòng đời
  5. Entry/SL/TP Model tính giá
  6. Order Intent Generator sinh order
  7. Decision Logger ghi tất cả
  8. Xuất CSV

Output:
  - setups.csv
  - orders_intent.csv
  - strategy_decisions.csv
"""

import csv
import os
from typing import Optional
from collections import defaultdict

from .models import (
    Setup, OrderIntent, StrategyDecision,
    SETUP_STATUS_CREATED, SETUP_STATUS_PENDING, SETUP_STATUS_ARMED,
    SETUP_STATUS_TRIGGERED, SETUP_STATUS_ENTERED,
    SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED, SETUP_STATUS_COMPLETED,
    DIRECTION_LONG, DIRECTION_SHORT,
    SETUP_CSV_FIELDS, ORDER_INTENT_CSV_FIELDS, DECISION_CSV_FIELDS,
)
from .config import StrategyConfig
from .setup_engine import SetupEngine
from .setup_state_machine import SetupStateMachine
from .entry_model import calculate_entry
from .sl_model import calculate_sl
from .tp_model import calculate_tp
from .filter_engine import FilterEngine
from .order_intent_generator import OrderIntentGenerator
from .decision_logger import DecisionLogger


class StrategyRunner:
    """Orchestrator chính — chạy strategy bar-by-bar."""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.engine = SetupEngine(config)
        self.filter_engine = FilterEngine(config)
        self.intent_generator = OrderIntentGenerator(config)
        self.decision_logger = DecisionLogger()

        # Kết quả
        self.setups: list[Setup] = []
        self.order_intents: list[OrderIntent] = []

        # Active setups
        self._active: list[Setup] = []

        # Cooldown bars tracking
        self._last_trade_result: Optional[bool] = None
        self._cooldown_until_bar: int = 0
        self._orders_today: int = 0
        self._orders_this_session: int = 0
        self._last_session_day: int = -1

        # For bars processing
        self._events_by_bar: dict[int, list[dict]] = {}
        self._all_bar_indices: list[int] = []

    def load_layer1(self, events_path: str, snapshots_path: str,
                    objects_path: str) -> None:
        """Load 3 file CSV từ Layer 1."""
        self.engine.load_layer1_data(events_path, snapshots_path, objects_path)

        # Group events by bar_index
        self._events_by_bar = defaultdict(list)
        max_bar = 0
        for ev in self.engine._events:
            bi = int(ev.get("bar_index", 0))
            self._events_by_bar[bi].append(ev)
            max_bar = max(max_bar, bi)

        self._all_bar_indices = sorted(self._events_by_bar.keys())

        # Lấy ATR từ snapshot cuối
        last_snap = self.engine._snapshots.get(max_bar, {})
        if not self.config.atr_value:
            # Sử dụng volatility từ snapshot nếu có
            snap_atr = float(last_snap.get("active_ob_count", 0)) * 0.001
            self.config.atr_value = max(0.0001, snap_atr or 0.001)

    def run(self) -> dict:
        """Chạy strategy trên toàn bộ dữ liệu.

        Returns:
            dict: thống kê kết quả
        """
        if not self._all_bar_indices:
            return {"error": "No data loaded"}

        print(f"Running strategy '{self.config.name}' over {len(self._all_bar_indices)} bars...")

        for bar_index in self._all_bar_indices:
            snap = self.engine._snapshots.get(bar_index, {})
            bar_events = self._events_by_bar.get(bar_index, [])
            timestamp = int(bar_events[0].get("timestamp", 0)) if bar_events else 0
            current_price = float(snap.get("last_close", 0) or snap.get("close", 0))

            # ── 1. Xử lý setup engine ──
            new_setups = self.engine.process_bar(bar_index, timestamp, bar_events)
            self.engine.active_setups = [s for s in self.engine.active_setups
                                         if s.status not in (SETUP_STATUS_CANCELLED,
                                                             SETUP_STATUS_EXPIRED,
                                                             SETUP_STATUS_COMPLETED)]

            # ── 2. Kiểm tra cooldown ──
            if bar_index < self._cooldown_until_bar:
                # Không tạo setup mới trong cooldown
                pass
            else:
                for setup in new_setups:
                    self._process_new_setup(setup, bar_index, timestamp, snap, bar_events)

            # ── 3. Cập nhật active setups ──
            self._update_active(bar_index, timestamp, snap, bar_events, current_price)

            # Reset session tracking
            current_day = bar_index // 1440  # approximate day
            if current_day != self._last_session_day:
                self._orders_this_session = 0
                if current_day > self._last_session_day + 1:
                    self._orders_today = 0
                self._last_session_day = current_day

            # Merge active setups
            self.engine.active_setups = [s for s in self.setups
                                         if s.status not in (SETUP_STATUS_CANCELLED,
                                                             SETUP_STATUS_EXPIRED,
                                                             SETUP_STATUS_COMPLETED)]

        # ── 4. Export ──
        stats = self._summarize()
        return stats

    def _process_new_setup(self, setup: Setup, bar_index: int,
                           timestamp: int, snap: dict,
                           bar_events: list[dict]) -> None:
        """Xử lý một setup mới: filter → state machine → lưu."""
        # Kiểm tra concurrent limit
        active_count = sum(1 for s in self.setups if s.status in (
            SETUP_STATUS_PENDING, SETUP_STATUS_ARMED, SETUP_STATUS_TRIGGERED))
        if active_count >= self.config.max_concurrent_setups:
            self.decision_logger.log_reject(timestamp, bar_index,
                                            setup.setup_id,
                                            ["max_concurrent_setups"])
            return

        # Filter
        passed, reasons = self.filter_engine.check_all(setup, bar_index, snap, bar_events)
        if not passed:
            self.decision_logger.log_reject(timestamp, bar_index,
                                            setup.setup_id, reasons)
            return

        # Qua filter → chuyển sang pending
        sm = SetupStateMachine(setup)
        sm.transition_to(SETUP_STATUS_PENDING, bar_index)
        self.setups.append(setup)
        self.decision_logger.log_create(timestamp, bar_index, setup.setup_id)

        # Nếu có OB zone + price, arm luôn
        if setup.entry_zone_mid > 0:
            sm.transition_to(SETUP_STATUS_ARMED, bar_index)
            self.decision_logger.log_arm(timestamp, bar_index, setup.setup_id)

    def _update_active(self, bar_index: int, timestamp: int,
                       snap: dict, bar_events: list[dict],
                       current_price: float) -> None:
        """Cập nhật state cho các setup đang active."""
        for setup in self.setups:
            if setup.status in (SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED,
                               SETUP_STATUS_COMPLETED):
                continue

            sm = SetupStateMachine(setup)

            # ── Check exit nếu đã entered ──
            if setup.status == SETUP_STATUS_ENTERED:
                self._check_exit(setup, bar_index, timestamp, snap, bar_events, current_price)
                continue

            # ── Check cancel / expire ──
            bars_since_created = bar_index - setup.created_bar

            # Cancel: có event ngược chiều
            cancelled = False
            for ev in bar_events:
                etype = ev.get("event_type", "")
                if setup.direction == DIRECTION_SHORT and "BOS_BULLISH" in etype:
                    sm.transition_to(SETUP_STATUS_CANCELLED, bar_index)
                    self.decision_logger.log_cancel(timestamp, bar_index,
                                                    setup.setup_id, "bullish_bos_cancelled")
                    cancelled = True
                    break
                elif setup.direction == DIRECTION_LONG and "BOS_BEARISH" in etype:
                    sm.transition_to(SETUP_STATUS_CANCELLED, bar_index)
                    self.decision_logger.log_cancel(timestamp, bar_index,
                                                    setup.setup_id, "bearish_bos_cancelled")
                    cancelled = True
                    break

            if cancelled:
                continue

            # Expire
            if bars_since_created > self.config.max_bars_wait_entry + 5:
                sm.transition_to(SETUP_STATUS_EXPIRED, bar_index)
                self.decision_logger.log_expire(timestamp, bar_index, setup.setup_id)
                continue

            # ── ARM → TRIGGERED (giá chạm entry zone) ──
            if setup.status == SETUP_STATUS_ARMED:
                if setup.direction == DIRECTION_SHORT:
                    # Giá chạm OB zone (short entry ở OB)
                    if current_price <= setup.entry_zone_top and current_price >= setup.entry_zone_bottom:
                        # Tính SL/TP
                        sl_price, sl_type = calculate_sl(setup, self.config, snap)
                        setup.sl_price = sl_price

                        tp_price, tp_type = calculate_tp(setup, self.config, snap,
                                                         current_price=current_price)
                        setup.tp_price = tp_price

                        sm.transition_to(SETUP_STATUS_TRIGGERED, bar_index)
                        self.decision_logger.log_trigger(timestamp, bar_index, setup.setup_id)
                else:
                    if current_price <= setup.entry_zone_top and current_price >= setup.entry_zone_bottom:
                        sl_price, sl_type = calculate_sl(setup, self.config, snap)
                        setup.sl_price = sl_price

                        tp_price, tp_type = calculate_tp(setup, self.config, snap,
                                                         current_price=current_price)
                        setup.tp_price = tp_price

                        sm.transition_to(SETUP_STATUS_TRIGGERED, bar_index)
                        self.decision_logger.log_trigger(timestamp, bar_index, setup.setup_id)

            # ── TRIGGERED → ENTERED ──
            if setup.status == SETUP_STATUS_TRIGGERED:
                # Check order frequency
                if self._orders_today >= self.config.max_orders_per_day:
                    sm.transition_to(SETUP_STATUS_CANCELLED, bar_index)
                    self.decision_logger.log_cancel(timestamp, bar_index,
                                                    setup.setup_id, "max_daily_orders")
                    continue
                if self._orders_this_session >= self.config.max_orders_per_session:
                    sm.transition_to(SETUP_STATUS_CANCELLED, bar_index)
                    self.decision_logger.log_cancel(timestamp, bar_index,
                                                    setup.setup_id, "max_session_orders")
                    continue

                # Tính entry price
                entry_price, entry_type = calculate_entry(setup, self.config,
                                                          current_price, bar_index, snap)

                # Tạo order intent
                intent = self.intent_generator.generate(
                    setup, bar_index, timestamp, entry_price, entry_type
                )
                if intent:
                    self.order_intents.append(intent)
                    self.decision_logger.log_enter(timestamp, bar_index, setup.setup_id)
                    self.decision_logger.log_place_order(timestamp, bar_index, setup.setup_id)
                    sm.transition_to(SETUP_STATUS_ENTERED, bar_index)
                    self._orders_today += 1
                    self._orders_this_session += 1
                else:
                    self.decision_logger.log_skip_order(timestamp, bar_index,
                                                        setup.setup_id, "invalid_intent")

    def _check_exit(self, setup: Setup, bar_index: int, timestamp: int,
                    snap: dict, bar_events: list[dict],
                    current_price: float) -> None:
        """Kiểm tra exit cho lệnh đang mở."""
        if not self.config.use_early_exit:
            return

        # Early exit on reverse CHOCH
        if self.config.early_exit_on_reverse_choch:
            for ev in bar_events:
                etype = ev.get("event_type", "")
                if setup.direction == DIRECTION_SHORT and "CHOCH_BULLISH" in etype:
                    self._close_setup(setup, bar_index, timestamp, "reverse_choch")
                    return
                elif setup.direction == DIRECTION_LONG and "CHOCH_BEARISH" in etype:
                    self._close_setup(setup, bar_index, timestamp, "reverse_choch")
                    return

        # No progress exit
        bars_in_trade = bar_index - setup.entered_bar
        if bars_in_trade >= self.config.max_bars_no_progress:
            entry_price = setup.entry_zone_mid
            if entry_price > 0:
                if setup.direction == DIRECTION_LONG:
                    progress_pct = (current_price - entry_price) / entry_price * 100
                else:
                    progress_pct = (entry_price - current_price) / entry_price * 100

                rr = progress_pct / max(0.001, abs(entry_price - setup.sl_price) / entry_price * 100)
                if rr < self.config.no_progress_min_r:
                    self._close_setup(setup, bar_index, timestamp, f"no_progress_rr={rr:.2f}")

    def _close_setup(self, setup: Setup, bar_index: int,
                     timestamp: int, reason: str) -> None:
        """Đóng setup và log."""
        sm = SetupStateMachine(setup)
        sm.transition_to(SETUP_STATUS_COMPLETED, bar_index)
        self.decision_logger.log_cancel(timestamp, bar_index,
                                        setup.setup_id, f"early_exit:{reason}")

    def _summarize(self) -> dict:
        """Thống kê kết quả."""
        status_counts = defaultdict(int)
        for s in self.setups:
            status_counts[s.status] += 1

        return {
            "strategy": self.config.name,
            "total_setups": len(self.setups),
            "total_orders": len(self.order_intents),
            "total_decisions": len(self.decision_logger.decisions),
            "status_counts": dict(status_counts),
            "decision_summary": self.decision_logger.summary(),
        }

    def export_csv(self, output_dir: str = "") -> dict[str, str]:
        """Xuất 3 file CSV kết quả.

        Returns:
            dict: {output_type: file_path}
        """
        out = output_dir or "."

        # setups.csv
        setups_path = os.path.join(out, "setups.csv")
        with open(setups_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=SETUP_CSV_FIELDS)
            writer.writeheader()
            for s in self.setups:
                writer.writerow(s.to_csv_row())

        # orders_intent.csv
        orders_path = os.path.join(out, "orders_intent.csv")
        with open(orders_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ORDER_INTENT_CSV_FIELDS)
            writer.writeheader()
            for o in self.order_intents:
                writer.writerow(o.to_csv_row())

        # strategy_decisions.csv
        decisions_path = os.path.join(out, "strategy_decisions.csv")
        self.decision_logger.export_csv(decisions_path)

        return {
            "setups": setups_path,
            "orders_intent": orders_path,
            "strategy_decisions": decisions_path,
        }
