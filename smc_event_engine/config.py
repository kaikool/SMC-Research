"""
Config system — YAML-driven, no hard-coded magic numbers.
LuxAlgo defaults are the reference; overridable via spec.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional
import yaml
import os


# ── Constants (mirror LuxAlgo enums) ──────────────────────────────────
BULLISH = +1
BEARISH = -1
BULLISH_LEG = 1
BEARISH_LEG = 0

SWING = "swing"
INTERNAL = "internal"

OB_ACTIVE = "active"
OB_MITIGATED = "mitigated"
OB_INVALIDATED = "invalidated"
OB_EXPIRED = "expired"

FVG_ACTIVE = "active"
FVG_PARTIAL = "partial"
FVG_FILLED = "filled"
FVG_INVALIDATED = "invalidated"

BREAK_CLOSE = "close"
BREAK_WICK = "wick"
MITIGATION_WICK = "wick_touch"
MITIGATION_CLOSE = "close_through"
MITIGATION_HIGHLOW = "high_low"


@dataclass
class SwingConfig:
    """Pivot detection — LuxAlgo leg method with configurable left/right."""
    left: int = 5
    right: int = 5
    use_close_break: bool = True


@dataclass
class StructureConfig:
    """BOS / CHOCH detection rules."""
    bos_break_method: str = BREAK_CLOSE       # close or wick
    choch_break_method: str = BREAK_CLOSE     # close or wick
    require_close_for_choch: bool = True


@dataclass
class OrderBlockConfig:
    """OB extraction & lifecycle — LuxAlgo style + spec lifecycle."""
    use_body_only: bool = False
    mitigation_method: str = MITIGATION_HIGHLOW   # LuxAlgo default: high/low
    invalidation_method: str = MITIGATION_CLOSE
    max_active: int = 20
    max_age_bars: int = 500
    volatility_filter: bool = True                # LuxAlgo: skip OB on high-vol bars
    volatility_multiplier: float = 2.0            # (high-low) >= mult * ATR → volatile bar
    atr_period: int = 200
    filter_method: str = "Atr"                    # Atr or Range (LuxAlgo)
    internal_max_display: int = 5
    swing_max_display: int = 5


@dataclass
class FVGConfig:
    """Fair Value Gap — LuxAlgo HTF 3-bar method."""
    auto_threshold: bool = True
    threshold_multiplier: float = 2.0
    min_size_atr: float = 0.0
    fill_method: str = "full"                     # full or partial
    extend_bars: int = 1
    use_htf: bool = True
    htf_timeframe: str = ""                       # empty = chart TF


@dataclass
class LiquidityConfig:
    """Equal highs/lows & sweep detection."""
    bars_confirmation: int = 3
    threshold: float = 0.1                        # fraction of ATR
    max_active_zones: int = 10


@dataclass
class PremiumDiscountConfig:
    """Premium / discount zone range."""
    premium_percent: float = 0.05                 # top 5%
    discount_percent: float = 0.05                # bottom 5%
    use_trailing_extremes: bool = True            # LuxAlgo style


@dataclass
class MTFConfig:
    """Multi-timeframe settings."""
    strict_closed_htf: bool = True
    enabled: bool = False
    htf_timeframes: list = field(default_factory=lambda: ["60", "240"])


@dataclass
class LoggingConfig:
    """Output control."""
    events_path: str = "events.csv"
    snapshots_path: str = "snapshots.csv"
    objects_path: str = "objects.csv"
    log_every_bar: bool = True
    snapshot_every_bar: bool = True


@dataclass
class EngineConfig:
    """Top-level config — merge of all sub-configs + LuxAlgo inputs."""
    swing: SwingConfig = field(default_factory=SwingConfig)
    structure: StructureConfig = field(default_factory=StructureConfig)
    order_block: OrderBlockConfig = field(default_factory=OrderBlockConfig)
    fvg: FVGConfig = field(default_factory=FVGConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    premium_discount: PremiumDiscountConfig = field(default_factory=PremiumDiscountConfig)
    mtf: MTFConfig = field(default_factory=MTFConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # LuxAlgo UI-style toggles
    mode: str = "Historical"                # Historical / Present
    style: str = "Colored"                  # Colored / Monochrome
    show_trend_candles: bool = False

    show_internals: bool = True
    internal_bullish_filter: str = "All"    # All / BOS / CHOCH
    internal_bearish_filter: str = "All"
    internal_confluence_filter: bool = False

    show_swing_structure: bool = True
    swing_bullish_filter: str = "All"
    swing_bearish_filter: str = "All"
    show_swing_points: bool = False
    swing_length: int = 50
    internal_length: int = 5

    show_high_low_swings: bool = True
    show_premium_discount_zones: bool = False
    show_equal_highs_lows: bool = True
    show_fair_value_gaps: bool = False

    # Symbol / metadata
    symbol: str = "UNKNOWN"
    timeframe: str = ""

    @classmethod
    def from_yaml(cls, path: str) -> "EngineConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls._from_dict(data or {})

    @classmethod
    def from_dict(cls, data: dict) -> "EngineConfig":
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "EngineConfig":
        cfg = cls()

        if "swing" in data:
            cfg.swing = SwingConfig(**{**cfg.swing.__dict__, **data["swing"]})
        if "structure" in data:
            cfg.structure = StructureConfig(**{**cfg.structure.__dict__, **data["structure"]})
        if "order_block" in data:
            cfg.order_block = OrderBlockConfig(**{**cfg.order_block.__dict__, **data["order_block"]})
        if "fvg" in data:
            cfg.fvg = FVGConfig(**{**cfg.fvg.__dict__, **data["fvg"]})
        if "liquidity" in data:
            cfg.liquidity = LiquidityConfig(**{**cfg.liquidity.__dict__, **data["liquidity"]})
        if "premium_discount" in data:
            cfg.premium_discount = PremiumDiscountConfig(**{**cfg.premium_discount.__dict__, **data["premium_discount"]})
        if "mtf" in data:
            cfg.mtf = MTFConfig(**{**cfg.mtf.__dict__, **data["mtf"]})
        if "logging" in data:
            cfg.logging = LoggingConfig(**{**cfg.logging.__dict__, **data["logging"]})

        for k in ("mode", "style", "show_trend_candles", "show_internals",
                  "internal_bullish_filter", "internal_bearish_filter",
                  "internal_confluence_filter", "show_swing_structure",
                  "swing_bullish_filter", "swing_bearish_filter",
                  "show_swing_points", "swing_length", "internal_length",
                  "show_high_low_swings", "show_premium_discount_zones",
                  "show_equal_highs_lows", "show_fair_value_gaps",
                  "symbol", "timeframe"):
            if k in data:
                setattr(cfg, k, data[k])

        return cfg

    def to_dict(self) -> dict:
        d = {}
        for section_name, section in [
            ("swing", self.swing), ("structure", self.structure),
            ("order_block", self.order_block), ("fvg", self.fvg),
            ("liquidity", self.liquidity), ("premium_discount", self.premium_discount),
            ("mtf", self.mtf), ("logging", self.logging),
        ]:
            d[section_name] = {k: v for k, v in section.__dict__.items()}
        for k in ("mode", "style", "show_trend_candles", "show_internals",
                  "internal_bullish_filter", "internal_bearish_filter",
                  "internal_confluence_filter", "show_swing_structure",
                  "swing_bullish_filter", "swing_bearish_filter",
                  "show_swing_points", "swing_length", "internal_length",
                  "show_high_low_swings", "show_premium_discount_zones",
                  "show_equal_highs_lows", "show_fair_value_gaps",
                  "symbol", "timeframe"):
            d[k] = getattr(self, k)
        return d


# ── Default YAML for reference / audit ────────────────────────────────
DEFAULT_YAML = """
swing:
  left: 5
  right: 5
  use_close_break: true

structure:
  bos_break_method: close
  choch_break_method: close

order_block:
  use_body_only: false
  mitigation_method: high_low
  invalidation_method: close_through
  max_active: 20
  max_age_bars: 500
  volatility_filter: true
  volatility_multiplier: 2.0
  atr_period: 200
  filter_method: Atr
  internal_max_display: 5
  swing_max_display: 5

fvg:
  auto_threshold: true
  min_size_atr: 0.0
  fill_method: full

liquidity:
  bars_confirmation: 3
  threshold: 0.1

premium_discount:
  premium_percent: 0.05
  discount_percent: 0.05

mtf:
  strict_closed_htf: true

logging:
  events_path: events.csv
  snapshots_path: snapshots.csv
  objects_path: objects.csv
"""
