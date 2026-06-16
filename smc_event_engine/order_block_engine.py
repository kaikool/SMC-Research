"""
Order Block Engine — LuxAlgo extraction + spec lifecycle.

Extraction (LuxAlgo):
  - Bullish structure break → find bar with lowest parsedLow from pivot to current
  - Bearish structure break → find bar with highest parsedHigh from pivot to current
  - Volatile bar filter: (high-low) >= 2×ATR → swap parsedHigh/parsedLow

Lifecycle (spec):
  - created → active → touched → (partially mitigated) → fully mitigated / invalidated / expired
"""

from typing import Optional
from .models import OrderBlock, Bar, Event, Snapshot
from .config import (
    EngineConfig, BULLISH, BEARISH, SWING, INTERNAL,
    OB_ACTIVE, OB_MITIGATED, OB_INVALIDATED, OB_EXPIRED,
    MITIGATION_CLOSE, MITIGATION_HIGHLOW,
)
from .no_lookahead_guard import NoLookaheadGuard


class OrderBlockEngine:
    """Manages order block creation and lifecycle."""

    def __init__(self, config: EngineConfig, guard: NoLookaheadGuard):
        self.cfg = config
        self.guard = guard

        # OB storage (LuxAlgo-style arrays)
        self.swing_order_blocks: list[OrderBlock] = []
        self.internal_order_blocks: list[OrderBlock] = []

        # Parsed prices (LuxAlgo volatility filter)
        self.parsed_highs: list[float] = []
        self.parsed_lows: list[float] = []
        self.raw_highs: list[float] = []
        self.raw_lows: list[float] = []
        self.bar_times: list[int] = []

        # OB counter for unique IDs
        self._ob_counter = 0

    def on_bar(self, bar: Bar, bar_index: int,
               atr_value: float) -> None:
        """Update parsed prices for this bar."""
        # Volatility filter (LuxAlgo)
        high_vol = False
        if self.cfg.order_block.volatility_filter:
            vol_measure = atr_value
            if self.cfg.order_block.filter_method == "Range" and bar_index > 0:
                vol_measure = (self.cfg.order_block.atr_period > 0 and
                               atr_value > 0) and atr_value or (bar.high - bar.low)
            high_vol = (bar.high - bar.low) >= (self.cfg.order_block.volatility_multiplier * vol_measure)

        parsed_high = bar.low if high_vol else bar.high
        parsed_low = bar.high if high_vol else bar.low

        self.parsed_highs.append(parsed_high)
        self.parsed_lows.append(parsed_low)
        self.raw_highs.append(bar.high)
        self.raw_lows.append(bar.low)
        self.bar_times.append(bar.timestamp)

    def create_from_structure_break(self, direction: int, pivot_bar: int,
                                    pivot_price: float, pivot_timestamp: int,
                                    current_bar: int, current_timestamp: int,
                                    level: str = SWING,
                                    source_event: str = "") -> Optional[OrderBlock]:
        """
        LuxAlgo OB extraction after BOS/CHOCH.
        
        Args:
            direction: BULLISH or BEARISH (direction of the break)
            pivot_bar: bar_index of the pivot that was broken
            pivot_price: price level of the pivot
            current_bar: current bar_index
            level: "swing" or "internal"
            source_event: e.g. "BOS_BULLISH"
        """
        is_swing = (level == SWING)
        if not is_swing and not self.cfg.show_internals:
            return None
        if is_swing and not self.cfg.order_block.swing_max_display:
            return None

        max_display = (self.cfg.order_block.swing_max_display if is_swing
                       else self.cfg.order_block.internal_max_display)
        if max_display <= 0:
            return None

        # Need at least 2 bars to slice
        if current_bar <= pivot_bar:
            return None

        # Slice from pivot to current (LuxAlgo: slice(pivot.barIndex, bar_index))
        start = pivot_bar
        end = current_bar  # exclusive

        if start >= len(self.parsed_highs) or end > len(self.parsed_highs):
            return None

        if direction == BEARISH:
            # Find bar with highest parsedHigh
            segment = self.parsed_highs[start:end]
            if not segment:
                return None
            local_idx = segment.index(max(segment))
            parsed_idx = start + local_idx
        else:
            # BULLISH: find bar with lowest parsedLow
            segment = self.parsed_lows[start:end]
            if not segment:
                return None
            local_idx = segment.index(min(segment))
            parsed_idx = start + local_idx

        ob_top = self.parsed_highs[parsed_idx]
        ob_bottom = self.parsed_lows[parsed_idx]
        ob_mid = (ob_top + ob_bottom) / 2
        ob_time = self.bar_times[parsed_idx]

        # Store the OB
        self._ob_counter += 1
        ob_id = f"OB_{self._ob_counter}"
        direction_label = "BULLISH" if direction == BULLISH else "BEARISH"

        ob = OrderBlock(
            id=ob_id,
            direction=direction,
            structure_type=level,
            origin_bar=parsed_idx,
            created_at=ob_time,
            active_from=current_timestamp,
            top=ob_top,
            bottom=ob_bottom,
            mid=ob_mid,
            status=OB_ACTIVE,
            source_event=source_event,
            source_pivot_level=pivot_price,
            source_pivot_bar=pivot_bar,
        )

        # Push to the front (LuxAlgo unshift)
        storage = self.swing_order_blocks if is_swing else self.internal_order_blocks
        if len(storage) >= 100:   # LuxAlgo: max 100
            storage.pop()
        storage.insert(0, ob)

        return ob

    def check_mitigations(self, bar: Bar, bar_index: int,
                          atr_value: float) -> list[Event]:
        """
        Check all active OBs for touch/mitigation/invalidation/expiry.
        LuxAlgo deletion logic + spec lifecycle.
        """
        events: list[Event] = []
        use_close = (self.cfg.order_block.mitigation_method == MITIGATION_CLOSE)

        # Check swing OBs
        s_events = self._check_mitigations_for(
            self.swing_order_blocks, bar, bar_index,
            use_close, SWING)
        events.extend(s_events)

        # Check internal OBs
        i_events = self._check_mitigations_for(
            self.internal_order_blocks, bar, bar_index,
            use_close, INTERNAL)
        events.extend(i_events)

        return events

    def _check_mitigations_for(self, storage: list[OrderBlock],
                                bar: Bar, bar_index: int,
                                use_close: bool, level: str) -> list[Event]:
        """Check mitigations for one OB storage list."""
        events: list[Event] = []
        to_remove: list[int] = []

        for idx, ob in enumerate(storage):
            if ob.status != OB_ACTIVE:
                continue

            # ── Check invalidation (close through the entire OB) ──
            if ob.direction == BULLISH:
                # Bullish OB: low of bar goes below OB bottom → invalidation
                if self.cfg.order_block.invalidation_method == "close_through":
                    if bar.close < ob.bottom:
                        ob.status = OB_INVALIDATED
                        ob.invalidated_at = bar.timestamp
                        events.append(self._make_mitigation_event(ob, bar, bar_index, "OB_INVALIDATED"))
                        to_remove.append(idx)
                        continue
                # Mitigation (LuxAlgo): low < OB.low OR close < OB.low
                mit_source = bar.low if not use_close else bar.close
                if mit_source < ob.bottom:
                    ob.status = OB_MITIGATED
                    ob.mitigated_at = bar.timestamp
                    if ob.first_touch_at is None:
                        ob.first_touch_at = bar.timestamp
                    ob.touched_ratio = 1.0
                    events.append(self._make_mitigation_event(ob, bar, bar_index, "OB_MITIGATED"))
                    to_remove.append(idx)

            else:  # BEARISH
                # Bearish OB: high of bar goes above OB top → invalidation
                if self.cfg.order_block.invalidation_method == "close_through":
                    if bar.close > ob.top:
                        ob.status = OB_INVALIDATED
                        ob.invalidated_at = bar.timestamp
                        events.append(self._make_mitigation_event(ob, bar, bar_index, "OB_INVALIDATED"))
                        to_remove.append(idx)
                        continue
                mit_source = bar.high if not use_close else bar.close
                if mit_source > ob.top:
                    ob.status = OB_MITIGATED
                    ob.mitigated_at = bar.timestamp
                    if ob.first_touch_at is None:
                        ob.first_touch_at = bar.timestamp
                    ob.touched_ratio = 1.0
                    events.append(self._make_mitigation_event(ob, bar, bar_index, "OB_MITIGATED"))
                    to_remove.append(idx)

            # ── Check first touch (the other side touched the OB zone) ──
            if ob.first_touch_at is None:
                if ob.direction == BULLISH:
                    if bar.low <= ob.top and bar.high >= ob.bottom:
                        ob.first_touch_at = bar.timestamp
                        events.append(self._make_mitigation_event(ob, bar, bar_index, "OB_TOUCHED"))
                else:
                    if bar.high >= ob.bottom and bar.low <= ob.top:
                        ob.first_touch_at = bar.timestamp
                        events.append(self._make_mitigation_event(ob, bar, bar_index, "OB_TOUCHED"))

            # ── Check expiry by max age ──
            if self.cfg.order_block.max_age_bars > 0:
                age = bar_index - ob.origin_bar
                if age > self.cfg.order_block.max_age_bars:
                    ob.status = OB_EXPIRED
                    ob.expired_at = bar.timestamp
                    events.append(self._make_mitigation_event(ob, bar, bar_index, "OB_EXPIRED"))
                    to_remove.append(idx)

        # Remove in reverse order (preserve indices)
        for idx in sorted(to_remove, reverse=True):
            storage.pop(idx)

        return events

    def _make_mitigation_event(self, ob: OrderBlock, bar: Bar,
                                bar_index: int, event_type: str) -> Event:
        return Event(
            timestamp=bar.timestamp,
            bar_index=bar_index,
            symbol=bar.symbol,
            timeframe=bar.timeframe,
            event_type=event_type,
            direction=ob.direction,
            price=bar.close,
            level_top=ob.top,
            level_bottom=ob.bottom,
            source_object_id=ob.source_event,
            object_id=ob.id,
            status=ob.status,
            confirmed=True,
        )

    def active_count(self, level: str = "") -> int:
        """Count active OBs."""
        count = 0
        if level in ("", SWING):
            count += sum(1 for ob in self.swing_order_blocks if ob.status == OB_ACTIVE)
        if level in ("", INTERNAL):
            count += sum(1 for ob in self.internal_order_blocks if ob.status == OB_ACTIVE)
        return count
