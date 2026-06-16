"""
SMC Event Engine — Main Orchestrator.

Bar-by-bar loop:
  1. Update indicators (ATR, volatility)
  2. Run swing detection (SwingEngine.on_bar)
  3. Run structure detection (StructureEngine.on_bar)
  4. Create OBs from structure breaks (OrderBlockEngine.create_from_structure_break)
  5. Update OB lifecycle (OrderBlockEngine.check_mitigations)
  6. Detect FVGs (FVGEngine.on_bar)
  7. Update premium/discount zones (PremiumDiscountEngine.update_trailing_extremes)
  8. Run zone manager checks (ZoneManager.check_touches)
  9. Emit events & snapshots
  10. No-lookahead guard validation

Output: events.csv, snapshots.csv, objects.csv
"""

from typing import Optional
from .models import Bar, Event, Snapshot
from .config import EngineConfig, BULLISH, BEARISH, SWING, INTERNAL, OB_ACTIVE
from .swing_engine import SwingEngine
from .structure_engine import StructureEngine
from .order_block_engine import OrderBlockEngine
from .fvg_engine import FVGEngine
from .liquidity_engine import LiquidityEngine
from .premium_discount_engine import PremiumDiscountEngine
from .zone_manager import ZoneManager
from .output import CombinedOutput
from .no_lookahead_guard import NoLookaheadGuard


