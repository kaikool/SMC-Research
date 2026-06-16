"""
Strategy Layer — Config hệ thống.

Toàn bộ rule của strategy được cấu hình qua YAML, không hard-code.
"""

from dataclasses import dataclass, field
from typing import Optional
import yaml


# ── Default config ─────────────────────────────────────────────

DEFAULT_CONFIG_YAML = """
strategy:
  name: sweep_choch_ob_v1
  description: "Sweep → CHOCH → OB Retest"

  direction:
    allow_long: true
    allow_short: true

  symbol: "XAUUSD"
  timeframe: "15"

  # ── Đường dẫn dữ liệu Layer 1 ──
  layer1_input:
    events_path: ""        # để trống = tự động tìm
    snapshots_path: ""
    objects_path: ""

  # ── Session ──
  session:
    enabled: false
    allowed_sessions: ["london", "new_york", "asia"]
    # timezone: UTC

  # ── Setup Rule ──
  setup:
    # Sweep → CHOCH → OB
    require_sweep: true
    require_choch: true
    require_order_block: true

    # BOS → Retest
    require_bos: false

    # Khoảng cách tối đa giữa sweep và choch (bars)
    max_bars_sweep_to_choch: 100
    # Chờ entry tối đa (bars)
    max_bars_wait_entry: 100
    # Chờ đủ điều kiện (bars sau khi tạo)
    max_bars_arm: 10

    # Sweep direction required
    long_requires_sell_side_sweep: true
    short_requires_buy_side_sweep: true

  # ── Entry ──
  entry:
    type: limit                    # market / limit
    price_source: ob_mid           # ob_mid / ob_boundary / fvg_mid / price_current
    limit_price_adjustment: 0.0    # buffer thêm vào limit (pip)
    require_candle_confirm: false  # chờ nến xác nhận trước entry

  # ── Stop Loss ──
  stop_loss:
    type: sweep_extreme            # sweep_extreme / ob_extreme / swing_extreme / atr
    buffer_pips: 10.0
    buffer_atr_ratio: 0.0          # 0 = tắt, 0.1 = 10% ATR
    use_fixed_buffer: true

  # ── Take Profit ──
  take_profit:
    type: fixed_r                  # fixed_r / liquidity_target / swing_extreme / equilibrium
    r_multiple: 2.0
    use_opposing_liquidity: false

  # ── Filters ──
  filters:
    require_htf_alignment: false
    require_premium_discount: false
    max_spread_atr_ratio: 0.0     # 0 = tắt
    require_sweep_displacement: true
    min_rr_ratio: 1.5
    min_confidence: 0.3

  # ── Risk ──
  risk:
    risk_per_trade_pct: 0.5
    max_daily_loss_pct: 2.0
    max_open_positions: 1
    max_concurrent_setups: 3

  # ── Cooldown ──
  cooldown:
    bars_after_loss: 10
    bars_after_win: 3
    max_orders_per_session: 5
    max_orders_per_day: 10

  # ── Exit ──
  exit:
    use_early_exit: true
    early_exit_on_reverse_choch: true
    max_bars_no_progress: 20      # thoát nếu sau N bar chưa đạt 0.5R
    no_progress_min_r: 0.3
"""


