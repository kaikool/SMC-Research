"""
Position Manager — Quản lý vị thế đang mở.

V1 rules:
  - Không hedge
  - Một symbol chỉ một position
  - Có position rồi không mở lệnh mới cùng symbol
"""

from typing import Optional
from .models import (
    Position, Order, BarOHLC,
    DIRECTION_LONG, DIRECTION_SHORT,
    POSITION_OPEN, POSITION_CLOSED,
    EXIT_SL, EXIT_TP, EXIT_MANUAL, EXIT_MARGIN_CALL, EXIT_DAILY_LOSS,
)


class PositionManager:
    """Quản lý positions."""

    def __init__(self, config):
        self.config = config
        self.positions: list[Position] = []
        self._next_id = 1

    def open_position(self, order: Order, fill_price: float,
                      timestamp: int, bar_index: int,
                      lots: float, commission: float,
                      spread_cost: float) -> Optional[Position]:
        """Mở vị thế mới từ order đã khớp.

        Returns:
            Position hoặc None nếu không mở được (do rules).
        """
        cfg = self.config.position

        # Kiểm tra hedging
        if not cfg.allow_hedging:
            existing = self.get_open_position(order.symbol)
            if existing:
                # Nếu ngược chiều → đóng position cũ (nếu không hedge)
                if existing.direction != order.direction:
                    # V1: không tự động reverse — báo lỗi
                    return None
                # Cùng chiều → không scale in (V1)
                return None

        # Kiểm tra max positions
        open_count = len(self.get_all_open_positions())
        if open_count >= cfg.max_total_positions:
            return None

        pos = Position(
            position_id=f"POS_{self._next_id:04d}",
            order_id=order.order_id,
            setup_id=order.setup_id,
            symbol=order.symbol,
            direction=order.direction,
            size_lot=lots,
            entry_time=timestamp,
            entry_bar=bar_index,
            entry_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            status=POSITION_OPEN,
            commission=commission,
            spread_cost=spread_cost,
        )
        self._next_id += 1
        self.positions.append(pos)
        return pos

    def close_position(self, position: Position, exit_price: float,
                       timestamp: int, bar_index: int,
                       exit_reason: str, commission: float = 0.0,
                       additional_spread: float = 0.0,
                       slippage_cost: float = 0.0) -> dict:
        """Đóng vị thế và tính PnL.

        Returns:
            dict với thông tin PnL
        """
        if position.status != POSITION_OPEN:
            return {}

        direction = position.direction
        lots = position.size_lot
        entry = position.entry_price
        exit_p = exit_price

        # Gross PnL
        point_size = self._get_point_size(position.symbol)
        if direction == DIRECTION_LONG:
            gross_pnl = (exit_p - entry) * lots * self._get_contract_size(position.symbol)
        else:
            gross_pnl = (entry - exit_p) * lots * self._get_contract_size(position.symbol)

        # Total commission (entry đã tính, thêm exit)
        total_commission = position.commission + commission
        total_spread = position.spread_cost + additional_spread
        total_slippage = slippage_cost

        net_pnl = gross_pnl - total_commission - total_spread - total_slippage

        # R multiple
        risk_per_lot = abs(entry - position.stop_loss) * self._get_contract_size(position.symbol)
        r_multiple = gross_pnl / risk_per_lot if risk_per_lot > 0 else 0.0

        # Holding bars
        holding_bars = bar_index - position.entry_bar

        # Update position
        position.status = POSITION_CLOSED
        position.exit_time = timestamp
        position.exit_bar = bar_index
        position.exit_price = exit_p
        position.exit_reason = exit_reason
        position.gross_pnl = gross_pnl
        position.commission = total_commission
        position.spread_cost = total_spread
        position.slippage_cost = total_slippage
        position.net_pnl = net_pnl
        position.r_multiple = r_multiple
        position.holding_bars = holding_bars

        return {
            "gross_pnl": gross_pnl,
            "commission": total_commission,
            "spread_cost": total_spread,
            "slippage_cost": total_slippage,
            "net_pnl": net_pnl,
            "r_multiple": r_multiple,
            "holding_bars": holding_bars,
            "exit_price": exit_p,
        }

    def update_sl(self, position: Position, new_sl: float) -> None:
        """Di chuyển stop loss."""
        if position.status == POSITION_OPEN:
            position.stop_loss = new_sl

    def update_tp(self, position: Position, new_tp: float) -> None:
        """Di chuyển take profit."""
        if position.status == POSITION_OPEN:
            position.take_profit = new_tp

    def get_open_position(self, symbol: str) -> Optional[Position]:
        """Lấy position đang mở của một symbol (V1: max 1 position/symbol)."""
        for p in self.positions:
            if p.symbol == symbol and p.status == POSITION_OPEN:
                return p
        return None

    def get_all_open_positions(self) -> list[Position]:
        """Lấy tất cả positions đang mở."""
        return [p for p in self.positions if p.status == POSITION_OPEN]

    def get_closed_positions(self) -> list[Position]:
        """Lấy tất cả positions đã đóng."""
        return [p for p in self.positions if p.status == POSITION_CLOSED]

    def update_mae_mfe(self, position: Position, current_price: float) -> None:
        """Cập nhật MAE/MFE cho position đang mở.

        MAE = Maximum Adverse Excursion (giá xa nhất bất lợi)
        MFE = Maximum Favorable Excursion (giá xa nhất thuận lợi)
        """
        if position.status != POSITION_OPEN:
            return

        entry = position.entry_price
        direction = position.direction

        if direction == DIRECTION_LONG:
            adverse = entry - current_price   # giá xuống = adverse
            favorable = current_price - entry  # giá lên = favorable
        else:
            adverse = current_price - entry    # giá lên = adverse
            favorable = entry - current_price  # giá xuống = favorable

        if adverse > position.max_adverse:
            position.max_adverse = adverse
        if favorable > position.max_favorable:
            position.max_favorable = favorable

    def _get_contract_size(self, symbol: str) -> float:
        """Lấy contract size."""
        specs = getattr(self, '_specs', {})
        if isinstance(specs, dict) and symbol in specs:
            cs = specs[symbol].get("contract_size", 0)
            if cs > 0:
                return cs
        sizes = {"XAUUSD": 100, "GBPUSD": 100000, "EURUSD": 100000}
        return sizes.get(symbol, 100000)

    def _set_specs(self, symbol_specs: dict):
        """Gán symbol_specs (được gọi từ ExecutionEngine)."""
        self._specs = symbol_specs

    def _get_point_size(self, symbol: str) -> float:
        sizes = {"XAUUSD": 0.01, "GBPUSD": 0.00001, "EURUSD": 0.00001}
        return sizes.get(symbol, 0.00001)
