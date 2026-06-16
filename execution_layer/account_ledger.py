"""
Account Ledger — Sổ tài khoản ghi mọi thay đổi tiền.

Ghi nhận:
  - balance, equity, realized_pnl, unrealized_pnl
  - used_margin, free_margin
  - commission_paid
  - deposit/withdraw

Mỗi bar cần update unrealized PnL từ positions đang mở.
"""

from typing import Optional
from .models import (
    AccountState, LedgerEntry, Position, BarOHLC,
    DIRECTION_LONG, DIRECTION_SHORT,
    POSITION_OPEN,
)


class AccountLedger:
    """Quản lý sổ tài khoản."""

    def __init__(self, config):
        self.config = config
        self.account = AccountState(
            balance=config.account.initial_balance,
            equity=config.account.initial_balance,
            free_margin=config.account.initial_balance,
            margin_level=9999.0,
        )
        self.ledger: list[LedgerEntry] = []
        self.equity_curve: list[dict] = []
        self._peak_equity = config.account.initial_balance
        self._daily_pnl = 0.0
        self._last_trading_day = -1

    def compute_unrealized_pnl(self, positions: list[Position],
                                bar: BarOHLC) -> float:
        """Tính unrealized PnL từ tất cả positions đang mở."""
        total = 0.0
        for pos in positions:
            if pos.status != POSITION_OPEN:
                continue
            direction = pos.direction
            lots = pos.size_lot
            entry = pos.entry_price
            contract_size = self._get_contract_size(pos.symbol)

            if direction == DIRECTION_LONG:
                # Long: unrealized = (close_bid - entry) * lots * contract_size
                pnl = (bar.close_bid - entry) * lots * contract_size
            else:
                # Short: unrealized = (entry - close_ask) * lots * contract_size
                pnl = (entry - bar.close_ask) * lots * contract_size
            total += pnl
        return total

    def update_equity(self, unrealized_pnl: float, used_margin: float):
        """Cập nhật equity, free_margin, margin_level."""
        self.account.unrealized_pnl = unrealized_pnl
        self.account.equity = self.account.balance + unrealized_pnl
        self.account.used_margin = used_margin
        self.account.free_margin = max(0.0, self.account.equity - used_margin)

        if used_margin > 0:
            self.account.margin_level = self.account.equity / used_margin
        else:
            self.account.margin_level = 9999.0

        # Peak equity for drawdown
        if self.account.equity > self._peak_equity:
            self._peak_equity = self.account.equity

    def record_bar(self, timestamp: int, open_positions: int) -> dict:
        """Ghi trạng thái tài khoản vào equity curve sau mỗi bar.

        Returns:
            dict: {equity, drawdown} cho bar này
        """
        drawdown = self._peak_equity - self.account.equity

        row = self.account.to_equity_row(timestamp, open_positions, drawdown)
        self.equity_curve.append(row)
        return row

    def apply_realized_pnl(self, net_pnl: float, position: Position,
                           timestamp: int, event_type: str = "CLOSE",
                           reason: str = "") -> LedgerEntry:
        """Ghi nhận realized PnL khi đóng position."""
        before = self.account.balance
        self.account.balance += net_pnl
        self.account.realized_pnl += net_pnl
        after = self.account.balance

        if net_pnl < 0:
            self._daily_pnl += net_pnl

        entry = LedgerEntry(
            timestamp=timestamp,
            event_type=event_type,
            amount=net_pnl,
            balance_before=before,
            balance_after=after,
            position_id=position.position_id,
            order_id=position.order_id,
            reason=reason,
        )
        self.ledger.append(entry)

        # Update equity immediately
        self.account.equity = self.account.balance + self.account.unrealized_pnl
        return entry

    def apply_commission(self, amount: float, timestamp: int,
                         position_id: str = "", order_id: str = "",
                         reason: str = "commission") -> LedgerEntry:
        """Ghi nhận phí giao dịch."""
        if amount <= 0:
            return None
        before = self.account.balance
        self.account.balance -= amount
        self.account.commission_paid += amount
        after = self.account.balance

        entry = LedgerEntry(
            timestamp=timestamp,
            event_type="COMMISSION",
            amount=-amount,
            balance_before=before,
            balance_after=after,
            position_id=position_id,
            order_id=order_id,
            reason=reason,
        )
        self.ledger.append(entry)
        return entry

    def check_daily_loss_limit(self) -> bool:
        """Kiểm tra daily loss limit.

        Returns:
            True nếu vượt quá daily loss limit.
        """
        if self.config.risk_limits.max_daily_loss_pct <= 0:
            return False
        max_loss = self.config.account.initial_balance * (
            self.config.risk_limits.max_daily_loss_pct / 100.0
        )
        return self._daily_pnl <= -max_loss

    def reset_daily_pnl(self):
        """Reset daily PnL (gọi đầu mỗi ngày giao dịch mới)."""
        self._daily_pnl = 0.0

    def _get_contract_size(self, symbol: str) -> float:
        sizes = {"XAUUSD": 100, "GBPUSD": 100000, "EURUSD": 100000}
        return sizes.get(symbol, 100000)
