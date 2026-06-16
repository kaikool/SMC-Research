"""
Decision Logger — Ghi lý do mọi quyết định của Strategy Layer.

Mỗi quyết định (tạo setup, lọc, hủy, vào lệnh, thoát) đều được ghi lại
để sau này audit và cải thiện strategy.
"""

import csv
from typing import Optional
from .models import StrategyDecision


class DecisionLogger:
    """Ghi lại mọi quyết định trong quá trình chạy strategy."""

    def __init__(self, output_path: str = ""):
        self.decisions: list[StrategyDecision] = []
        self.output_path = output_path

    def log(self, decision: StrategyDecision) -> None:
        """Ghi một quyết định."""
        self.decisions.append(decision)

    def log_create(self, timestamp: int, bar_index: int,
                   setup_id: str, reasons: list = None) -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="CREATE_SETUP",
            passed=True, failed_reasons=reasons or [],
        )
        self.decisions.append(d)
        return d

    def log_reject(self, timestamp: int, bar_index: int,
                   setup_id: str, reasons: list[str]) -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="REJECT_SETUP",
            passed=False, failed_reasons=reasons,
        )
        self.decisions.append(d)
        return d

    def log_arm(self, timestamp: int, bar_index: int,
                setup_id: str) -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="ARM_SETUP",
            passed=True,
        )
        self.decisions.append(d)
        return d

    def log_trigger(self, timestamp: int, bar_index: int,
                    setup_id: str) -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="TRIGGER_SETUP",
            passed=True,
        )
        self.decisions.append(d)
        return d

    def log_enter(self, timestamp: int, bar_index: int,
                  setup_id: str) -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="ENTER",
            passed=True,
        )
        self.decisions.append(d)
        return d

    def log_cancel(self, timestamp: int, bar_index: int,
                   setup_id: str, reason: str = "") -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="CANCEL_SETUP",
            passed=False, failed_reasons=[reason] if reason else [],
            metadata=reason,
        )
        self.decisions.append(d)
        return d

    def log_expire(self, timestamp: int, bar_index: int,
                   setup_id: str) -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="EXPIRE_SETUP",
            passed=False, metadata="max_wait_bars_exceeded",
        )
        self.decisions.append(d)
        return d

    def log_place_order(self, timestamp: int, bar_index: int,
                        setup_id: str) -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="PLACE_ORDER",
            passed=True,
        )
        self.decisions.append(d)
        return d

    def log_skip_order(self, timestamp: int, bar_index: int,
                       setup_id: str, reason: str = "") -> StrategyDecision:
        d = StrategyDecision(
            timestamp=timestamp, bar_index=bar_index,
            setup_id=setup_id, decision="SKIP_ORDER",
            passed=False, failed_reasons=[reason] if reason else [],
            metadata=reason,
        )
        self.decisions.append(d)
        return d

    def export_csv(self, path: str = "") -> str:
        """Xuất tất cả decision ra CSV."""
        output = path or self.output_path
        if not output:
            return ""

        from .models import DECISION_CSV_FIELDS
        with open(output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=DECISION_CSV_FIELDS)
            writer.writeheader()
            for d in self.decisions:
                writer.writerow(d.to_csv_row())

        return output

    def summary(self) -> dict:
        """Thống kê nhanh các quyết định."""
        counts = {}
        for d in self.decisions:
            counts[d.decision] = counts.get(d.decision, 0) + 1
        passed = sum(1 for d in self.decisions if d.passed)
        failed = sum(1 for d in self.decisions if not d.passed)
        return {
            "total": len(self.decisions),
            "passed": passed,
            "failed": failed,
            "by_decision": counts,
        }
