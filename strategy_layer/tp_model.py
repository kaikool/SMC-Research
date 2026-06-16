"""
Take Profit Model — Tính take profit cho setup.

Các kiểu TP:
  - fixed_r: R multiple (2R, 3R, ...)
  - liquidity_target: opposing liquidity pool
  - swing_extreme: opposing swing high/low
  - equilibrium: midpoint of premium/discount range
"""

from typing import Optional
from .models import Setup, DIRECTION_LONG, DIRECTION_SHORT
from .config import StrategyConfig


def calculate_tp(setup: Setup, config: StrategyConfig,
                 snap: dict, objects_cache: dict = None,
                 current_price: float = 0.0) -> tuple[float, str]:
    """Tính take profit cho setup.

    Returns:
        (tp_price, tp_type)
    """
    tp_type = config.tp_type
    sl_price = setup.sl_price
    entry_price = setup.entry_zone_mid

    # Nếu chưa có SL hoặc entry hợp lệ, dùng fixed R mặc định
    if sl_price <= 0:
        sl_price = entry_price * 1.01 if setup.direction == DIRECTION_SHORT else entry_price * 0.99

    risk_distance = abs(entry_price - sl_price) if entry_price > 0 else 0.001

    if tp_type == "fixed_r":
        r_multi = config.tp_r_multiple
        if setup.direction == DIRECTION_SHORT:
            tp_price = entry_price - risk_distance * r_multi
        else:
            tp_price = entry_price + risk_distance * r_multi

    elif tp_type == "swing_extreme":
        # LONG: TP at last swing high
        # SHORT: TP at last swing low
        if setup.direction == DIRECTION_LONG:
            tp_price = float(snap.get("last_swing_high", 0))
        else:
            tp_price = float(snap.get("last_swing_low", 0))

        # Nếu không có swing, fallback fixed R
        if tp_price <= 0 or (setup.direction == DIRECTION_LONG and tp_price <= entry_price):
            tp_price = entry_price + risk_distance * config.tp_r_multiple
        elif setup.direction == DIRECTION_SHORT and tp_price >= entry_price:
            tp_price = entry_price - risk_distance * config.tp_r_multiple

    elif tp_type == "equilibrium":
        # Equilibrium = avg of last_swing_high and last_swing_low
        swing_high = float(snap.get("last_swing_high", 0))
        swing_low = float(snap.get("last_swing_low", 0))
        if swing_high > 0 and swing_low > 0:
            tp_price = (swing_high + swing_low) / 2
        else:
            tp_price = entry_price + risk_distance * config.tp_r_multiple if setup.direction == DIRECTION_LONG else entry_price - risk_distance * config.tp_r_multiple

    else:
        # Fallback fixed R
        if setup.direction == DIRECTION_SHORT:
            tp_price = entry_price - risk_distance * config.tp_r_multiple
        else:
            tp_price = entry_price + risk_distance * config.tp_r_multiple

    return round(tp_price, 5), tp_type
