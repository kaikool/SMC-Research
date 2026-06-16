"""
Trade Recorder — Ghi lịch sử giao dịch và lệnh.

Output:
  - orders.csv: tất cả lệnh (kể cả lệnh không khớp)
  - trades.csv: tất cả giao dịch đã hoàn thành
  - positions.csv: tất cả positions (open + closed)
  - account_ledger.csv: sổ tài khoản
  - equity_curve.csv: đường cong equity
  - execution_decisions.csv: audit log
"""

import csv
import os
from typing import Optional
from .models import (
    Order, Position, AccountState, LedgerEntry, ExecutionDecision,
    ORDERS_CSV_FIELDS, TRADES_CSV_FIELDS,
    ACCOUNT_LEDGER_CSV_FIELDS, EQUITY_CURVE_CSV_FIELDS,
    LEDGER_LOG_CSV_FIELDS, EXECUTION_DECISIONS_CSV_FIELDS,
)


class TradeRecorder:
    """Ghi tất cả output ra CSV."""

    def __init__(self, output_dir: str = "."):
        self.output_dir = output_dir
        self.decisions: list[ExecutionDecision] = []
        os.makedirs(output_dir, exist_ok=True)

    def export_all(self, orders: list[Order], positions: list[Position],
                   account: AccountState, ledger: list[LedgerEntry],
                   equity_curve: list[dict]) -> dict[str, str]:
        """Xuất tất cả output CSV.

        Returns:
            dict: {output_type: file_path}
        """
        paths = {}

        # orders.csv
        paths["orders"] = self._export_orders(orders)

        # trades.csv (positions đã đóng)
        paths["trades"] = self._export_trades(positions)

        # positions.csv (tất cả positions)
        paths["positions"] = self._export_positions(positions)

        # account_ledger.csv (per-bar)
        paths["account_ledger"] = self._export_account_ledger(account, equity_curve)

        # equity_curve.csv
        paths["equity_curve"] = self._export_equity_curve(equity_curve)

        # ledger_log.csv (chi tiết từng giao dịch)
        paths["ledger_log"] = self._export_ledger_log(ledger)

        # execution_decisions.csv
        paths["execution_decisions"] = self._export_decisions()

        return paths

    def _export_orders(self, orders: list[Order]) -> str:
        path = os.path.join(self.output_dir, "orders.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ORDERS_CSV_FIELDS)
            writer.writeheader()
            for o in orders:
                writer.writerow(o.to_csv_row())
        return path

    def _export_trades(self, positions: list[Position]) -> str:
        path = os.path.join(self.output_dir, "trades.csv")
        closed = [p for p in positions if p.status == "closed"]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADES_CSV_FIELDS)
            writer.writeheader()
            for p in closed:
                writer.writerow(p.to_csv_row())
        return path

    def _export_positions(self, positions: list[Position]) -> str:
        path = os.path.join(self.output_dir, "positions.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADES_CSV_FIELDS)
            writer.writeheader()
            for p in positions:
                writer.writerow(p.to_csv_row())
        return path

    def _export_account_ledger(self, account: AccountState,
                               equity_curve: list[dict]) -> str:
        path = os.path.join(self.output_dir, "account_ledger.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=ACCOUNT_LEDGER_CSV_FIELDS)
            writer.writeheader()
            for row in equity_curve:
                writer.writerow({k: row.get(k, "") for k in ACCOUNT_LEDGER_CSV_FIELDS})
        return path

    def _export_equity_curve(self, equity_curve: list[dict]) -> str:
        path = os.path.join(self.output_dir, "equity_curve.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=EQUITY_CURVE_CSV_FIELDS)
            writer.writeheader()
            for row in equity_curve:
                writer.writerow(row)
        return path

    def _export_ledger_log(self, ledger: list[LedgerEntry]) -> str:
        path = os.path.join(self.output_dir, "ledger_log.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_LOG_CSV_FIELDS)
            writer.writeheader()
            for entry in ledger:
                writer.writerow(entry.to_csv_row())
        return path

    def _export_decisions(self) -> str:
        path = os.path.join(self.output_dir, "execution_decisions.csv")
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=EXECUTION_DECISIONS_CSV_FIELDS)
            writer.writeheader()
            for d in self.decisions:
                writer.writerow(d.to_csv_row())
        return path

    def log_decision(self, timestamp: int, bar_index: int,
                     order_id: str, decision: str,
                     reason: str = "", details: str = "") -> None:
        """Ghi một execution decision."""
        self.decisions.append(ExecutionDecision(
            timestamp=timestamp,
            bar_index=bar_index,
            order_id=order_id,
            decision=decision,
            reason=reason,
            details=details,
        ))
