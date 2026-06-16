"""
Pending Order Handler — Xử lý hết hạn và hủy lệnh chờ.

Mỗi bar kiểm tra:
  - Order quá hạn → expired
  - Setup bị cancel → cancel order
"""

from typing import Optional
from .models import (
    Order,
    ORDER_PENDING, ORDER_ACCEPTED,
)


class PendingOrderHandler:
    """Xử lý pending orders."""

    def __init__(self, config):
        self.config = config

    def check_expiry(self, order: Order, current_bar_index: int,
                     current_timestamp: int) -> bool:
        """Kiểm tra order có hết hạn không.

        Returns:
            True nếu order hết hạn
        """
        if order.status not in (ORDER_PENDING, ORDER_ACCEPTED):
            return False

        # Kiểm tra valid_until_bar
        if order.valid_until_bar > 0 and current_bar_index > order.valid_until_bar:
            return True

        # Kiểm tra valid_until timestamp
        if order.valid_until > 0 and current_timestamp > order.valid_until:
            return True

        return False

    def check_expiry_all(self, orders: list[Order], current_bar_index: int,
                         current_timestamp: int) -> list[Order]:
        """Kiểm tra expiry cho tất cả pending orders.

        Returns:
            list[Order]: các orders đã hết hạn
        """
        expired = []
        for o in orders:
            if o.status not in (ORDER_PENDING, ORDER_ACCEPTED):
                continue
            if self.check_expiry(o, current_bar_index, current_timestamp):
                expired.append(o)
        return expired

    def should_cancel_on_event(self, order: Order, events: list[dict]) -> bool:
        """Kiểm tra có nên cancel order vì event ngược chiều không.

        V1: nếu có BOS ngược chiều thì cancel pending order.
        """
        for ev in events:
            etype = ev.get("event_type", "")
            if order.direction > 0:  # Long
                if "BOS_BEARISH" in etype or "CHOCH_BEARISH" in etype:
                    return True
            else:  # Short
                if "BOS_BULLISH" in etype or "CHOCH_BULLISH" in etype:
                    return True
        return False
