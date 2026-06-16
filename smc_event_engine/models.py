"""
Data models — all typed, all documented.
Every SMC concept (pivot, OB, FVG, zone, event, snapshot) lives here.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum, auto
from .config import (
    BULLISH, BEARISH, SWING, INTERNAL,
    OB_ACTIVE, OB_MITIGATED, OB_INVALIDATED, OB_EXPIRED,
    FVG_ACTIVE, FVG_PARTIAL, FVG_FILLED, FVG_INVALIDATED,
)


# ── Pivot Point ───────────────────────────────────────────────────────
@dataclass
class PivotPoint:
    """A confirmed swing high or swing low (internal or swing)."""
    pivot_type: str                    # "swing_high", "swing_low", "internal_high", "internal_low"
    price: float
    bar_index: int
    timestamp: int                     # millis
    leg: int = 0                       # 0=BEARISH_LEG, 1=BULLISH_LEG at time of detection
    # For LuxAlgo-style pivot tracking
    last_level: float = 0.0
    crossed: bool = False


# ── Order Block ───────────────────────────────────────────────────────
@dataclass
class OrderBlock:
    """Full lifecycle — LuxAlgo extraction + spec lifecycle."""
    id: str
    direction: int                     # BULLISH (+1) or BEARISH (-1)
    structure_type: str                # SWING or INTERNAL
    origin_bar: int
    created_at: int                    # millis
    active_from: int = 0               # millis — when it becomes "usable"
    top: float = 0.0
    bottom: float = 0.0
    mid: float = 0.0
    status: str = OB_ACTIVE
    source_event: str = ""             # e.g. "BOS_BULLISH"
    source_pivot_level: float = 0.0
    source_pivot_bar: int = 0
    first_touch_at: Optional[int] = None
    mitigated_at: Optional[int] = None
    invalidated_at: Optional[int] = None
    expired_at: Optional[int] = None
    touched_ratio: float = 0.0         # 0.0 → 1.0

    @property
    def is_active(self) -> bool:
        return self.status == OB_ACTIVE

    @property
    def height(self) -> float:
        return self.top - self.bottom


# ── Fair Value Gap ────────────────────────────────────────────────────
@dataclass
class FVG:
    """FVG with 3-bar structure (LuxAlgo HTF style)."""
    id: str
    direction: int                     # BULLISH or BEARISH
    top: float
    bottom: float
    mid: float = 0.0
    left_bar: int = 0
    middle_bar: int = 0
    right_bar: int = 0
    created_at: int = 0
    filled_ratio: float = 0.0
    status: str = FVG_ACTIVE
    filled_at: Optional[int] = None
    invalidated_at: Optional[int] = None

    @property
    def is_active(self) -> bool:
        return self.status == FVG_ACTIVE


# ── Premium / Discount Range ──────────────────────────────────────────
@dataclass
class PDRange:
    """Active premium/discount range."""
    range_high: float
    range_low: float
    equilibrium: float = 0.0
    premium_zone_top: float = 0.0
    premium_zone_bottom: float = 0.0
    discount_zone_top: float = 0.0
    discount_zone_bottom: float = 0.0
    active_from: int = 0
    source_swing_high_bar: int = 0
    source_swing_low_bar: int = 0

    def __post_init__(self):
        if self.equilibrium == 0.0:
            self.equilibrium = (self.range_high + self.range_low) / 2


# ── Equal High/Low ────────────────────────────────────────────────────
@dataclass
class EqualLevel:
    """Detected equal high or equal low."""
    id: str
    level_type: str                    # "equal_high" or "equal_low"
    price: float
    bar_index: int
    timestamp: int
    confirmation_bar: int = 0
    distance: float = 0.0              # distance in ATR units


# ── Liquidity Zone ────────────────────────────────────────────────────
@dataclass
class LiquidityZone:
    """Buy-side or sell-side liquidity zone."""
    id: str
    side: str                          # "buy_side", "sell_side"
    level: float
    top: float
    bottom: float
    created_at: int
    swept_at: Optional[int] = None
    sweep_type: str = ""               # "wick", "close", "wick+displacement"
    status: str = "active"


# ── Zone — unified wrapper for Zone Manager ───────────────────────────
@dataclass
class Zone:
    """Unified zone wrapper — OB, FVG, liquidity, or PD."""
    id: str
    zone_type: str                     # "order_block", "fvg", "liquidity", "pd_range"
    direction: int                     # BULLISH / BEARISH / 0 (neutral)
    top: float
    bottom: float
    created_at: int
    status: str = "active"
    source_object_id: str = ""
    reference: object = None           # The original object (OrderBlock, FVG, etc.)


# ── Event ─────────────────────────────────────────────────────────────
@dataclass
class Event:
    """A timestamped SMC event — the primary output of the engine."""
    timestamp: int                     # millis
    bar_index: int
    symbol: str
    timeframe: str
    event_type: str                    # e.g. "SWING_HIGH", "SWING_LOW", "BOS", "CHOCH", ...
    direction: int                     # BULLISH / BEARISH / 0
    price: float = 0.0
    level_top: float = 0.0
    level_bottom: float = 0.0
    source_object_id: str = ""
    object_id: str = ""
    status: str = ""
    confirmed: bool = True
    metadata: str = ""                 # JSON-encoded extras


# ── Snapshot ──────────────────────────────────────────────────────────
@dataclass
class Snapshot:
    """Per-bar state dump — critical for debugging repaint errors."""
    timestamp: int
    bar_index: int
    current_trend: int = 0             # BULLISH / BEARISH / 0
    last_swing_high: float = 0.0
    last_swing_low: float = 0.0
    last_internal_high: float = 0.0
    last_internal_low: float = 0.0
    active_ob_count: int = 0
    active_fvg_count: int = 0
    active_liquidity_count: int = 0
    in_premium: bool = False
    in_discount: bool = False
    last_bos_direction: int = 0
    last_choch_direction: int = 0
    swing_high_crossed: bool = False
    swing_low_crossed: bool = False
    last_swing_leg: int = 0
    last_internal_leg: int = 0


# ── Bar data ──────────────────────────────────────────────────────────
@dataclass
class Bar:
    """One OHLCV bar — input to the engine."""
    timestamp: int                     # millis
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_volume: float = 0.0
    spread: float = 0.0
    symbol: str = ""
    timeframe: str = ""

    def validate(self) -> list[str]:
        """Return list of validation errors."""
        errors = []
        if self.high < max(self.open, self.close):
            errors.append(f"high ({self.high}) < max(open, close)")
        if self.low > min(self.open, self.close):
            errors.append(f"low ({self.low}) > min(open, close)")
        if self.open < 0 or self.high < 0 or self.low < 0 or self.close < 0:
            errors.append("negative price")
        if self.volume < 0:
            errors.append("negative volume")
        return errors
