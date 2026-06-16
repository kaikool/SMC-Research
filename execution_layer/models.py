"""
Execution Layer — Data models cho backtest engine.

Định nghĩa tất cả struct cho Execution Engine V1:
  Order, Position, AccountState, LedgerEntry.
"""

from dataclasses import dataclass, field
from typing import Optional


# ── Order Status ──────────────────────────────────────────────────

ORDER_CREATED = "created"
ORDER_ACCEPTED = "accepted"
ORDER_REJECTED = "rejected"
ORDER_PENDING = "pending"
ORDER_PARTIALLY_FILLED = "partially_filled"
ORDER_FILLED = "filled"
ORDER_CANCELLED = "cancelled"
ORDER_EXPIRED = "expired"

VALID_ORDER_STATUSES = {
    ORDER_CREATED, ORDER_ACCEPTED, ORDER_REJECTED, ORDER_PENDING,
    ORDER_PARTIALLY_FILLED, ORDER_FILLED, ORDER_CANCELLED, ORDER_EXPIRED,
}

# ── Order Action ──────────────────────────────────────────────────

ACTION_PLACE_ORDER = "PLACE_ORDER"
ACTION_CANCEL_ORDER = "CANCEL_ORDER"
ACTION_MODIFY_ORDER = "MODIFY_ORDER"
ACTION_CLOSE_POSITION = "CLOSE_POSITION"

# ── Order Types ───────────────────────────────────────────────────

ORDER_TYPE_MARKET = "market"
ORDER_TYPE_LIMIT = "limit"
ORDER_TYPE_STOP = "stop"
ORDER_TYPE_STOP_LIMIT = "stop_limit"

# ── Direction ─────────────────────────────────────────────────────

DIRECTION_LONG = 1
DIRECTION_SHORT = -1
DIRECTION_NONE = 0

# ── Position Status ───────────────────────────────────────────────

POSITION_OPEN = "open"
POSITION_CLOSED = "closed"

# ── Exit Reasons ──────────────────────────────────────────────────

EXIT_TP = "take_profit"
EXIT_SL = "stop_loss"
EXIT_MANUAL = "manual_close"
EXIT_CANCEL = "cancelled"
EXIT_EXPIRED = "expired"
EXIT_REVERSE = "reverse_signal"
EXIT_DAILY_LOSS = "daily_loss_limit"
EXIT_KILL_SWITCH = "kill_switch"
EXIT_MARGIN_CALL = "margin_call"

# ── Execution Decisions ───────────────────────────────────────────

DECISION_ORDER_ACCEPTED = "ORDER_ACCEPTED"
DECISION_ORDER_REJECTED = "ORDER_REJECTED"
DECISION_ORDER_FILLED = "ORDER_FILLED"
DECISION_ORDER_CANCELLED = "ORDER_CANCELLED"
DECISION_ORDER_EXPIRED = "ORDER_EXPIRED"
DECISION_POSITION_OPENED = "POSITION_OPENED"
DECISION_POSITION_CLOSED = "POSITION_CLOSED"
DECISION_SL_HIT = "SL_HIT"
DECISION_TP_HIT = "TP_HIT"
DECISION_MARGIN_REJECT = "MARGIN_REJECT"


# ── Data Classes ──────────────────────────────────────────────────

@dataclass
class Order:
    """Một order — có lifecycle đầy đủ."""

    order_id: str = ""
    setup_id: str = ""
    symbol: str = ""
    direction: int = DIRECTION_NONE
    order_type: str = ORDER_TYPE_MARKET
    action: str = ACTION_PLACE_ORDER
    status: str = ORDER_CREATED

    requested_price: float = 0.0
    filled_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    size_lot: float = 0.0
    risk_pct: float = 0.0

    created_at: int = 0          # ms epoch
    bar_index: int = 0
    filled_at: int = 0
    filled_bar: int = 0
    valid_until: int = 0         # ms epoch
    valid_until_bar: int = 0

    reject_reason: str = ""
    cancel_reason: str = ""
    expired_reason: str = ""

    def to_csv_row(self) -> dict:
        return {
            "order_id": self.order_id,
            "setup_id": self.setup_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "order_type": self.order_type,
            "status": self.status,
            "requested_price": round(self.requested_price, 5) if self.requested_price else "",
            "filled_price": round(self.filled_price, 5) if self.filled_price else "",
            "stop_loss": round(self.stop_loss, 5) if self.stop_loss else "",
            "take_profit": round(self.take_profit, 5) if self.take_profit else "",
            "size_lot": round(self.size_lot, 2) if self.size_lot else "",
            "created_at": self.created_at,
            "filled_at": self.filled_at,
            "bar_index": self.bar_index,
            "filled_bar": self.filled_bar,
            "reject_reason": self.reject_reason,
            "cancel_reason": self.cancel_reason,
            "expired_reason": self.expired_reason,
        }


