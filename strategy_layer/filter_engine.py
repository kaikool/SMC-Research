"""
Filter Engine — Bộ lọc setup.

Các filter:
  - Session filter
  - Premium/Discount filter
  - HTF alignment filter
  - Spread filter
  - Sweep displacement filter
  - Min RR filter
  - Min confidence filter
"""

from typing import Optional
from .models import Setup, DIRECTION_LONG, DIRECTION_SHORT
from .config import StrategyConfig


class FilterEngine:
    """Kiểm tra các filter trên setup."""

    def __init__(self, config: StrategyConfig):
        self.config = config

    def check_all(self, setup: Setup, bar_index: int,
                  snap: dict, bar_events: list[dict]) -> tuple[bool, list[str]]:
        """Chạy tất cả filter, trả về (passed, failed_reasons)."""
        failed: list[str] = []

        # 1. Session
        ok, reason = self._check_session(snap)
        if not ok:
            failed.append(reason)

        # 2. Premium/Discount
        ok, reason = self._check_premium_discount(setup, snap)
        if not ok:
            failed.append(reason)

        # 3. Sweep displacement
        ok, reason = self._check_sweep_displacement(setup, bar_events)
        if not ok:
            failed.append(reason)

        # 4. Min RR
        ok, reason = self._check_min_rr(setup)
        if not ok:
            failed.append(reason)

        # 5. Min confidence
        ok, reason = self._check_min_confidence(setup)
        if not ok:
            failed.append(reason)

        # 6. HTF alignment
        ok, reason = self._check_htf_alignment(setup, snap)
        if not ok:
            failed.append(reason)

        return len(failed) == 0, failed

    def _check_session(self, snap: dict) -> tuple[bool, str]:
        if not self.config.session_enabled:
            return True, ""

        session_id = snap.get("session_id", "")
        session_map = {
            "1": "asia",
            "2": "london",
            "3": "new_york",
            "4": "asia",  # asia overlap
            "5": "london_overlap",
            "0": "unknown",
        }
        session_name = session_map.get(str(session_id).strip(), "unknown")

        if session_name not in self.config.allowed_sessions:
            return False, f"session_not_allowed:{session_name}"

        return True, ""

    def _check_premium_discount(self, setup: Setup, snap: dict) -> tuple[bool, str]:
        if not self.config.require_premium_discount:
            return True, ""

        in_premium = snap.get("in_premium", "False").lower() == "true"
        in_discount = snap.get("in_discount", "False").lower() == "true"

        if setup.direction == DIRECTION_SHORT and not in_premium:
            return False, "not_in_premium_for_short"
        if setup.direction == DIRECTION_LONG and not in_discount:
            return False, "not_in_discount_for_long"

        return True, ""

    def _check_sweep_displacement(self, setup: Setup,
                                   bar_events: list[dict]) -> tuple[bool, str]:
        if not self.config.require_sweep_displacement:
            return True, ""

        # Kiểm tra có sweep event trên bar này
        has_sweep = any("LIQUIDITY_SWEEP" in e.get("event_type", "") for e in bar_events)
        has_choch = any("CHOCH" in e.get("event_type", "") for e in bar_events)

        if not has_sweep and not has_choch:
            return True, ""  # sweep/choch từ bar trước

        # Nếu sweep xảy ra trên bar này, cần có displacement (CHOCH/BOS)
        if has_sweep and not has_choch:
            return False, "sweep_without_displacement"

        return True, ""

    def _check_min_rr(self, setup: Setup) -> tuple[bool, str]:
        if self.config.min_rr_ratio <= 0:
            return True, ""

        entry = setup.entry_zone_mid
        sl = setup.sl_price
        if entry <= 0 or sl <= 0:
            return True, ""

        risk = abs(entry - sl)
        # TP chưa có, dùng R từ entry và last swing
        reward = abs(setup.tp_price - entry) if setup.tp_price > 0 else risk * 2

        if risk > 0 and reward / risk < self.config.min_rr_ratio:
            return False, f"rr_below_min:{reward/risk:.2f}<{self.config.min_rr_ratio}"

        return True, ""

    def _check_min_confidence(self, setup: Setup) -> tuple[bool, str]:
        if setup.confidence < self.config.min_confidence:
            return False, f"low_confidence:{setup.confidence:.2f}<{self.config.min_confidence}"
        return True, ""

    def _check_htf_alignment(self, setup: Setup, snap: dict) -> tuple[bool, str]:
        if not self.config.require_htf_alignment:
            return True, ""

        trend = int(snap.get("current_trend", 0))
        if setup.direction == DIRECTION_LONG and trend <= 0:
            return False, f"htf_not_aligned_long:trend={trend}"
        if setup.direction == DIRECTION_SHORT and trend >= 0:
            return False, f"htf_not_aligned_short:trend={trend}"

        return True, ""