class SMCEngine:
    """
    SMC Event Engine — top-level runner.

    Usage:
        engine = SMCEngine(config)
        engine.run(bars)
        engine.output.close_all()
        print(engine.guard.summary())
    """

    def __init__(self, config: Optional[EngineConfig] = None):
        self.cfg = config or EngineConfig()

        # Guard
        self.guard = NoLookaheadGuard(strict=False)

        # Sub-engines
        self.swing = SwingEngine(self.cfg, self.guard)
        self.structure = StructureEngine(self.cfg, self.guard)
        self.ob_engine = OrderBlockEngine(self.cfg, self.guard)
        self.fvg_engine = FVGEngine(self.cfg, self.guard)
        self.liquidity = LiquidityEngine(self.cfg, self.guard)
        self.pd_engine = PremiumDiscountEngine(self.cfg)
        self.zone_manager = ZoneManager(self.cfg)

        # Output
        self.output = CombinedOutput(self.cfg)

        # State
        self.all_bars: list[Bar] = []
        self.prev_close: float = 0.0
        self.events_this_bar: list[Event] = []
        self.current_bar_index: int = -1
        self.current_timestamp: int = 0

    def run(self, bars: list[Bar]) -> None:
        """Main bar-by-bar loop."""
        self.all_bars = bars
        self.output.open_all()

        for i, bar in enumerate(bars):
            self._process_bar(bar, i)

        self.output.close_all()

    def _process_bar(self, bar: Bar, bar_index: int) -> None:
        """Process a single bar through all engines."""
        self.events_this_bar = []
        self.current_bar_index = bar_index
        self.current_timestamp = bar.timestamp

        # Update OB engine with parsed prices (bar-by-bar)
        self.ob_engine.on_bar(bar, bar_index, self.swing.atr_value)

        # ── 1. Swing Detection ──────────────────────────────────
        snapshot = Snapshot(timestamp=bar.timestamp, bar_index=bar_index)
        swing_events = self.swing.on_bar(bar, bar_index, snapshot)
        self._emit_events(swing_events)

        # ── 2. Structure Detection (BOS/CHOCH) ──────────────────
        struct_events = self.structure.on_bar(
            bar, bar_index, self.prev_close,
            self.swing.swing_high, self.swing.swing_low,
            self.swing.internal_high, self.swing.internal_low,
            snapshot,
        )
        self._emit_events(struct_events)

        # ── 3. Order Block Creation (from structure breaks) ─────
        ob_create_events = self._process_ob_creation(struct_events, bar, bar_index)
        self._emit_events(ob_create_events)

        # ── 4. Order Block Mitigation Checks ────────────────────
        ob_mit_events = self.ob_engine.check_mitigations(bar, bar_index, self.swing.atr_value)
        for ev in ob_mit_events:
            self.zone_manager.update_from_lifecycle_event(ev)
        self._emit_events(ob_mit_events)

        # ── 5. FVG Detection & Fill Check ───────────────────────
        if self.cfg.show_fair_value_gaps:
            fvg_events = self.fvg_engine.on_bar(bar, bar_index, self.all_bars, self.swing.atr_value)
            self._emit_events(fvg_events)

        # ── 6. Premium / Discount Zones ─────────────────────────
        if self.cfg.show_premium_discount_zones or self.cfg.show_high_low_swings:
            pd_events = self.pd_engine.update_trailing_extremes(
                self.swing.trailing_top, self.swing.trailing_bottom,
                self.swing.trailing_top_bar, self.swing.trailing_bottom_bar,
                self.swing.trailing_top_time, self.swing.trailing_bottom_time,
                bar, bar_index,
            )
            self._emit_events(pd_events)
            self.pd_engine.update_snapshot(snapshot, bar.close)

        # ── 7. Zone Manager Updates ─────────────────────────────
        zone_touch_events = self.zone_manager.check_touches(bar, bar_index)
        self._emit_events(zone_touch_events)
        self.zone_manager.update_snapshot(snapshot)

        # ── 8. Liquidity Sweep Detection ────────────────────────
        liq_events = self.liquidity.on_bar(
            bar, bar_index, self.swing.swing_high, self.swing.swing_low,
            self.swing.equal_highs, self.swing.equal_lows,
        )
        self._emit_events(liq_events)

        # ── 9. Emit snapshot every bar ─────────────────────────
        if self.cfg.logging.snapshot_every_bar:
            self._finalize_snapshot(snapshot, bar)

        # ── 10. Update state ────────────────────────────────────
        self.prev_close = bar.close

    def _process_ob_creation(self, struct_events: list[Event],
                              bar: Bar, bar_index: int) -> list[Event]:
        """When BOS/CHOCH events fire, create corresponding OBs."""
        events: list[Event] = []

        for se in struct_events:
            if not se.confirmed:
                continue
            if "BOS" not in se.event_type and "CHOCH" not in se.event_type:
                continue

            is_internal = se.event_type.startswith("INTERNAL_")
            level = INTERNAL if is_internal else SWING
            direction = se.direction
            source_event = se.event_type

            # Get pivot info from the structure event metadata
            pivot_level = 0.0
            pivot_bar = 0
            try:
                meta = {}
                for part in se.metadata.split(","):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        meta[k.strip()] = v.strip()
                pivot_level = float(meta.get("break_level", 0))
            except (ValueError, KeyError):
                pass

            # Find the pivot bar from structure event
            if direction == BULLISH:
                pivot_obj = self.swing.swing_high if not is_internal else self.swing.internal_high
                pivot_bar = pivot_obj.bar_index
                pivot_level = pivot_obj.price or pivot_level
            else:
                pivot_obj = self.swing.swing_low if not is_internal else self.swing.internal_low
                pivot_bar = pivot_obj.bar_index
                pivot_level = pivot_obj.price or pivot_level

            if pivot_level <= 0 or pivot_bar <= 0:
                continue

            ob = self.ob_engine.create_from_structure_break(
                direction=direction,
                pivot_bar=pivot_bar,
                pivot_price=pivot_level,
                pivot_timestamp=self.all_bars[pivot_bar].timestamp if pivot_bar < len(self.all_bars) else 0,
                current_bar=bar_index,
                current_timestamp=bar.timestamp,
                level=level,
                source_event=source_event,
            )

            if ob is not None:
                # Register with zone manager
                zone = self.zone_manager.update_from_ob(ob)

                # Log to objects.csv
                self.output.object_logger.write_ob(ob)

                events.append(Event(
                    timestamp=bar.timestamp, bar_index=bar_index,
                    symbol=bar.symbol, timeframe=bar.timeframe,
                    event_type="ORDER_BLOCK_CREATED",
                    direction=ob.direction,
                    price=bar.close,
                    level_top=ob.top,
                    level_bottom=ob.bottom,
                    source_object_id=source_event,
                    object_id=ob.id,
                    status=OB_ACTIVE,
                    confirmed=True,
                    metadata=f'ob_type={"swing" if level == SWING else "internal"}',
                ))

        return events

    def _emit_events(self, new_events: list[Event]) -> None:
        """Write events to output and track."""
        for ev in new_events:
            self.guard.check_no_retroactive_event(
                event_bar=ev.bar_index,
                current_bar=self.current_bar_index,
                event_type=ev.event_type,
            )
            self.guard.check_event_time(
                event_time=ev.timestamp,
                confirm_time=self.current_timestamp,
                event_type=ev.event_type,
                bar=self.current_bar_index,
            )

            # Ensure symbol/timeframe are filled
            if not ev.symbol and self.cfg.symbol:
                ev.symbol = self.cfg.symbol
            if not ev.timeframe and self.cfg.timeframe:
                ev.timeframe = self.cfg.timeframe

            self.output.event_logger.write(ev)
            self.events_this_bar.append(ev)

    def _finalize_snapshot(self, snapshot: Snapshot, bar: Bar) -> None:
        """Fill remaining snapshot fields and write."""
        if self.cfg.symbol:
            snapshot.current_trend = self.structure.swing_trend
        if self.cfg.show_fair_value_gaps:
            pass  # FVG count already tracked via zone_manager

        self.output.snapshot_logger.write(snapshot)

    def summary(self) -> dict:
        """Print summary statistics."""
        return {
            "total_events": self.output.event_logger.row_count,
            "bar_count": len(self.all_bars),
            "violations": len(self.guard.violations),
            "active_obs": self.ob_engine.active_count(),
            "active_fvgs": self.fvg_engine.active_count,
        }
