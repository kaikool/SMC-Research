"""
Stop Loss Model — Tính stop loss cho setup.

Các kiểu SL:
  - sweep_extreme: trên sweep high (short) / dưới sweep low (long)
  - ob_extreme: trên OB (short) / dưới OB (long)
  - swing_extreme: trên swing high (short) / dưới swing low (long)
  - atr: ATR * multiple
"""

from typing import Optional
from .models import Setup, DIRECTION_LONG, DIRECTION_SHORT
from .config import StrategyConfig


def calculate_sl(setup: Setup, config: StrategyConfig,
                 snap: dict, objects_cache: dict = None,
                 atr_value: float = 0.0) -> tuple[float, str]:
    """Tính stop loss cho setup.

    Returns:
        (sl_price, sl_type)
    """
    sl_type = config.sl_type

    if sl_type == "sweep_extreme":
        # SHORT: SL trên sweep high / swing high
        # LONG:  SL dưới sweep low / swing low
        if setup.direction == DIRECTION_SHORT:
            sl_price = float(snap.get("last_swing_high", 0))
            # Nếu OB top cao hơn swing high thì dùng OB top
            if setup.entry_zone_top > sl_price:
                sl_price = setup.entry_zone_top
        else:
            sl_price = float(snap.get("last_swing_low", 0))
            if setup.entry_zone_bottom < sl_price or sl_price == 0:
                sl_price = setup.entry_zone_bottom

        # Thêm buffer
        if config.sl_use_fixed_buffer and config.sl_buffer_pips > 0:
            buffer = config.sl_buffer_pips * 0.0001
            if setup.direction == DIRECTION_SHORT:
                sl_price += buffer
            else:
                sl_price -= buffer

        # --- Giới hạn khoảng cách SL tối đa ---
        # Tránh SL quá xa entry (vd swing low từ 1000 bars trước)
        entry = setup.entry_zone_mid
        if entry > 0 and sl_price > 0:
            max_distance = config.sl_buffer_atr_ratio * 10  # ATR multiples
            if max_distance <= 0:
                # Mặc định: max 2.0 cho XAUUSD (200 pips) / 0.02 cho forex
                max_distance = 2.0 if entry > 100 else 0.02
            if setup.direction == DIRECTION_SHORT:
                actual_dist = sl_price - entry
                if actual_dist > max_distance:
                    sl_price = entry + max_distance
            else:
                actual_dist = entry - sl_price
                if actual_dist > max_distance:
                    sl_price = entry - max_distance

    elif sl_type == "ob_extreme":
        if setup.direction == DIRECTION_SHORT:
            sl_price = setup.entry_zone_top + (config.sl_buffer_pips * 0.0001 if config.sl_use_fixed_buffer else 0)
        else:
            sl_price = setup.entry_zone_bottom - (config.sl_buffer_pips * 0.0001 if config.sl_use_fixed_buffer else 0)

    elif sl_type == "atr" and atr_value > 0:
        # ATR-based SL
        atr_multiple = max(0.5, config.sl_buffer_atr_ratio * 10 if config.sl_buffer_atr_ratio > 0 else 1.0)
        if setup.direction == DIRECTION_SHORT:
            sl_price = setup.entry_zone_mid + atr_value * atr_multiple
        else:
            sl_price = setup.entry_zone_mid - atr_value * atr_multiple

    else:
        # Fallback: OB boundary
        if setup.direction == DIRECTION_SHORT:
            sl_price = setup.entry_zone_top
        else:
            sl_price = setup.entry_zone_bottom
        sl_type = "ob_extreme"

    return round(sl_price, 5), sl_type
