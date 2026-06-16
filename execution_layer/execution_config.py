"""
Execution Config — YAML-driven, không hard-code.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal
import yaml
import json
import os


@dataclass
class SpreadConfig:
    mode: str = "from_data"              # "from_data" or "fixed"
    fallback_points: dict = field(default_factory=lambda: {
        "XAUUSD": 25,
        "GBPUSD": 12,
        "EURUSD": 10,
    })


@dataclass
class SlippageConfig:
    mode: str = "fixed"                  # "fixed" or "atr_ratio"
    points: dict = field(default_factory=lambda: {
        "XAUUSD": 5,
        "GBPUSD": 2,
        "EURUSD": 2,
    })
    atr_ratio: float = 0.1              # % of ATR if mode = "atr_ratio"


@dataclass
class CommissionConfig:
    mode: str = "per_lot"                # "per_lot", "per_million", "none"
    per_lot_round_turn: dict = field(default_factory=lambda: {
        "XAUUSD": 7.0,
        "GBPUSD": 7.0,
        "EURUSD": 7.0,
    })
    per_million: dict = field(default_factory=dict)


@dataclass
class AccountConfig:
    initial_balance: float = 10000.0
    currency: str = "USD"
    leverage: int = 100


@dataclass
class MarginConfig:
    enabled: bool = True
    stop_out_level: float = 0.5          # 50% margin level → stop out


@dataclass
class PositionConfig:
    allow_hedging: bool = False
    max_positions_per_symbol: int = 1
    max_total_positions: int = 3


@dataclass
class RiskLimitsConfig:
    max_daily_loss_pct: float = 3.0
    max_open_risk_pct: float = 2.0
    max_daily_orders: int = 10


@dataclass
class SessionConfig:
    """Forex session hooks — V1 minimal."""
    enabled: bool = True
    rollover_time: str = "17:00"         # NY close, EST
    weekend_gap: bool = True


@dataclass
class SwapConfig:
    enabled: bool = False                # V1: tắt swap
    long_swap_per_lot: float = 0.0
    short_swap_per_lot: float = 0.0


@dataclass
class IntrabarConfig:
    """Intrabar resolution model — V1: conservative."""
    model: str = "conservative_ohlc"     # "conservative_ohlc", "synthetic_path", "tick_replay"
    adversarial: bool = True


@dataclass
class ExecutionConfig:
    """Top-level config cho Execution Engine."""

    fill_model: str = "conservative_ohlc"
    trade_on_close: bool = False          # True = khớp tại close của signal bar

    spread: SpreadConfig = field(default_factory=SpreadConfig)
    slippage: SlippageConfig = field(default_factory=SlippageConfig)
    commission: CommissionConfig = field(default_factory=CommissionConfig)
    account: AccountConfig = field(default_factory=AccountConfig)
    margin: MarginConfig = field(default_factory=MarginConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
    risk_limits: RiskLimitsConfig = field(default_factory=RiskLimitsConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    swap: SwapConfig = field(default_factory=SwapConfig)
    intrabar: IntrabarConfig = field(default_factory=IntrabarConfig)

    # Paths
    symbol_specs_path: str = "symbol_specs.json"

    @classmethod
    def from_yaml(cls, path: str) -> "ExecutionConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls._from_dict(data or {})

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionConfig":
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "ExecutionConfig":
        cfg = cls()

        exec_data = data.get("execution", data)

        if "fill_model" in exec_data:
            cfg.fill_model = exec_data["fill_model"]
        if "trade_on_close" in exec_data:
            cfg.trade_on_close = exec_data["trade_on_close"]

        # Sub-configs
        sub_configs = [
            ("spread", SpreadConfig),
            ("slippage", SlippageConfig),
            ("commission", CommissionConfig),
            ("account", AccountConfig),
            ("margin", MarginConfig),
            ("position", PositionConfig),
            ("risk_limits", RiskLimitsConfig),
            ("session", SessionConfig),
            ("swap", SwapConfig),
            ("intrabar", IntrabarConfig),
        ]

        for key, cls_type in sub_configs:
            if key in exec_data:
                merged = {**cfg.__dict__[key].__dict__, **exec_data[key]}
                setattr(cfg, key, cls_type(**merged))

        if "symbol_specs_path" in exec_data:
            cfg.symbol_specs_path = exec_data["symbol_specs_path"]

        return cfg

    def to_dict(self) -> dict:
        return {
            "fill_model": self.fill_model,
            "trade_on_close": self.trade_on_close,
            "spread": self.spread.__dict__,
            "slippage": self.slippage.__dict__,
            "commission": self.commission.__dict__,
            "account": self.account.__dict__,
            "margin": self.margin.__dict__,
            "position": self.position.__dict__,
            "risk_limits": self.risk_limits.__dict__,
            "session": self.session.__dict__,
            "swap": self.swap.__dict__,
            "intrabar": self.intrabar.__dict__,
            "symbol_specs_path": self.symbol_specs_path,
        }


# ── Default YAML ──────────────────────────────────────────────────

DEFAULT_EXECUTION_YAML = """\
execution:
  fill_model: conservative_ohlc
  trade_on_close: false

  spread:
    mode: from_data
    fallback_points:
      XAUUSD: 25
      GBPUSD: 12
      EURUSD: 10

  slippage:
    mode: fixed
    points:
      XAUUSD: 5
      GBPUSD: 2
      EURUSD: 2

  commission:
    mode: per_lot
    per_lot_round_turn:
      XAUUSD: 7.0
      GBPUSD: 7.0
      EURUSD: 7.0

  account:
    initial_balance: 10000
    currency: USD
    leverage: 100

  margin:
    enabled: true
    stop_out_level: 0.5

  position:
    allow_hedging: false
    max_positions_per_symbol: 1
    max_total_positions: 3

  risk_limits:
    max_daily_loss_pct: 3.0
    max_open_risk_pct: 2.0
    max_daily_orders: 10

  intrabar:
    model: conservative_ohlc
    adversarial: true
"""
