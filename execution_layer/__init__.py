"""
Execution Layer — backtest engine, position management, PnL.

Vai trò:
  - Nhận order_intent từ Strategy Layer
  - Quản lý vị thế (mở/đóng/sửa)
  - Tính toán PnL, equity curve, drawdown
  - Mô phỏng spread, slippage, commission
  - Xuất orders.csv, trades.csv, equity_curve.csv
"""

from .models import (
    Order, Position, AccountState, LedgerEntry, BarOHLC,
    DIRECTION_LONG, DIRECTION_SHORT, DIRECTION_NONE,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP,
    ORDER_CREATED, ORDER_ACCEPTED, ORDER_REJECTED,
    ORDER_PENDING, ORDER_FILLED, ORDER_CANCELLED, ORDER_EXPIRED,
    POSITION_OPEN, POSITION_CLOSED,
    EXIT_SL, EXIT_TP,
)
from .execution_config import ExecutionConfig, DEFAULT_EXECUTION_YAML
from .execution_engine import ExecutionEngine