@dataclass
class Position:
    """Một vị thế — kết quả của một order đã khớp."""

    position_id: str = ""
    order_id: str = ""
    setup_id: str = ""
    symbol: str = ""
    direction: int = DIRECTION_NONE
    size_lot: float = 0.0

    entry_time: int = 0
    entry_bar: int = 0
    entry_price: float = 0.0       # giá khớp thực tế

    stop_loss: float = 0.0
    take_profit: float = 0.0

    status: str = POSITION_OPEN
    exit_time: int = 0
    exit_bar: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""

    # PnL breakdown
    gross_pnl: float = 0.0
    commission: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    net_pnl: float = 0.0
    r_multiple: float = 0.0
    holding_bars: int = 0

    # MAE/MFE tracking
    max_adverse: float = 0.0       # MAE in price
    max_favorable: float = 0.0     # MFE in price

    def to_csv_row(self) -> dict:
        return {
            "position_id": self.position_id,
            "order_id": self.order_id,
            "setup_id": self.setup_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "size_lot": round(self.size_lot, 2),
            "entry_time": self.entry_time,
            "entry_bar": self.entry_bar,
            "entry_price": round(self.entry_price, 5),
            "stop_loss": round(self.stop_loss, 5) if self.stop_loss else "",
            "take_profit": round(self.take_profit, 5) if self.take_profit else "",
            "status": self.status,
            "exit_time": self.exit_time,
            "exit_bar": self.exit_bar,
            "exit_price": round(self.exit_price, 5) if self.exit_price else "",
            "exit_reason": self.exit_reason,
            "gross_pnl": round(self.gross_pnl, 2),
            "commission": round(self.commission, 2),
            "spread_cost": round(self.spread_cost, 2),
            "slippage_cost": round(self.slippage_cost, 2),
            "net_pnl": round(self.net_pnl, 2),
            "r_multiple": round(self.r_multiple, 2),
            "holding_bars": self.holding_bars,
            "max_adverse": round(self.max_adverse, 5) if self.max_adverse else "",
            "max_favorable": round(self.max_favorable, 5) if self.max_favorable else "",
        }


@dataclass
class AccountState:
    """Trạng thái tài khoản tại một thời điểm."""

    balance: float = 0.0
    equity: float = 0.0
    used_margin: float = 0.0
    free_margin: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    commission_paid: float = 0.0
    margin_level: float = 0.0      # equity / used_margin

    def to_ledger_row(self, timestamp: int) -> dict:
        return {
            "timestamp": timestamp,
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "used_margin": round(self.used_margin, 2),
            "free_margin": round(self.free_margin, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "commission_paid": round(self.commission_paid, 2),
            "margin_level": round(self.margin_level, 4) if self.margin_level else 0,
        }

    def to_equity_row(self, timestamp: int, open_positions: int,
                      drawdown: float) -> dict:
        return {
            "timestamp": timestamp,
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "drawdown": round(drawdown, 2),
            "open_positions": open_positions,
        }


@dataclass
class LedgerEntry:
    """Một dòng trong sổ tài khoản."""

    timestamp: int = 0
    event_type: str = ""           # OPEN, CLOSE, COMMISSION, DEPOSIT, WITHDRAW, SWAP
    amount: float = 0.0
    balance_before: float = 0.0
    balance_after: float = 0.0
    position_id: str = ""
    order_id: str = ""
    reason: str = ""

    def to_csv_row(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "amount": round(self.amount, 2),
            "balance_before": round(self.balance_before, 2),
            "balance_after": round(self.balance_after, 2),
            "position_id": self.position_id,
            "order_id": self.order_id,
            "reason": self.reason,
        }


@dataclass
class ExecutionDecision:
    """Một quyết định của Execution Engine — dùng cho audit log."""

    timestamp: int = 0
    bar_index: int = 0
    order_id: str = ""
    decision: str = ""
    reason: str = ""
    details: str = ""

    def to_csv_row(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "bar_index": self.bar_index,
            "order_id": self.order_id,
            "decision": self.decision,
            "reason": self.reason,
            "details": self.details,
        }


# ── Bar OHLCV với bid/ask ──────────────────────────────────────────

@dataclass
class BarOHLC:
    """Một nến OHLCV + bid/ask + spread."""

    symbol: str = ""
    timestamp: int = 0
    bar_index: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0

    # Bid/Ask
    open_bid: float = 0.0
    high_bid: float = 0.0
    low_bid: float = 0.0
    close_bid: float = 0.0
    open_ask: float = 0.0
    high_ask: float = 0.0
    low_ask: float = 0.0
    close_ask: float = 0.0

    spread_points: float = 0.0
    spread_price: float = 0.0


# ── CSV field lists ───────────────────────────────────────────────

ORDERS_CSV_FIELDS = [
    "order_id", "setup_id", "symbol", "direction", "order_type",
    "status", "requested_price", "filled_price",
    "stop_loss", "take_profit", "size_lot",
    "created_at", "filled_at", "bar_index", "filled_bar",
    "reject_reason", "cancel_reason", "expired_reason",
]

TRADES_CSV_FIELDS = [
    "position_id", "order_id", "setup_id", "symbol", "direction",
    "size_lot",
    "entry_time", "entry_bar", "entry_price",
    "stop_loss", "take_profit",
    "status", "exit_time", "exit_bar", "exit_price", "exit_reason",
    "gross_pnl", "commission", "spread_cost", "slippage_cost",
    "net_pnl", "r_multiple", "holding_bars",
    "max_adverse", "max_favorable",
]

ACCOUNT_LEDGER_CSV_FIELDS = [
    "timestamp", "balance", "equity",
    "used_margin", "free_margin",
    "realized_pnl", "unrealized_pnl",
    "commission_paid", "margin_level",
]

EQUITY_CURVE_CSV_FIELDS = [
    "timestamp", "balance", "equity", "drawdown", "open_positions",
]

LEDGER_LOG_CSV_FIELDS = [
    "timestamp", "event_type", "amount",
    "balance_before", "balance_after",
    "position_id", "order_id", "reason",
]

EXECUTION_DECISIONS_CSV_FIELDS = [
    "timestamp", "bar_index", "order_id",
    "decision", "reason", "details",
]
