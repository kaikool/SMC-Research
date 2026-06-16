"""
Premium / Discount Engine — zones based on trailing swing extremes.

LuxAlgo logic:
  - Range = trailing.top → trailing.bottom (continuously updated)
  - Premium zone: top 5% (range_high to 0.95×range_high + 0.05×range_low)
  - Equilibrium: midpoint (avg of top & bottom)
  - Discount zone: bottom 5% (0.95×bottom + 0.05×top → bottom)

Events: PD_RANGE_CREATED, PRICE_ENTER_PREMIUM, PRICE_ENTER_DISCOUNT, PRICE_CROSS_EQUILIBRIUM
"""

from typing import Optional
from .models import PDRange, Bar, Event, Snapshot
from .config import EngineConfig, BULLISH, BEARISH


class PremiumDiscountEngine:
    """Manages premium/discount zones based on swing extremes."""

    def __init__(self, config: EngineConfig):
        self.cfg = config
        self.active_range: Optional[PDRange] = None
        self._last_in_premium: Optional[bool] = None
        self._last_in_discount: Optional[bool] = None
        self._last_above_equilibrium: Optional[bool] = None

    def update_trailing_extremes(self, trail_top: float, trail_bottom: float,
                                  trail_top_bar: int, trail_bottom_bar: int,
                                  trail_top_time: int, trail_bottom_time: int,
                                  bar: Bar, bar_index: int) -> list[Event]:
        """Update the PD range from trailing extremes. Returns events."""
        events: list[Event] = []

        if trail_top <= trail_bottom or trail_top == 0 or trail_bottom == float("inf"):
            return events

        prev_range = self.active_range

        # Calculate zones (LuxAlgo logic)
        eq = (trail_top + trail_bottom) / 2
        premium_top = trail_top
        premium_bottom = 0.95 * trail_top + 0.05 * trail_bottom
        discount_top = 0.95 * trail_bottom + 0.05 * trail_top
        discount_bottom = trail_bottom

        if self.active_range is None:
            # Create new range
            self.active_range = PDRange(
                range_high=trail_top,
                range_low=trail_bottom,
                equilibrium=eq,
                premium_zone_top=premium_top,
                premium_zone_bottom=premium_bottom,
                discount_zone_top=discount_top,
                discount_zone_bottom=discount_bottom,
                active_from=bar.timestamp,
                source_swing_high_bar=trail_top_bar,
                source_swing_low_bar=trail_bottom_bar,
            )
            events.append(Event(
                timestamp=bar.timestamp, bar_index=bar_index,
                symbol=bar.symbol, timeframe=bar.timeframe,
                event_type="PD_RANGE_CREATED", direction=0,
                price=bar.close, level_top=trail_top, level_bottom=trail_bottom,
                object_id="pd_range_main", status="active", confirmed=True,
            ))
        else:
            # Update existing range
            self.active_range.range_high = trail_top
            self.active_range.range_low = trail_bottom
            self.active_range.equilibrium = eq
            self.active_range.premium_zone_top = premium_top
            self.active_range.premium_zone_bottom = premium_bottom
            self.active_range.discount_zone_top = discount_top
            self.active_range.discount_zone_bottom = discount_bottom

        # Check price position
        in_premium = bar.close > premium_bottom
        in_discount = bar.close < discount_top

        if self._last_in_premium is not None and in_premium != self._last_in_premium:
            if in_premium:
                events.append(Event(
                    timestamp=bar.timestamp, bar_index=bar_index,
                    symbol=bar.symbol, timeframe=bar.timeframe,
                    event_type="PRICE_ENTER_PREMIUM", direction=BEARISH,
                    price=bar.close, level_top=trail_top, level_bottom=trail_bottom,
                    status="active", confirmed=True,
                ))

        if self._last_in_discount is not None and in_discount != self._last_in_discount:
            if in_discount:
                events.append(Event(
                    timestamp=bar.timestamp, bar_index=bar_index,
                    symbol=bar.symbol, timeframe=bar.timeframe,
                    event_type="PRICE_ENTER_DISCOUNT", direction=BULLISH,
                    price=bar.close, level_top=trail_top, level_bottom=trail_bottom,
                    status="active", confirmed=True,
                ))

        # Equilibrium cross
        above_eq = bar.close > eq
        if self._last_above_equilibrium is not None and above_eq != self._last_above_equilibrium:
            events.append(Event(
                timestamp=bar.timestamp, bar_index=bar_index,
                symbol=bar.symbol, timeframe=bar.timeframe,
                event_type="PRICE_CROSS_EQUILIBRIUM",
                direction=BULLISH if above_eq else BEARISH,
                price=bar.close, level_top=trail_top, level_bottom=trail_bottom,
                status="active", confirmed=True,
            ))

        self._last_in_premium = in_premium
        self._last_in_discount = in_discount
        self._last_above_equilibrium = above_eq

        return events

    def update_snapshot(self, snapshot: Snapshot, close: float):
        """Fill PD-related fields in a snapshot."""
        if self.active_range:
            snapshot.in_premium = close > self.active_range.premium_zone_bottom
            snapshot.in_discount = close < self.active_range.discount_zone_top
