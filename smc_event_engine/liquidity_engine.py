"""
Liquidity Engine — sweep detection & equal high/low management.

LuxAlgo logic:
  - Equal highs/lows: detected during swing pivot checking
    (integrated in SwingEngine._check_equal_levels)
  - Liquidity sweeps: when price sweeps through equal highs/lows

Spec extensions:
  - Buy-side / sell-side liquidity zones
  - Wick sweep vs close sweep vs sweep + displacement
  - Stop-hunt detection
"""

from typing import Optional
from .models import Bar, PivotPoint, Event, Snapshot, LiquidityZone
from .config import EngineConfig, BULLISH, BEARISH
from .no_lookahead_guard import NoLookaheadGuard


class LiquidityEngine:
    """Detect liquidity sweeps and manage liquidity zones."""

    def __init__(self, config: EngineConfig, guard: NoLookaheadGuard):
        self.cfg = config
        self.guard = guard
        self.liquidity_zones: list[LiquidityZone] = []
        self._liq_counter = 0

    def on_bar(self, bar: Bar, bar_index: int,
               swing_high: PivotPoint, swing_low: PivotPoint,
               equal_highs: list[PivotPoint], equal_lows: list[PivotPoint]) -> list[Event]:
        """Check for liquidity sweeps on this bar.

        Each equal high/low level is swept at most once.
        """
        events: list[Event] = []

        # Track already-swept levels by their bar_index
        swept_high_indices = {z.level for z in self.liquidity_zones if z.side == "buy_side"}
        swept_low_indices = {z.level for z in self.liquidity_zones if z.side == "sell_side"}

        # Check equal high sweeps (buy-side liquidity)
        for eqh in equal_highs:
            if eqh.price <= 0:
                continue
            if eqh.price in swept_high_indices:
                continue
            if bar.high > eqh.price:
                sweep_type = self._classify_sweep(bar, eqh.price, "high")
                self._liq_counter += 1
                zone = LiquidityZone(
                    id=f"SWP_{self._liq_counter}",
                    side="buy_side",
                    level=eqh.price,
                    top=eqh.price * 1.001 if eqh.price > 0 else eqh.price + 0.001,
                    bottom=eqh.price * 0.999 if eqh.price > 0 else eqh.price - 0.001,
                    created_at=bar.timestamp,
                    swept_at=bar.timestamp,
                    sweep_type=sweep_type,
                    status="swept",
                )
                self.liquidity_zones.append(zone)
                events.append(Event(
                    timestamp=bar.timestamp, bar_index=bar_index,
                    symbol=bar.symbol, timeframe=bar.timeframe,
                    event_type="LIQUIDITY_SWEEP",
                    direction=BEARISH,
                    price=bar.close,
                    level_top=zone.top,
                    level_bottom=zone.bottom,
                    object_id=zone.id,
                    status="confirmed",
                    confirmed=True,
                    metadata=f'swept_side=buy_side,sweep_type={sweep_type}',
                ))

        # Check equal low sweeps (sell-side liquidity)
        for eql in equal_lows:
            if eql.price <= 0:
                continue
            if eql.price in swept_low_indices:
                continue
            if bar.low < eql.price:
                sweep_type = self._classify_sweep(bar, eql.price, "low")
                self._liq_counter += 1
                zone = LiquidityZone(
                    id=f"SWP_{self._liq_counter}",
                    side="sell_side",
                    level=eql.price,
                    top=eql.price * 1.001 if eql.price > 0 else eql.price + 0.001,
                    bottom=eql.price * 0.999 if eql.price > 0 else eql.price - 0.001,
                    created_at=bar.timestamp,
                    swept_at=bar.timestamp,
                    sweep_type=sweep_type,
                    status="swept",
                )
                self.liquidity_zones.append(zone)
                events.append(Event(
                    timestamp=bar.timestamp, bar_index=bar_index,
                    symbol=bar.symbol, timeframe=bar.timeframe,
                    event_type="LIQUIDITY_SWEEP",
                    direction=BULLISH,
                    price=bar.close,
                    level_top=zone.top,
                    level_bottom=zone.bottom,
                    object_id=zone.id,
                    status="confirmed",
                    confirmed=True,
                    metadata=f'swept_side=sell_side,sweep_type={sweep_type}',
                ))

        # Check swing high/low sweeps (liquidity beyond structure)
        if swing_high.price > 0 and bar.high > swing_high.price and swing_high.crossed:
            pass  # Already covered by BOS/CHOCH

        if swing_low.price > 0 and bar.low < swing_low.price and swing_low.crossed:
            pass  # Already covered by BOS/CHOCH

        return events

    def _classify_sweep(self, bar: Bar, level: float, direction: str) -> str:
        """Classify the sweep type: wick, close, or wick+displacement."""
        if direction == "high":
            # Wick sweep: high > level but close < level
            if bar.close < level:
                if bar.high - bar.close > (bar.high - bar.low) * 0.3:
                    return "wick_sweep"
                return "wick"
            else:
                # Close sweep: close > level
                displacement = bar.close - level
                avg_range = (bar.high - bar.low) or 0.001
                if displacement / avg_range > 0.5:
                    return "close_sweep_with_displacement"
                return "close_sweep"
        else:
            if bar.close > level:
                if bar.close - bar.low > (bar.high - bar.low) * 0.3:
                    return "wick_sweep"
                return "wick"
            else:
                displacement = level - bar.close
                avg_range = (bar.high - bar.low) or 0.001
                if displacement / avg_range > 0.5:
                    return "close_sweep_with_displacement"
                return "close_sweep"

    @property
    def active_count(self) -> int:
        return sum(1 for z in self.liquidity_zones if z.status == "active")
