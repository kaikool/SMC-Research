"""
Margin Model — Tính margin, free margin, margin level.

V1 đơn giản:
  required_margin = notional / leverage
  margin_level = equity / used_margin

Chỉ hỗ trợ quote USD để tránh currency conversion.
"""

from typing import Optional


class MarginModel:
    """Tính toán margin."""

    def __init__(self, config, symbol_specs: dict):
        self.config = config
        self.specs = symbol_specs

    def _get_specs(self, symbol: str) -> dict:
        """Lấy per-symbol specs."""
        if isinstance(self.specs, dict) and symbol and symbol in self.specs:
            return self.specs[symbol]
        return self.specs if isinstance(self.specs, dict) else {}

    def required_margin(self, lots: float, price: float,
                        symbol: str = "") -> float:
        """Tính required margin cho một vị thế.

        V1: notional / leverage, giả sử quote currency = USD.
        """
        if not self.config.margin.enabled:
            return 0.0

        specs = self._get_specs(symbol)
        contract_size = specs.get("contract_size", 100000)
        notional = lots * contract_size * price
        leverage = specs.get("leverage", self.config.account.leverage)
        return notional / leverage

    def total_used_margin(self, positions: list) -> float:
        """Tính tổng used margin từ tất cả vị thế đang mở."""
        total = 0.0
        for pos in positions:
            if pos.status == "open":
                specs = self._get_specs(pos.symbol)
                contract_size = specs.get("contract_size", 100000)
                notional = pos.size_lot * contract_size * pos.entry_price
                leverage = specs.get("leverage", self.config.account.leverage)
                total += notional / leverage
        return total

    def free_margin(self, equity: float, used_margin: float) -> float:
        """Tính free margin."""
        return max(0.0, equity - used_margin)

    def margin_level(self, equity: float, used_margin: float) -> float:
        """Tính margin level (%)."""
        if used_margin <= 0:
            return 9999.0  # no margin used
        return equity / used_margin

    def check_margin_call(self, equity: float, used_margin: float) -> bool:
        """Kiểm tra margin call: equity <= stop_out_level * used_margin."""
        if not self.config.margin.enabled:
            return False
        if used_margin <= 0:
            return False
        level = self.margin_level(equity, used_margin)
        return level <= self.config.margin.stop_out_level
