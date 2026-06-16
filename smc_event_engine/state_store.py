"""
State Store — internal market state used across engines.

Tracks:
  - current_trend (swing & internal)
  - last pivot points
  - active zones/OBs/FVGs
  - HTF state (for MTF engine)

This is the "memory" of the SMC engine.
"""

from dataclasses import dataclass, field
from typing import Optional
from .models import Bar, PivotPoint


@dataclass
class HTFState:
    """Multi-timeframe state for one HTF timeframe."""
    timeframe: str
    current_period_start: int = 0
    last_closed: Optional[Bar] = None
    last_high: float = 0.0
    last_low: float = 0.0
    last_close: float = 0.0
    pending_bars: list[Bar] = field(default_factory=list)


@dataclass
class MarketState:
    """Full market state at any point in time."""
    # Trends
    swing_trend: int = 0          # +1=BULLISH, -1=BEARISH, 0=NEUTRAL
    internal_trend: int = 0

    # Last pivots
    last_swing_high: float = 0.0
    last_swing_low: float = 0.0
    last_swing_high_bar: int = 0
    last_swing_low_bar: int = 0
    last_internal_high: float = 0.0
    last_internal_low: float = 0.0

    # Trailing extremes
    trailing_top: float = 0.0
    trailing_bottom: float = float("inf")
    trailing_top_bar: int = 0
    trailing_bottom_bar: int = 0

    # Counts
    active_ob_count: int = 0
    active_fvg_count: int = 0
    active_liquidity_count: int = 0

    # Last structure events
    last_bos_direction: int = 0
    last_choch_direction: int = 0

    # Leg states
    swing_leg: int = 0
    internal_leg: int = 0

    # Pivot crossed flags
    swing_high_crossed: bool = False
    swing_low_crossed: bool = False
    internal_high_crossed: bool = False
    internal_low_crossed: bool = False

    # Premium/discount
    in_premium: bool = False
    in_discount: bool = False
    equilibrium: float = 0.0


class StateStore:
    """Maintains and serves the current market state."""

    def __init__(self):
        self.state = MarketState()
        self._history: list[MarketState] = []

    def save_snapshot(self) -> MarketState:
        """Deep-copy current state into history."""
        import copy
        snap = copy.deepcopy(self.state)
        self._history.append(snap)
        return snap

    def get_history(self) -> list[MarketState]:
        return self._history

    def get_latest(self) -> MarketState:
        return self.state

    def to_dict(self) -> dict:
        s = self.state
        return {
            "swing_trend": s.swing_trend,
            "internal_trend": s.internal_trend,
            "last_swing_high": s.last_swing_high,
            "last_swing_low": s.last_swing_low,
            "trailing_top": s.trailing_top,
            "trailing_bottom": s.trailing_bottom,
            "active_obs": s.active_ob_count,
            "active_fvgs": s.active_fvg_count,
            "in_premium": s.in_premium,
            "in_discount": s.in_discount,
        }
