"""
No-Lookahead Guard — prevent repaint errors at runtime.

Each rule raises a LookaheadError if violated so the engine
catches future-leaking logic before it poisons backtest results.
"""

from dataclasses import dataclass, field
from typing import Optional


class LookaheadError(Exception):
    """Raised when the engine violates a no-lookahead rule."""
    pass


@dataclass
class Violation:
    rule: str
    current_bar: int
    detail: str


class NoLookaheadGuard:
    """
    Runtime guard that checks every event and state transition.

    Rules (from spec):
      - event_time >= confirm_time
      - object_active_from >= confirmed_at
      - HTF timestamp used < LTF current timestamp
      - pivot_confirm_bar >= pivot_center + rightbars
      - no event assigned retroactively
    """

    def __init__(self, strict: bool = True):
        self.strict = strict
        self.violations: list[Violation] = []

    def check_pivot_timing(self, pivot_center: int, pivot_confirm: int,
                           right_bars: int, label: str = "") -> None:
        """Pivot must be confirmed only after right_bars have passed."""
        min_confirm = pivot_center + right_bars
        if pivot_confirm < min_confirm:
            msg = (f"Pivot at bar {pivot_center} confirmed at bar {pivot_confirm} "
                   f"but needs >= {min_confirm} (right={right_bars}) [{label}]")
            self._violate("pivot_timing", pivot_confirm, msg)

    def check_event_time(self, event_time: int, confirm_time: int,
                         event_type: str, bar: int) -> None:
        """Event timestamp must be >= its confirmation time."""
        if event_time < confirm_time:
            msg = (f"{event_type} at [{event_time}] < confirm_time [{confirm_time}] "
                   f"at bar {bar}")
            self._violate("event_time", bar, msg)

    def check_object_activation(self, active_from: int, confirmed_at: int,
                                obj_id: str, bar: int) -> None:
        """Object activation must be >= its confirmation."""
        if active_from < confirmed_at:
            msg = (f"Object {obj_id} active_from [{active_from}] < "
                   f"confirmed_at [{confirmed_at}] at bar {bar}")
            self._violate("object_activation", bar, msg)

    def check_htf_timing(self, htf_ts: int, ltf_ts: int, bar: int) -> None:
        """HTF candle must be fully closed before LTF uses it."""
        if htf_ts >= ltf_ts:
            msg = (f"HTF candle {htf_ts} >= LTF current {ltf_ts} at bar {bar} "
                   f"— HTF candle still open!")
            self._violate("htf_timing", bar, msg)

    def check_no_retroactive_event(self, event_bar: int, current_bar: int,
                                   event_type: str) -> None:
        """An event cannot be assigned to a bar in the past."""
        if event_bar < current_bar:
            msg = (f"{event_type} assigned to bar {event_bar} but current bar "
                   f"is {current_bar} — retroactive!")
            self._violate("retroactive_event", current_bar, msg)

    def _violate(self, rule: str, bar: int, detail: str) -> None:
        v = Violation(rule=rule, current_bar=bar, detail=detail)
        self.violations.append(v)
        if self.strict:
            raise LookaheadError(f"[bar {bar}] {detail}")

    def summary(self) -> str:
        if not self.violations:
            return "No lookahead violations ✓"
        lines = [f"{len(self.violations)} violation(s):"]
        for v in self.violations:
            lines.append(f"  • [bar {v.current_bar}] {v.rule}: {v.detail}")
        return "\n".join(lines)

    def clear(self) -> None:
        self.violations.clear()
