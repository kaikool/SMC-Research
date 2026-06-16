"""
Structure Engine — BOS / CHOCH detection.

LuxAlgo SMC logic:
  - close crossover swing_high level → BULLISH break
    • trend was BEARISH → CHOCH (reversal)
    • trend was BULLISH → BOS (continuation)
  - close crossunder swing_low level → BEARISH break
    • trend was BULLISH → CHOCH (reversal)
    • trend was BEARISH → BOS (continuation)

Each pivot can only be broken once (crossed flag).
"""

from typing import Optional
from .models import Bar, PivotPoint, Event, Snapshot
from .config import EngineConfig, BULLISH, BEARISH, SWING, INTERNAL
from .no_lookahead_guard import NoLookaheadGuard


class StructureEngine:
    """Detect BOS and CHOCH events from swing/internal pivots."""

    def __init__(self, config: EngineConfig, guard: NoLookaheadGuard):
        self.cfg = config
        self.guard = guard

        # Trends (LuxAlgo: swingTrend, internalTrend)
        self.swing_trend = 0       # 0=neutral, +1=BULLISH, -1=BEARISH
        self.internal_trend = 0

        # Tracks last BOS/CHOCH direction for snapshot
        self.last_bos_direction = 0
        self.last_choch_direction = 0

    def on_bar(self, bar: Bar, bar_index: int, prev_close: float,
               swing_high: PivotPoint, swing_low: PivotPoint,
               internal_high: PivotPoint, internal_low: PivotPoint,
               snapshot: Snapshot) -> list[Event]:
        """
        Check for BOS/CHOCH on this bar.

        Must be called AFTER SwingEngine.on_bar() because pivots
        need to be updated before structure checks.
        """
        events: list[Event] = []

        # ── Swing structure ────────────────────────────────────────
        if self.cfg.show_swing_structure or self.cfg.order_block.swing_max_display > 0:
            s_events = self._check_structure(
                bar, bar_index, prev_close,
                swing_high, swing_low,
                level=SWING,
                trend_ref=lambda: self.swing_trend,
                set_trend=lambda v: setattr(self, "swing_trend", v),
                snapshot=snapshot,
            )
            events.extend(s_events)

        # ── Internal structure ─────────────────────────────────────
        if self.cfg.show_internals or self.cfg.order_block.internal_max_display > 0:
            i_events = self._check_structure(
                bar, bar_index, prev_close,
                internal_high, internal_low,
                level=INTERNAL,
                trend_ref=lambda: self.internal_trend,
                set_trend=lambda v: setattr(self, "internal_trend", v),
                snapshot=snapshot,
                swing_high=swing_high,
                swing_low=swing_low,
            )
            events.extend(i_events)

        # Update snapshot
        snapshot.last_bos_direction = self.last_bos_direction
        snapshot.last_choch_direction = self.last_choch_direction
        snapshot.current_trend = self.swing_trend
        snapshot.swing_high_crossed = swing_high.crossed
        snapshot.swing_low_crossed = swing_low.crossed

        return events

    def _check_structure(self, bar: Bar, bar_index: int, prev_close: float,
                         pivot_high: PivotPoint, pivot_low: PivotPoint,
                         level: str, trend_ref, set_trend,
                         snapshot: Snapshot,
                         swing_high: Optional[PivotPoint] = None,
                         swing_low: Optional[PivotPoint] = None) -> list[Event]:
        """Check both bullish and bearish structure breaks for a level."""
        events: list[Event] = []
        is_internal = (level == INTERNAL)

        # ── Bullish break: close crosses above swing_high ──────────
        if pivot_high.price > 0 and not pivot_high.crossed:

            # LuxAlgo extra condition for internal
            extra_ok = True
            if is_internal and swing_high is not None:
                # Internal only fires if its pivot differs from swing pivot
                extra_ok = (pivot_high.price != swing_high.price)

            # Confluence filter (LuxAlgo: bullishBar / bearishBar)
            if is_internal and self.cfg.internal_confluence_filter:
                upper_wick = bar.high - max(bar.close, bar.open)
                lower_wick = min(bar.close, bar.open) - bar.low
                bullish_bar = upper_wick > lower_wick
                extra_ok = extra_ok and bullish_bar

            # Crossover check: prev_close <= level AND close > level
            if (prev_close <= pivot_high.price < bar.close) and extra_ok:
                pivot_high.crossed = True
                current_trend = trend_ref()

                is_choch = (current_trend == BEARISH)
                tag = "CHOCH" if is_choch else "BOS"
                new_trend = BULLISH
                set_trend(new_trend)

                if is_choch:
                    self.last_choch_direction = BULLISH
                else:
                    self.last_bos_direction = BULLISH

                event_type = f"{tag}_BULLISH"
                if is_internal:
                    event_type = f"INTERNAL_{event_type}"

                events.append(Event(
                    timestamp=bar.timestamp,
                    bar_index=bar_index,
                    symbol=bar.symbol,
                    timeframe=bar.timeframe,
                    event_type=event_type,
                    direction=BULLISH,
                    price=bar.close,
                    level_top=0.0,
                    level_bottom=pivot_high.price,
                    source_object_id=f"{level}_high_{pivot_high.bar_index}",
                    object_id="",
                    status="confirmed",
                    confirmed=True,
                    metadata=f'break_level={pivot_high.price:.5f},tag={tag}',
                ))

        # ── Bearish break: close crosses below swing_low ─────────
        if pivot_low.price > 0 and not pivot_low.crossed:

            extra_ok = True
            if is_internal and swing_low is not None:
                extra_ok = (pivot_low.price != swing_low.price)

            if is_internal and self.cfg.internal_confluence_filter:
                upper_wick = bar.high - max(bar.close, bar.open)
                lower_wick = min(bar.close, bar.open) - bar.low
                bearish_bar = upper_wick < lower_wick
                extra_ok = extra_ok and bearish_bar

            if (prev_close >= pivot_low.price > bar.close) and extra_ok:
                pivot_low.crossed = True
                current_trend = trend_ref()

                is_choch = (current_trend == BULLISH)
                tag = "CHOCH" if is_choch else "BOS"
                new_trend = BEARISH
                set_trend(new_trend)

                if is_choch:
                    self.last_choch_direction = BEARISH
                else:
                    self.last_bos_direction = BEARISH

                event_type = f"{tag}_BEARISH"
                if is_internal:
                    event_type = f"INTERNAL_{event_type}"

                events.append(Event(
                    timestamp=bar.timestamp,
                    bar_index=bar_index,
                    symbol=bar.symbol,
                    timeframe=bar.timeframe,
                    event_type=event_type,
                    direction=BEARISH,
                    price=bar.close,
                    level_top=pivot_low.price,
                    level_bottom=0.0,
                    source_object_id=f"{level}_low_{pivot_low.bar_index}",
                    object_id="",
                    status="confirmed",
                    confirmed=True,
                    metadata=f'break_level={pivot_low.price:.5f},tag={tag}',
                ))

        return events
