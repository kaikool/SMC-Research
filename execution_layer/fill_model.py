"""
Fill Model — Conservative OHLC fill rules.

Đây là lõi của Execution Engine. Quyết định lệnh có khớp không và giá nào.

Conservative OHLC (Mức 1):
  - Không biết thứ tự high/low trong nến → chọn kết quả bất lợi nhất.
  - Nếu entry, SL, TP cùng xảy ra trong một bar: ưu tiên kết quả xấu nhất.

Fill rules:
  Market order:
    signal bar close xong → khớp tại open bar kế tiếp + spread/slippage

  Buy limit:
    nếu low <= limit_price → khớp tại limit_price (hoặc worse)

  Sell limit:
    nếu high >= limit_price → khớp tại limit_price

  Buy stop:
    nếu high >= stop_price → kích hoạt, fill ngay

  Sell stop:
    nếu low <= stop_price → kích hoạt, fill ngay
"""

from typing import Optional, Literal
from .models import (
    Order, BarOHLC,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP,
    DIRECTION_LONG, DIRECTION_SHORT,
)


class FillModel:
    """Conservative OHLC fill model — V1."""

    def __init__(self, config, spread_model, slippage_model):
        self.config = config
        self.spread = spread_model
        self.slippage = slippage_model

    def check_fill(self, order: Order, bar: BarOHLC,
                   current_bar_index: int) -> tuple[bool, float, str]:
        """Kiểm tra order có khớp trong bar này không.

        Args:
            order: Order cần kiểm tra
            bar: Bar hiện tại (OHLC + bid/ask)
            current_bar_index: Bar index hiện tại

        Returns:
            (filled, fill_price, reason)
            reason: "filled", "not_triggered", "triggered_but_rejected"
        """
        if order.status not in ("accepted", "pending"):
            return False, 0.0, "invalid_status"

        if order.order_type == ORDER_TYPE_MARKET:
            return self._fill_market(order, bar, current_bar_index)

        elif order.order_type == ORDER_TYPE_LIMIT:
            return self._fill_limit(order, bar, current_bar_index)

        elif order.order_type == ORDER_TYPE_STOP:
            return self._fill_stop(order, bar, current_bar_index)

        return False, 0.0, "unknown_order_type"

    def _fill_market(self, order: Order, bar: BarOHLC,
                     current_bar_index: int) -> tuple[bool, float, str]:
        """Market order: khớp tại open của bar hiện tại (signal bar đã close bar trước).

        Nếu trade_on_close=True → khớp tại close của bar signal.
        Nếu trade_on_close=False → khớp tại open bar kế tiếp.

        Với bid/ask:
          Long: fill_price = open_ask + slippage
          Short: fill_price = open_bid - slippage
        """
        cfg = self.config

        if cfg.trade_on_close:
            # Khớp tại close của bar hiện tại
            if order.direction == DIRECTION_LONG:
                base_price = bar.close_ask
            else:
                base_price = bar.close_bid
        else:
            # Khớp tại open của bar hiện tại (bar kế tiếp sau signal)
            if order.direction == DIRECTION_LONG:
                base_price = bar.open_ask
            else:
                base_price = bar.open_bid

        # Slippage
        slippage = self.slippage.get_slippage_price(
            order.symbol, is_stop_order=(order.order_type == ORDER_TYPE_STOP)
        )
        fill_price = self.slippage.apply_slippage(base_price, order.direction, slippage)

        return True, fill_price, "filled"

    def _fill_limit(self, order: Order, bar: BarOHLC,
                    current_bar_index: int) -> tuple[bool, float, str]:
        """Limit order: kiểm tra giá chạm.

        Buy limit: low <= limit_price → khớp
          Conservative: fill tại limit_price (giá xấu nhất cho buy limit là limit price)
          Nhưng nếu limit_price > open_ask, có thể khớp ngay tại open

        Sell limit: high >= limit_price → khớp
        """
        limit = order.requested_price
        symbol = order.symbol

        if order.direction == DIRECTION_LONG:
            # Buy limit: low phải chạm limit price
            if bar.low_bid <= limit:
                # Conservative: giả sử khớp ở limit price
                fill_price = limit
                # Nhưng nếu limit cao hơn open → khớp tốt hơn ngay từ đầu bar
                if limit >= bar.open_ask:
                    fill_price = bar.open_ask
                return True, fill_price, "filled"
            # Kiểm tra nếu open đã tốt hơn limit
            if bar.open_ask <= limit:
                fill_price = min(limit, bar.open_ask)
                return True, fill_price, "filled_at_open"
        else:
            # Sell limit: high phải chạm limit price
            if bar.high_ask >= limit:
                fill_price = limit
                if limit <= bar.open_bid:
                    fill_price = bar.open_bid
                return True, fill_price, "filled"
            if bar.open_bid >= limit:
                fill_price = max(limit, bar.open_bid)
                return True, fill_price, "filled_at_open"

        return False, 0.0, "not_triggered"

    def _fill_stop(self, order: Order, bar: BarOHLC,
                   current_bar_index: int) -> tuple[bool, float, str]:
        """Stop order: giá chạm stop → kích hoạt → fill.

        Buy stop: high >= stop_price → kích hoạt
          Fill: stop_price + spread/2 + slippage (mua ở ask)

        Sell stop: low <= stop_price → kích hoạt
          Fill: stop_price - spread/2 - slippage (bán ở bid)
        """
        stop = order.requested_price
        symbol = order.symbol

        if order.direction == DIRECTION_LONG:
            # Buy stop: giá phá lên trên stop
            if bar.high_ask >= stop:
                # Kích hoạt — fill giá stop + slippage
                slippage = self.slippage.get_slippage_price(symbol, is_stop_order=True)
                # Fill: thường khớp ở ask gần stop price + slippage
                fill_price = max(bar.open_ask, stop) + slippage
                return True, fill_price, "filled_stop"
        else:
            # Sell stop: giá phá xuống dưới stop
            if bar.low_bid <= stop:
                slippage = self.slippage.get_slippage_price(symbol, is_stop_order=True)
                fill_price = min(bar.open_bid, stop) - slippage
                return True, fill_price, "filled_stop"

        return False, 0.0, "not_triggered"

    def resolve_collision(self, order: Order, bar: BarOHLC) -> tuple[str, float]:
        """Giải quyết xung đột nếu cùng bar chạm cả entry, SL, TP.

        Conservative rule:
          Long: nếu cùng bar chạm TP và SL → SL trước
          Short: nếu cùng bar chạm TP và SL → SL trước

        Returns:
            (event, price): "entry", "sl", "tp" + giá
        """
        direction = order.direction
        sl = order.stop_loss
        tp = order.take_profit

        hit_entry = False
        hit_sl = False
        hit_tp = False
        entry_price = 0.0

        # Kiểm tra entry
        filled, fill_price, _ = self.check_fill(order, bar, bar.bar_index)
        if filled:
            hit_entry = True
            entry_price = fill_price

        # Kiểm tra SL
        if direction == DIRECTION_LONG:
            if sl > 0 and bar.low_bid <= sl:
                hit_sl = True
            if tp > 0 and bar.high_bid >= tp:
                hit_tp = True
        else:
            if sl > 0 and bar.high_ask >= sl:
                hit_sl = True
            if tp > 0 and bar.low_ask <= tp:
                hit_tp = True

        # Xung đột: ưu tiên bất lợi
        if hit_sl and hit_tp:
            # Conservative: SL trước (bất lợi)
            return "sl", (sl if direction == DIRECTION_LONG else sl)

        if hit_entry and hit_sl:
            # Có thể vào lệnh rồi bị SL cùng bar
            # Conservative: giả sử entry xảy ra trước rồi SL
            return "entry_then_sl", entry_price

        if hit_entry and hit_tp:
            return "entry_then_tp", entry_price

        if hit_entry:
            return "entry", entry_price

        if hit_sl:
            return "sl", sl

        if hit_tp:
            return "tp", tp

        return "none", 0.0
