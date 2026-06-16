"""
Slippage Model — Fixed hoặc ATR-based.

V1: fixed points. Có thể mở rộng sau.
"""

from typing import Optional


class SlippageModel:
    """Tính slippage cho mỗi lệnh."""

    def __init__(self, config):
        self.config = config

    def get_slippage_price(self, symbol: str, is_stop_order: bool = False,
                           current_atr: float = 0.0) -> float:
        """Tính slippage bằng price (không phải points).

        Returns:
            Slippage giá trị price (sẽ được +/ - từ fill price tuỳ hướng)
        """
        cfg = self.config.slippage
        point_size = self._get_point_size(symbol)

        if cfg.mode == "fixed":
            points = cfg.points.get(symbol, 2)
            if is_stop_order:
                points *= 2  # stop order thường bị trượt giá hơn
            return points * point_size

        elif cfg.mode == "atr_ratio" and current_atr > 0:
            return max(
                cfg.points.get(symbol, 2) * point_size,
                current_atr * cfg.atr_ratio
            )

        return cfg.points.get(symbol, 2) * point_size

    def apply_slippage(self, fill_price: float, direction: int,
                       slippage_price: float) -> float:
        """Apply slippage: long mắc hơn (+), short rẻ hơn (-)."""
        if direction > 0:  # long
            return fill_price + slippage_price
        else:  # short
            return fill_price - slippage_price

    def _get_point_size(self, symbol: str) -> float:
        """Lấy point_size mặc định dựa trên symbol."""
        # Default point sizes
        sizes = {
            "XAUUSD": 0.01,
            "GBPUSD": 0.00001,
            "EURUSD": 0.00001,
        }
        return sizes.get(symbol, 0.00001)
