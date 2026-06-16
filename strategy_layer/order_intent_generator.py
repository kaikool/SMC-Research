"""
Order Intent Generator — Sinh order intent từ setup đã sẵn sàng.

Chuyển đổi Setup thành OrderIntent sẵn sàng gửi Execution Layer.
"""

from typing import Optional
from .models import (
    Setup, OrderIntent, StrategyDecision,
    SETUP_STATUS_ARMED, SETUP_STATUS_TRIGGERED, SETUP_STATUS_ENTERED,
    DIRECTION_LONG, DIRECTION_SHORT,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT,
)
from .config import StrategyConfig


class OrderIntentGenerator:
    """Sinh OrderIntent từ Setup."""

    def __init__(self, config: StrategyConfig):
        self.config = config

    def generate(self, setup: Setup, bar_index: int, timestamp: int,
                 entry_price: float, entry_type: str) -> Optional[OrderIntent]:
        """Tạo OrderIntent từ setup đã triggered.

        Returns:
            OrderIntent object hoặc None nếu không hợp lệ.
        """
        if not setup.sl_price or setup.sl_price <= 0:
            return None

        risk_pct = self.config.risk_per_trade_pct / 100.0

        order_type = ORDER_TYPE_MARKET if entry_type == "market" else ORDER_TYPE_LIMIT
        valid_until = timestamp + self.config.max_bars_wait_entry * (
            self.config.max_bars_wait_entry * 60 * 15 * 1000
        )

        intent = OrderIntent(
            timestamp=timestamp,
            bar_index=bar_index,
            setup_id=setup.setup_id,
            action="PLACE_ORDER",
            symbol=self.config.symbol,
            timeframe=self.config.timeframe,
            direction=setup.direction,
            order_type=order_type,
            entry_price=entry_price,
            sl_price=setup.sl_price,
            tp_price=setup.tp_price,
            risk_pct=risk_pct,
            valid_until=valid_until,
            status="pending",
        )

        return intent

    def generate_cancel(self, setup: Setup, bar_index: int,
                        timestamp: int) -> OrderIntent:
        """Tạo cancel intent cho setup đã hết hạn/bị huỷ."""
        return OrderIntent(
            timestamp=timestamp,
            bar_index=bar_index,
            setup_id=setup.setup_id,
            action="CANCEL_ORDER",
            status="cancelled",
        )
