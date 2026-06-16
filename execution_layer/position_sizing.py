"""
Position Sizing Engine — Biến risk% thành lot thật.

Công thức:
  risk_money = equity * risk_pct
  stop_distance = abs(entry_price - stop_loss)
  loss_per_lot = stop_distance * contract_size
  raw_lot = risk_money / loss_per_lot

  Sau đó chuẩn hóa: min_lot, lot_step, margin check.
"""

import math
from typing import Optional
from .models import DIRECTION_LONG, DIRECTION_SHORT


class PositionSizingEngine:
    """Tính lot size từ risk %."""

    def __init__(self, symbol_specs: dict):
        self.specs = symbol_specs

    def calculate_lots(self, equity: float, risk_pct: float,
                       entry_price: float, stop_loss: float,
                       symbol: str) -> tuple[float, Optional[str]]:
        """Tính lot size.

        Returns:
            (lot_size, reject_reason)
            reject_reason = None nếu thành công.
        """
        specs = self.specs.get(symbol, {}) if isinstance(self.specs, dict) and symbol in self.specs else self.specs
        if not specs:
            return 0.0, "symbol_specs_not_found"

        contract_size = specs.get("contract_size", 100000)
        min_lot = specs.get("min_lot", 0.01)
        lot_step = specs.get("lot_step", 0.01)
        max_lot = specs.get("max_lot", 100.0)

        # Risk money
        risk_money = equity * risk_pct

        # Stop distance in price
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance <= 0:
            return 0.0, "zero_stop_distance"

        # Loss per 1 lot
        loss_per_lot = stop_distance * contract_size
        if loss_per_lot <= 0:
            return 0.0, "invalid_loss_per_lot"

        # Raw lot
        raw_lot = risk_money / loss_per_lot

        # Normalize
        if raw_lot < min_lot:
            return 0.0, f"lot_below_minimum:raw={raw_lot:.6f}_min={min_lot}"

        # Round down to lot_step
        normalized = math.floor(raw_lot / lot_step) * lot_step
        normalized = max(min_lot, min(normalized, max_lot))

        return normalized, None

    def _get_specs(self, symbol: str) -> dict:
        """Lấy per-symbol specs."""
        if isinstance(self.specs, dict) and symbol in self.specs:
            return self.specs[symbol]
        return self.specs if isinstance(self.specs, dict) else {}

    def calculate_notional(self, lots: float, price: float,
                           symbol: str) -> float:
        """Tính notional value."""
        specs = self._get_specs(symbol)
        contract_size = specs.get("contract_size", 100000)
        return lots * contract_size * price

    def calculate_margin_required(self, lots: float, price: float,
                                  symbol: str, leverage: int = 100) -> float:
        """Tính required margin."""
        notional = self.calculate_notional(lots, price, symbol)
        return notional / leverage

    def calculate_stop_loss_pips(self, entry_price: float, stop_loss: float,
                                 symbol: str) -> float:
        """Tính stop distance bằng pip."""
        specs = self._get_specs(symbol)
        pip_size = specs.get("pip_size", 0.0001)
        return abs(entry_price - stop_loss) / pip_size
