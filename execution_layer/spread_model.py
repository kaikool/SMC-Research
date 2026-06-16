"""
Spread Model — Bid/Ask từ spread data hoặc fixed spread.

Nguyên tắc:
  Long entry mua tại Ask, Long exit bán tại Bid.
  Short entry bán tại Bid, Short exit mua tại Ask.

  ask = mid + spread / 2
  bid = mid - spread / 2
"""

from typing import Optional
from .models import BarOHLC


class SpreadModel:
    """Tính bid/ask từ mid OHLC."""

    def __init__(self, config, symbol_specs: dict):
        self.config = config
        self.specs = symbol_specs

    def _get_specs(self, symbol: str = "") -> dict:
        """Lấy per-symbol specs."""
        if isinstance(self.specs, dict) and symbol and symbol in self.specs:
            return self.specs[symbol]
        return self.specs if isinstance(self.specs, dict) else {}

    def compute_bid_ask(self, bar_index: int, o: float, h: float, l: float, c: float,
                        spread_points: Optional[float] = None,
                        symbol: str = "") -> tuple[float, float, float, float,
                                                    float, float, float, float]:
        """Tính bid/ask cho 4 giá của nến.

        Returns:
            (open_bid, high_bid, low_bid, close_bid,
             open_ask, high_ask, low_ask, close_ask)
        """
        point_size = self._get_specs(symbol).get("point_size", 0.00001)

        # Xác định spread (price)
        if spread_points is not None and spread_points > 0:
            sp_price = spread_points * point_size
        else:
            sp_price = self._fallback_spread_price()

        half = sp_price / 2.0

        return (
            o - half, h - half, l - half, c - half,   # bid
            o + half, h + half, l + half, c + half,   # ask
        )

    def compute_bid_ask_for_bar(self, bar: BarOHLC) -> BarOHLC:
        """Điền bid/ask cho một BarOHLC."""
        (bar.open_bid, bar.high_bid, bar.low_bid, bar.close_bid,
         bar.open_ask, bar.high_ask, bar.low_ask, bar.close_ask) = \
            self.compute_bid_ask(
                bar.bar_index, bar.open, bar.high, bar.low, bar.close,
                bar.spread_points, symbol=bar.symbol
            )
        return bar

    def _fallback_spread_price(self) -> float:
        """Spread price từ config fallback."""
        mode = self.config.spread.mode
        if mode == "fixed":
            points = self.config.spread.fallback_points
        else:
            points = self.config.spread.fallback_points

        # Use first symbol's spread as default
        for sym, pts in points.items():
            point_size = self.specs.get("point_size", 0.00001)
            return pts * point_size

        return 0.0002  # ultra fallback

    def get_spread_price(self, symbol: str, spread_points: Optional[float] = None,
                         bar: Optional[BarOHLC] = None) -> float:
        """Lấy spread price cho symbol."""
        point_size = self._get_specs(symbol).get("point_size", 0.00001)

        if spread_points is not None and spread_points > 0:
            return spread_points * point_size

        if bar and bar.spread_points > 0:
            return bar.spread_points * point_size

        # Fallback
        mode = self.config.spread.mode
        if mode == "fixed":
            points = self.config.spread.fallback_points.get(symbol, 10)
        else:
            points = self.config.spread.fallback_points.get(symbol, 10)

        return points * point_size
