"""
Strategy Layer — Data types cho setup, order intent, decision logging.

Định nghĩa tất cả struct cần thiết cho Strategy Layer V1.
"""

from dataclasses import dataclass, field
from typing import Optional


# ── Setup Status ───────────────────────────────────────────────

SETUP_STATUS_CREATED     = "created"
SETUP_STATUS_PENDING     = "pending"
SETUP_STATUS_ARMED       = "armed"
SETUP_STATUS_TRIGGERED   = "triggered"
SETUP_STATUS_ENTERED     = "entered"
SETUP_STATUS_CANCELLED   = "cancelled"
SETUP_STATUS_EXPIRED     = "expired"
SETUP_STATUS_COMPLETED   = "completed"

VALID_SETUP_STATUSES = {
    SETUP_STATUS_CREATED,
    SETUP_STATUS_PENDING,
    SETUP_STATUS_ARMED,
    SETUP_STATUS_TRIGGERED,
    SETUP_STATUS_ENTERED,
    SETUP_STATUS_CANCELLED,
    SETUP_STATUS_EXPIRED,
    SETUP_STATUS_COMPLETED,
}

# ── Direction ──────────────────────────────────────────────────

DIRECTION_LONG  = 1
DIRECTION_SHORT = -1
DIRECTION_NONE  = 0


# ── Order Types ────────────────────────────────────────────────

ORDER_TYPE_MARKET = "market"
ORDER_TYPE_LIMIT  = "limit"


# ── Data Classes ───────────────────────────────────────────────

@dataclass
class Setup:
    """Một setup giao dịch — kết quả của Signal Rule Engine."""

    setup_id: str
    created_at: int                 # ms epoch
    direction: int                  # 1 = long, -1 = short
    setup_type: str                 # "sweep_choch_ob", "bos_retest", ...
    source_events: list[str]        # event IDs gốc (sweep_001, choch_002, ...)
    source_objects: list[str]       # object IDs (ob_001, fvg_001, ...)
    entry_zone_top: float = 0.0
    entry_zone_bottom: float = 0.0
    entry_zone_mid: float = 0.0
    sl_price: float = 0.0
    sl_type: str = ""
    tp_price: float = 0.0
    tp_type: str = ""
    status: str = SETUP_STATUS_CREATED
    confidence: float = 0.0
    quality_score: float = 0.0
    grade: str = "N/A"
    metadata: dict = field(default_factory=dict)

    # Bar tracking
    created_bar: int = 0
    last_active_bar: int = 0
    triggered_bar: int = 0
    cancelled_bar: int = 0
    expired_bar: int = 0
    entered_bar: int = 0
    completed_bar: int = 0

    def to_csv_row(self) -> dict:
        return {
            "setup_id": self.setup_id,
            "created_at": self.created_at,
            "created_bar": self.created_bar,
            "direction": self.direction,
            "setup_type": self.setup_type,
            "source_events": ";".join(self.source_events),
            "source_objects": ";".join(self.source_objects),
            "entry_zone_top": round(self.entry_zone_top, 5),
            "entry_zone_bottom": round(self.entry_zone_bottom, 5),
            "entry_price": round(self.entry_zone_mid, 5),
            "sl_price": round(self.sl_price, 5),
            "tp_price": round(self.tp_price, 5),
            "status": self.status,
            "quality_score": round(self.quality_score, 2),
            "grade": self.grade,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class OrderIntent:
    """Một order intent sẵn sàng gửi sang Execution Layer."""

    timestamp: int                  # ms epoch
    bar_index: int
    setup_id: str
    action: str                     # "PLACE_ORDER", "CANCEL_ORDER", "MODIFY_ORDER"
    symbol: str = ""
    timeframe: str = ""
    direction: int = DIRECTION_NONE
    order_type: str = ORDER_TYPE_MARKET
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    risk_pct: float = 0.0
    valid_until: int = 0            # ms epoch
    status: str = "pending"

    def to_csv_row(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "bar_index": self.bar_index,
            "setup_id": self.setup_id,
            "action": self.action,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "order_type": self.order_type,
            "entry_price": round(self.entry_price, 5),
            "sl_price": round(self.sl_price, 5),
            "tp_price": round(self.tp_price, 5),
            "risk_pct": round(self.risk_pct, 4),
            "valid_until": self.valid_until,
            "status": self.status,
        }


@dataclass
class StrategyDecision:
    """Một quyết định từ strategy — dùng cho audit log."""

    timestamp: int                  # ms epoch
    bar_index: int
    setup_id: str
    decision: str                   # "CREATE_SETUP", "REJECT_SETUP",
                                    # "ARM_SETUP", "TRIGGER_SETUP",
                                    # "ENTER", "CANCEL", "EXPIRE",
                                    # "PLACE_ORDER", "SKIP_ORDER",
                                    # "EXIT_TRADE"
    passed: bool = True
    failed_reasons: list[str] = field(default_factory=list)
    metadata: str = ""

    def to_csv_row(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "bar_index": self.bar_index,
            "setup_id": self.setup_id,
            "decision": self.decision,
            "passed": 1 if self.passed else 0,
            "failed_reasons": ";".join(self.failed_reasons) if self.failed_reasons else "",
            "metadata": self.metadata,
        }


# ── Setup CSV field names ──────────────────────────────────────

SETUP_CSV_FIELDS = [
    "setup_id", "created_at", "created_bar",
    "direction", "setup_type", "source_events", "source_objects",
    "entry_zone_top", "entry_zone_bottom", "entry_price",
    "sl_price", "tp_price",
    "status", "quality_score", "grade", "confidence",
]

ORDER_INTENT_CSV_FIELDS = [
    "timestamp", "bar_index", "setup_id", "action",
    "symbol", "timeframe", "direction", "order_type",
    "entry_price", "sl_price", "tp_price",
    "risk_pct", "valid_until", "status",
]

DECISION_CSV_FIELDS = [
    "timestamp", "bar_index", "setup_id",
    "decision", "passed", "failed_reasons", "metadata",
]