@dataclass
class StrategyConfig:
    """Config container cho Strategy Layer."""

    # Strategy info
    name: str = "sweep_choch_ob_v1"
    description: str = "Sweep → CHOCH → OB Retest"

    # Direction
    allow_long: bool = True
    allow_short: bool = True

    # Symbol / Timeframe
    symbol: str = "XAUUSD"
    timeframe: str = "15"

    # Layer 1 input paths
    events_path: str = ""
    snapshots_path: str = ""
    objects_path: str = ""

    # Session
    session_enabled: bool = False
    allowed_sessions: list = field(default_factory=lambda: ["london", "new_york", "asia"])

    # Setup rules
    require_sweep: bool = True
    require_choch: bool = True
    require_order_block: bool = True
    require_bos: bool = False
    max_bars_sweep_to_choch: int = 100
    max_bars_wait_entry: int = 100
    max_bars_arm: int = 10
    long_requires_sell_side_sweep: bool = True
    short_requires_buy_side_sweep: bool = True

    # Entry
    entry_type: str = "limit"
    entry_price_source: str = "ob_mid"
    limit_price_adjustment: float = 0.0
    require_candle_confirm: bool = False

    # SL
    sl_type: str = "sweep_extreme"
    sl_buffer_pips: float = 10.0
    sl_buffer_atr_ratio: float = 0.0
    sl_use_fixed_buffer: bool = True

    # TP
    tp_type: str = "fixed_r"
    tp_r_multiple: float = 2.0
    tp_use_opposing_liquidity: bool = False

    # Filters
    require_htf_alignment: bool = False
    require_premium_discount: bool = False
    max_spread_atr_ratio: float = 0.0
    require_sweep_displacement: bool = True
    min_rr_ratio: float = 1.5
    min_confidence: float = 0.3

    # Risk
    risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 1
    max_concurrent_setups: int = 3

    # Cooldown
    cooldown_bars_after_loss: int = 10
    cooldown_bars_after_win: int = 3
    max_orders_per_session: int = 5
    max_orders_per_day: int = 10

    # Exit
    use_early_exit: bool = True
    early_exit_on_reverse_choch: bool = True
    max_bars_no_progress: int = 20
    no_progress_min_r: float = 0.3

    # Internal state (not from config)
    atr_value: float = 0.0
    current_bar_index: int = 0
    current_timestamp: int = 0

    @classmethod
    def from_yaml(cls, path: str) -> "StrategyConfig":
        """Load config từ file YAML."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls._from_dict(data.get("strategy", {}))

    @classmethod
    def from_dict(cls, data: dict) -> "StrategyConfig":
        """Load config từ dict."""
        return cls._from_dict(data.get("strategy", data))

    @classmethod
    def _from_dict(cls, s: dict) -> "StrategyConfig":
        cfg = cls()

        cfg.name = s.get("name", cfg.name)
        cfg.description = s.get("description", cfg.description)

        # Direction
        d = s.get("direction", {})
        cfg.allow_long = d.get("allow_long", cfg.allow_long)
        cfg.allow_short = d.get("allow_short", cfg.allow_short)

        cfg.symbol = s.get("symbol", cfg.symbol)
        cfg.timeframe = s.get("timeframe", cfg.timeframe)

        # Layer 1 input
        l1 = s.get("layer1_input", {})
        cfg.events_path = l1.get("events_path", cfg.events_path)
        cfg.snapshots_path = l1.get("snapshots_path", cfg.snapshots_path)
        cfg.objects_path = l1.get("objects_path", cfg.objects_path)

        # Session
        sess = s.get("session", {})
        cfg.session_enabled = sess.get("enabled", cfg.session_enabled)
        cfg.allowed_sessions = sess.get("allowed_sessions", cfg.allowed_sessions)

        # Setup
        su = s.get("setup", {})
        cfg.require_sweep = su.get("require_sweep", cfg.require_sweep)
        cfg.require_choch = su.get("require_choch", cfg.require_choch)
        cfg.require_order_block = su.get("require_order_block", cfg.require_order_block)
        cfg.require_bos = su.get("require_bos", cfg.require_bos)
        cfg.max_bars_sweep_to_choch = su.get("max_bars_sweep_to_choch", cfg.max_bars_sweep_to_choch)
        cfg.max_bars_wait_entry = su.get("max_bars_wait_entry", cfg.max_bars_wait_entry)
        cfg.max_bars_arm = su.get("max_bars_arm", cfg.max_bars_arm)
        cfg.long_requires_sell_side_sweep = su.get("long_requires_sell_side_sweep", cfg.long_requires_sell_side_sweep)
        cfg.short_requires_buy_side_sweep = su.get("short_requires_buy_side_sweep", cfg.short_requires_buy_side_sweep)

        # Entry
        en = s.get("entry", {})
        cfg.entry_type = en.get("type", cfg.entry_type)
        cfg.entry_price_source = en.get("price_source", cfg.entry_price_source)
        cfg.limit_price_adjustment = en.get("limit_price_adjustment", cfg.limit_price_adjustment)
        cfg.require_candle_confirm = en.get("require_candle_confirm", cfg.require_candle_confirm)

        # SL
        sl = s.get("stop_loss", {})
        cfg.sl_type = sl.get("type", cfg.sl_type)
        cfg.sl_buffer_pips = sl.get("buffer_pips", cfg.sl_buffer_pips)
        cfg.sl_buffer_atr_ratio = sl.get("buffer_atr_ratio", cfg.sl_buffer_atr_ratio)
        cfg.sl_use_fixed_buffer = sl.get("use_fixed_buffer", cfg.sl_use_fixed_buffer)

        # TP
        tp = s.get("take_profit", {})
        cfg.tp_type = tp.get("type", cfg.tp_type)
        cfg.tp_r_multiple = tp.get("r_multiple", cfg.tp_r_multiple)
        cfg.tp_use_opposing_liquidity = tp.get("use_opposing_liquidity", cfg.tp_use_opposing_liquidity)

        # Filters
        fl = s.get("filters", {})
        cfg.require_htf_alignment = fl.get("require_htf_alignment", cfg.require_htf_alignment)
        cfg.require_premium_discount = fl.get("require_premium_discount", cfg.require_premium_discount)
        cfg.max_spread_atr_ratio = fl.get("max_spread_atr_ratio", cfg.max_spread_atr_ratio)
        cfg.require_sweep_displacement = fl.get("require_sweep_displacement", cfg.require_sweep_displacement)
        cfg.min_rr_ratio = fl.get("min_rr_ratio", cfg.min_rr_ratio)
        cfg.min_confidence = fl.get("min_confidence", cfg.min_confidence)

        # Risk
        rk = s.get("risk", {})
        cfg.risk_per_trade_pct = rk.get("risk_per_trade_pct", cfg.risk_per_trade_pct)
        cfg.max_daily_loss_pct = rk.get("max_daily_loss_pct", cfg.max_daily_loss_pct)
        cfg.max_open_positions = rk.get("max_open_positions", cfg.max_open_positions)
        cfg.max_concurrent_setups = rk.get("max_concurrent_setups", cfg.max_concurrent_setups)

        # Cooldown
        cd = s.get("cooldown", {})
        cfg.cooldown_bars_after_loss = cd.get("bars_after_loss", cfg.cooldown_bars_after_loss)
        cfg.cooldown_bars_after_win = cd.get("bars_after_win", cfg.cooldown_bars_after_win)
        cfg.max_orders_per_session = cd.get("max_orders_per_session", cfg.max_orders_per_session)
        cfg.max_orders_per_day = cd.get("max_orders_per_day", cfg.max_orders_per_day)

        # Exit
        ex = s.get("exit", {})
        cfg.use_early_exit = ex.get("use_early_exit", cfg.use_early_exit)
        cfg.early_exit_on_reverse_choch = ex.get("early_exit_on_reverse_choch", cfg.early_exit_on_reverse_choch)
        cfg.max_bars_no_progress = ex.get("max_bars_no_progress", cfg.max_bars_no_progress)
        cfg.no_progress_min_r = ex.get("no_progress_min_r", cfg.no_progress_min_r)

        return cfg

    def to_yaml(self) -> str:
        """Xuất config hiện tại thành YAML string."""
        data = {
            "strategy": {
                "name": self.name,
                "description": self.description,
                "direction": {
                    "allow_long": self.allow_long,
                    "allow_short": self.allow_short,
                },
                "symbol": self.symbol,
                "timeframe": self.timeframe,
                "setup": {
                    "require_sweep": self.require_sweep,
                    "require_choch": self.require_choch,
                    "require_order_block": self.require_order_block,
                    "require_bos": self.require_bos,
                    "max_bars_sweep_to_choch": self.max_bars_sweep_to_choch,
                    "max_bars_wait_entry": self.max_bars_wait_entry,
                    "long_requires_sell_side_sweep": self.long_requires_sell_side_sweep,
                    "short_requires_buy_side_sweep": self.short_requires_buy_side_sweep,
                },
                "entry": {
                    "type": self.entry_type,
                    "price_source": self.entry_price_source,
                    "limit_price_adjustment": self.limit_price_adjustment,
                    "require_candle_confirm": self.require_candle_confirm,
                },
                "stop_loss": {
                    "type": self.sl_type,
                    "buffer_pips": self.sl_buffer_pips,
                    "buffer_atr_ratio": self.sl_buffer_atr_ratio,
                },
                "take_profit": {
                    "type": self.tp_type,
                    "r_multiple": self.tp_r_multiple,
                    "use_opposing_liquidity": self.tp_use_opposing_liquidity,
                },
                "filters": {
                    "require_htf_alignment": self.require_htf_alignment,
                    "require_premium_discount": self.require_premium_discount,
                    "require_sweep_displacement": self.require_sweep_displacement,
                    "min_rr_ratio": self.min_rr_ratio,
                    "min_confidence": self.min_confidence,
                },
                "risk": {
                    "risk_per_trade_pct": self.risk_per_trade_pct,
                    "max_daily_loss_pct": self.max_daily_loss_pct,
                    "max_open_positions": self.max_open_positions,
                    "max_concurrent_setups": self.max_concurrent_setups,
                },
                "cooldown": {
                    "bars_after_loss": self.cooldown_bars_after_loss,
                    "bars_after_win": self.cooldown_bars_after_win,
                    "max_orders_per_session": self.max_orders_per_session,
                    "max_orders_per_day": self.max_orders_per_day,
                },
                "exit": {
                    "use_early_exit": self.use_early_exit,
                    "early_exit_on_reverse_choch": self.early_exit_on_reverse_choch,
                    "max_bars_no_progress": self.max_bars_no_progress,
                },
            }
        }
        return yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
