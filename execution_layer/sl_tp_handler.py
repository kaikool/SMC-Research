"""
SL/TP Handler — Kiểm tra stop loss và take profit mỗi bar.

Nguyên tắc:
  Long exit dùng Bid.
  Short exit dùng Ask.

  Conservative: nếu cùng bar chạm cả SL và TP → SL trước.
"""

from typing import Optional, Literal
from .models import (
    Position, BarOHLC,
    DIRECTION_LONG, DIRECTION_SHORT,
    EXIT_SL, EXIT_TP,
)


class SLTPHandler:
    """Kiểm tra SL/TP mỗi bar."""

    def __init__(self, config):
        self.config = config

    def check(self, position: Position, bar: BarOHLC) -> tuple[bool, str, float]:
        """Kiểm tra SL/TP cho một position trong bar hiện tại.

        Returns:
            (hit, reason, exit_price)
            - hit: True nếu có SL hoặc TP bị chạm
            - reason: "stop_loss" hoặc "take_profit"
            - exit_price: giá thoát
        """
        if position.status != "open":
            return False, "", 0.0

        direction = position.direction
        sl = position.stop_loss
        tp = position.take_profit

        hit_sl = False
        hit_tp = False
        exit_price = 0.0

        if direction == DIRECTION_LONG:
            # Long: SL ở bid, TP ở bid
            if sl > 0 and bar.low_bid <= sl:
                hit_sl = True
                exit_price = sl
            if tp > 0 and bar.high_bid >= tp:
                hit_tp = True
                exit_price = tp

            # Collision: cùng bar chạm cả SL và TP → SL trước (conservative)
            if hit_sl and hit_tp:
                return True, EXIT_SL, sl

            if hit_sl:
                return True, EXIT_SL, sl
            if hit_tp:
                return True, EXIT_TP, tp

        else:
            # Short: SL ở ask, TP ở ask
            if sl > 0 and bar.high_ask >= sl:
                hit_sl = True
                exit_price = sl
            if tp > 0 and bar.low_ask <= tp:
                hit_tp = True
                exit_price = tp

            if hit_sl and hit_tp:
                return True, EXIT_SL, sl
            if hit_sl:
                return True, EXIT_SL, sl
            if hit_tp:
                return True, EXIT_TP, tp

        return False, "", 0.0

    def check_all(self, positions: list[Position], bar: BarOHLC,
                  timestamp: int, bar_index: int) -> list[dict]:
        """Kiểm tra SL/TP cho tất cả positions đang mở.

        Returns:
            list[dict]: danh sách các sự kiện SL/TP hit
            Mỗi event: {position, reason, exit_price, timestamp, bar_index}
        """
        events = []
        for pos in positions:
            if pos.status != "open":
                continue
            hit, reason, exit_price = self.check(pos, bar)
            if hit:
                events.append({
                    "position": pos,
                    "reason": reason,
                    "exit_price": exit_price,
                    "timestamp": timestamp,
                    "bar_index": bar_index,
                })
        return events
