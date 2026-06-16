"""
Setup State Machine — vòng đời của một setup.

Transitions:
  created → pending → armed → triggered → entered → completed
                      → cancelled       → cancelled
    → expired                              → expired
"""

from .models import (
    Setup, OrderIntent, StrategyDecision,
    SETUP_STATUS_CREATED, SETUP_STATUS_PENDING, SETUP_STATUS_ARMED,
    SETUP_STATUS_TRIGGERED, SETUP_STATUS_ENTERED,
    SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED,
    SETUP_STATUS_COMPLETED,
    DIRECTION_LONG, DIRECTION_SHORT, DIRECTION_NONE,
)


class SetupStateMachine:
    """Quản lý state transition cho một setup."""

    # Valid transitions
    _TRANSITIONS = {
        SETUP_STATUS_CREATED:   {SETUP_STATUS_PENDING, SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED},
        SETUP_STATUS_PENDING:   {SETUP_STATUS_ARMED, SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED},
        SETUP_STATUS_ARMED:     {SETUP_STATUS_TRIGGERED, SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED},
        SETUP_STATUS_TRIGGERED: {SETUP_STATUS_ENTERED, SETUP_STATUS_CANCELLED, SETUP_STATUS_EXPIRED},
        SETUP_STATUS_ENTERED:   {SETUP_STATUS_COMPLETED, SETUP_STATUS_CANCELLED},
        # Terminal states
        SETUP_STATUS_CANCELLED: set(),
        SETUP_STATUS_EXPIRED:   set(),
        SETUP_STATUS_COMPLETED: set(),
    }

    def __init__(self, setup: Setup):
        self.setup = setup

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self._TRANSITIONS.get(self.setup.status, set())

    def transition_to(self, new_status: str, bar_index: int) -> bool:
        if not self.can_transition_to(new_status):
            return False

        self.setup.status = new_status
        self.setup.last_active_bar = bar_index

        # Ghi lại bar đánh dấu
        bar_attrs = {
            SETUP_STATUS_CREATED: "created_bar",
            SETUP_STATUS_ARMED: None,  # không ghi đè
            SETUP_STATUS_TRIGGERED: "triggered_bar",
            SETUP_STATUS_ENTERED: "entered_bar",
            SETUP_STATUS_CANCELLED: "cancelled_bar",
            SETUP_STATUS_EXPIRED: "expired_bar",
            SETUP_STATUS_COMPLETED: "completed_bar",
        }
        attr = bar_attrs.get(new_status)
        if attr and getattr(self.setup, attr) == 0:
            setattr(self.setup, attr, bar_index)

        return True

    @staticmethod
    def create_decision(setup: Setup, decision: str, passed: bool = True,
                        reasons: list = None, metadata: str = "",
                        bar_index: int = 0, timestamp: int = 0) -> StrategyDecision:
        return StrategyDecision(
            timestamp=timestamp,
            bar_index=bar_index,
            setup_id=setup.setup_id,
            decision=decision,
            passed=passed,
            failed_reasons=reasons or [],
            metadata=metadata,
        )
