"""
Entry Model — Tính giá entry cho setup.

Các kiểu entry:
  - market: giá hiện tại
  - limit tại OB midpoint
  - limit tại OB boundary (top cho long, bottom cho short)
  - limit tại FVG midpoint
"""

from typing import Optional
from .models import Setup, DIRECTION_LONG, DIRECTION_SHORT
from .config import StrategyConfig


def calculate_entry(setup: Setup, config: StrategyConfig,
                    current_price: float, bar_index: int,
                    snap: dict) -> tuple[float, str]:
    """Tính giá entry cho setup.

    Returns:
        (entry_price, entry_type) — entry_type là "market" hoặc "limit"
    """
    entry_type = config.entry_type
    entry_price = current_price

    if entry_type == "market":
        return current_price, "market"

    if entry_type == "limit":
        price_source = config.entry_price_source

        if price_source == "ob_mid":
            entry_price = setup.entry_zone_mid
        elif price_source == "ob_boundary":
            if setup.direction == DIRECTION_LONG:
                entry_price = setup.entry_zone_top  # long buy gần đáy OB
            else:
                entry_price = setup.entry_zone_bottom  # short sell gần đỉnh OB
        elif price_source == "ob_top":
            entry_price = setup.entry_zone_top
        elif price_source == "ob_bottom":
            entry_price = setup.entry_zone_bottom
        elif price_source == "current_price":
            entry_price = current_price
        else:
            entry_price = setup.entry_zone_mid

        # Adjustment
        if config.limit_price_adjustment != 0:
            entry_price += config.limit_price_adjustment * 0.0001 * (
                -1 if setup.direction == DIRECTION_SHORT else 1
            )

    return entry_price, entry_type
