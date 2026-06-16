"""
Order Manager — Quản lý vòng đời lệnh.

Lifecycle:
  created → accepted → pending → filled
  created → rejected
  pending → cancelled
  pending → expired
"""

from typing import Optional
from .models import (
    Order,
    ORDER_CREATED, ORDER_ACCEPTED, ORDER_REJECTED,
    ORDER_PENDING, ORDER_FILLED, ORDER_CANCELLED, ORDER_EXPIRED,
)


class OrderManager:
    """Quản lý tất cả orders."""

    def __init__(self):
        self.orders: list[Order] = []
        self._next_id = 1

    def create_order(self, setup_id: str, symbol: str, direction: int,
                     order_type: str, action: str,
                     requested_price: float, stop_loss: float,
                     take_profit: float, risk_pct: float,
                     timestamp: int, bar_index: int,
                     valid_until: int = 0, valid_until_bar: int = 0) -> Order:
        """Tạo order mới với status = created."""
        order = Order(
            order_id=f"ORD_{self._next_id:04d}",
            setup_id=setup_id,
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            action=action,
            status=ORDER_CREATED,
            requested_price=requested_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_pct=risk_pct,
            created_at=timestamp,
            bar_index=bar_index,
            valid_until=valid_until,
            valid_until_bar=valid_until_bar,
        )
        self._next_id += 1
        self.orders.append(order)
        return order

    def accept_order(self, order: Order) -> None:
        """Chấp nhận order → chuyển sang pending (sẵn sàng chờ khớp)."""
        order.status = ORDER_PENDING

    def reject_order(self, order: Order, reason: str) -> None:
        """Từ chối order."""
        order.status = ORDER_REJECTED
        order.reject_reason = reason

    def fill_order(self, order: Order, fill_price: float,
                   filled_at: int, filled_bar: int) -> None:
        """Đánh dấu order đã khớp."""
        order.status = ORDER_FILLED
        order.filled_price = fill_price
        order.filled_at = filled_at
        order.filled_bar = filled_bar

    def cancel_order(self, order: Order, reason: str = "") -> None:
        """Hủy order."""
        order.status = ORDER_CANCELLED
        order.cancel_reason = reason

    def expire_order(self, order: Order, reason: str = "") -> None:
        """Hết hạn order."""
        order.status = ORDER_EXPIRED
        order.expired_reason = reason or "expired_by_time"

    def get_active_orders(self) -> list[Order]:
        """Lấy orders đang pending/accepted (chưa filled, cancelled, expired)."""
        return [o for o in self.orders
                if o.status in (ORDER_ACCEPTED, ORDER_PENDING)]

    def get_orders_by_setup(self, setup_id: str) -> list[Order]:
        """Lấy orders của một setup."""
        return [o for o in self.orders if o.setup_id == setup_id]

    def get_active_orders_for_symbol(self, symbol: str) -> list[Order]:
        """Lấy active orders cho một symbol."""
        return [o for o in self.orders
                if o.symbol == symbol
                and o.status in (ORDER_ACCEPTED, ORDER_PENDING)]

    def count_by_status(self) -> dict:
        """Đếm orders theo status."""
        counts = {}
        for o in self.orders:
            counts[o.status] = counts.get(o.status, 0) + 1
        return counts

    def get_next_order_id(self) -> str:
        oid = self._next_id
        self._next_id += 1
        return f"ORD_{oid:04d}"
