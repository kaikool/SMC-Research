"""
Commission Model — Tính phí giao dịch.

Các dạng:
  - per_lot: USD mỗi lot round-turn
  - per_million: USD mỗi 1M notional
  - none
"""


class CommissionModel:
    """Tính commission cho mỗi lệnh."""

    def __init__(self, config, symbol_specs: dict = None):
        self.config = config
        self.specs = symbol_specs or {}

    def calculate_entry_commission(self, symbol: str, lots: float,
                                   entry_price: float) -> float:
        """Tính commission khi vào lệnh."""
        return self._calculate(symbol, lots, entry_price) / 2.0

    def calculate_exit_commission(self, symbol: str, lots: float,
                                  exit_price: float) -> float:
        """Tính commission khi ra lệnh."""
        return self._calculate(symbol, lots, exit_price) / 2.0

    def calculate_round_turn(self, symbol: str, lots: float,
                             price: float) -> float:
        """Tính round-turn commission."""
        return self._calculate(symbol, lots, price)

    def _calculate(self, symbol: str, lots: float, price: float) -> float:
        """Tính commission cơ bản."""
        cfg = self.config.commission
        mode = cfg.mode

        if mode == "none" or not mode:
            return 0.0

        if mode == "per_lot":
            rate = cfg.per_lot_round_turn.get(symbol, 0)
            return lots * rate

        if mode == "per_million":
            rate = cfg.per_million.get(symbol, 0)
            notional = lots * self._get_contract_size(symbol) * price
            return (notional / 1_000_000) * rate

        return 0.0

    def _get_contract_size(self, symbol: str) -> float:
        """Lấy contract size từ symbol specs hoặc hardcoded fallback."""
        # Ưu tiên từ symbol_specs
        if isinstance(self.specs, dict) and symbol in self.specs:
            cs = self.specs[symbol].get("contract_size", 0)
            if cs > 0:
                return cs
        # Fallback hardcoded
        sizes = {"XAUUSD": 100, "GBPUSD": 100000, "EURUSD": 100000}
        return sizes.get(symbol, 100000)
