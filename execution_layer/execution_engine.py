"""
Execution Engine — Lớp giả lập "sàn/broker" trong backtest.

Nó nhận order_intent từ Strategy Layer và trả lời:
  - Lệnh có được đặt không?
  - Có khớp không?
  - Khớp ở giá nào?
  - Spread/slippage/commission tính thế nào?
  - SL/TP có bị chạm không?
  - Margin có đủ không?
  - PnL cuối cùng là bao nhiêu?

SMC Event Engine nói: thị trường xảy ra gì.
Strategy Layer nói: có nên đánh không.
Execution Engine nói: nếu đánh thì lệnh có khớp thật không, giá nào, phí bao nhiêu, lời lỗ ròng ra sao.
"""

import json
import os
import csv
import math
from typing import Optional
from collections import defaultdict

from .execution_config import ExecutionConfig
from .spread_model import SpreadModel
from .slippage_model import SlippageModel
from .commission_model import CommissionModel
from .position_sizing import PositionSizingEngine
from .margin_model import MarginModel
from .fill_model import FillModel
from .order_manager import OrderManager
from .position_manager import PositionManager
from .sl_tp_handler import SLTPHandler
from .pending_order_handler import PendingOrderHandler
from .account_ledger import AccountLedger
from .trade_recorder import TradeRecorder

from .models import (
    Order, Position, BarOHLC,
    DIRECTION_LONG, DIRECTION_SHORT, DIRECTION_NONE,
    ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_STOP,
    ORDER_PENDING, ORDER_ACCEPTED, ORDER_FILLED, ORDER_REJECTED,
    ORDER_CANCELLED, ORDER_EXPIRED, ORDER_CREATED,
    POSITION_OPEN, POSITION_CLOSED,
    EXIT_SL, EXIT_TP, EXIT_MANUAL, EXIT_MARGIN_CALL,
    DECISION_ORDER_ACCEPTED, DECISION_ORDER_REJECTED,
    DECISION_ORDER_FILLED, DECISION_ORDER_CANCELLED,
    DECISION_ORDER_EXPIRED, DECISION_POSITION_OPENED,
    DECISION_POSITION_CLOSED, DECISION_SL_HIT,
    DECISION_TP_HIT, DECISION_MARGIN_REJECT,
)

# Field mapping từ Strategy Layer's OrderIntent CSV
ORDER_INTENT_FIELDS = [
    "timestamp", "bar_index", "setup_id", "action",
    "symbol", "timeframe", "direction", "order_type",
    "entry_price", "sl_price", "tp_price",
    "risk_pct", "valid_until", "status",
]


class ExecutionEngine:
    """Execution Engine chính — orchestrator của tất cả sub-components."""

    def __init__(self, config: ExecutionConfig, symbol_specs: dict = None):
        self.config = config
        self.symbol_specs = symbol_specs or {}

        # Sub-components
        self.spread_model = SpreadModel(config, self.symbol_specs)
        self.slippage_model = SlippageModel(config)
        self.commission_model = CommissionModel(config, self.symbol_specs)
        self.position_sizing = PositionSizingEngine(self.symbol_specs)
        self.margin_model = MarginModel(config, self.symbol_specs)
        self.fill_model = FillModel(config, self.spread_model, self.slippage_model)
        self.order_manager = OrderManager()
        self.position_manager = PositionManager(config)
        self.position_manager._set_specs(self.symbol_specs)
        self.sl_tp_handler = SLTPHandler(config)
        self.pending_order_handler = PendingOrderHandler(config)
        self.account_ledger = AccountLedger(config)
        self.trade_recorder = TradeRecorder()

        # Runtime state
        self.current_bar_index = -1
        self.current_timestamp = 0
        self._bars: list[BarOHLC] = []        # All bars with bid/ask
        self._bar_map: dict[int, BarOHLC] = {}  # bar_index → BarOHLC
        self._total_spread_cost = 0.0
        self._total_slippage_cost = 0.0
        self._total_commission = 0.0
        self._daily_loss_triggered = False
        self._last_trading_day = -1

    # ── Load data ────────────────────────────────────────────────

    def load_bars(self, bars_data: list[dict]) -> list[BarOHLC]:
        """Load OHLCV bars, compute bid/ask.

        bars_data: list of dict with keys:
            timestamp (int ms), bar_index (int),
            open, high, low, close, volume, spread_points (optional)
        """
        self._bars = []
        self._bar_map = {}

        for i, row in enumerate(bars_data):
            bar = BarOHLC(
                timestamp=int(row.get("timestamp", 0)),
                bar_index=int(row.get("bar_index", i)),
                symbol=row.get("symbol", ""),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("volume", 0)),
                spread_points=float(row.get("spread_points", 0)),
            )
            # Compute bid/ask
            self.spread_model.compute_bid_ask_for_bar(bar)
            self._bars.append(bar)
            self._bar_map[bar.bar_index] = bar

        return self._bars

    def load_order_intents(self, path: str) -> dict[int, list[dict]]:
        """Đọc orders_intent.csv, group theo bar_index.

        Returns:
            dict: {bar_index: [order_intent_dict, ...]}
        """
        intents_by_bar: dict[int, list[dict]] = defaultdict(list)

        if not os.path.exists(path):
            print(f"WARNING: {path} not found. No order intents loaded.")
            return intents_by_bar

        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    bi = int(row.get("bar_index", 0))
                except (ValueError, TypeError):
                    continue
                intents_by_bar[bi].append(dict(row))

        print(f"Loaded {sum(len(v) for v in intents_by_bar.values())} order intents "
              f"from {path} across {len(intents_by_bar)} bars")
        return intents_by_bar

    # ── Main processing ───────────────────────────────────────────

    def run(self, bars_data: list[dict],
            order_intents_bar: dict[int, list[dict]] = None) -> dict:
        """Chạy full backtest.

        Args:
            bars_data: list of bar dicts
            order_intents_bar: {bar_index: [order_intent_dict]}

        Returns:
            dict: kết quả thống kê
        """
        if order_intents_bar is None:
            order_intents_bar = {}

        bars = self.load_bars(bars_data)
        if not bars:
            return {"error": "No bars loaded"}

        print(f"Running Execution Engine over {len(bars)} bars...")

        for bar in bars:
            bi = bar.bar_index
            intents = order_intents_bar.get(bi, [])
            self.process_bar(bar, intents)

        # ── Export ──
        stats = self.summarize()
        return stats

    def process_bar(self, bar: BarOHLC, order_intents: list[dict] = None) -> dict:
        """Xử lý một bar đầy đủ.

        Thứ tự:
          1. Kiểm tra SL/TP cho positions đang mở
          2. Kiểm tra pending orders (expiry)
          3. Xử lý cancel/modify intents
          4. Kiểm tra fill cho pending orders (limit/stop)
          5. Xử lý order intents mới (market/limit/stop)
          6. Update MAE/MFE, unrealized PnL
          7. Ghi equity curve
        """
        if order_intents is None:
            order_intents = []

        self.current_bar_index = bar.bar_index
        self.current_timestamp = bar.timestamp

        events_this_bar = []

        # ── 0. Kiểm tra daily reset ──
        self._check_daily_reset(bar)

        # ── 1. Kiểm tra SL/TP ──
        sl_tp_events = self._process_sl_tp(bar)
        events_this_bar.extend(sl_tp_events)

        # ── 2. Kiểm tra pending order expiry ──
        self._process_expiry(bar)

        # ── 3. Xử lý cancel/modify intents ──
        self._process_cancel_intents(order_intents)

        # ── 4. Kiểm tra fill cho pending orders ──
        fill_events = self._process_pending_fills(bar)
        events_this_bar.extend(fill_events)

        # ── 5. Xử lý order intents mới ──
        self._process_new_intents(order_intents, bar)

        # ── 6. Update MAE/MFE cho positions đang mở ──
        self._update_mae_mfe(bar)

        # ── 7. Cập nhật tài khoản ──
        open_positions = self.position_manager.get_all_open_positions()
        unrealized = self.account_ledger.compute_unrealized_pnl(open_positions, bar)
        used_margin = self.margin_model.total_used_margin(open_positions)
        self.account_ledger.update_equity(unrealized, used_margin)
        self.account_ledger.record_bar(bar.timestamp, len(open_positions))

        # ── 8. Kiểm tra margin call ──
        self._check_margin_call(bar)

        return {"events": events_this_bar}

    # ── Internal processing steps ─────────────────────────────────

    def _process_sl_tp(self, bar: BarOHLC) -> list[dict]:
        """Kiểm tra SL/TP cho tất cả positions đang mở."""
        events = []
        open_positions = self.position_manager.get_all_open_positions()
        hit_events = self.sl_tp_handler.check_all(open_positions, bar,
                                                   bar.timestamp, bar.bar_index)

        for ev in hit_events:
            pos = ev["position"]
            reason = ev["reason"]
            exit_price = ev["exit_price"]

            # Tính slippage cho exit
            slippage = self.slippage_model.get_slippage_price(
                pos.symbol, is_stop_order=(reason == EXIT_SL)
            )
            exit_price = self._apply_exit_slippage(exit_price, pos.direction,
                                                    slippage, is_sl=(reason == EXIT_SL))

            # Commission cho exit
            exit_commission = self.commission_model.calculate_exit_commission(
                pos.symbol, pos.size_lot, exit_price
            )

            # Spread cost cho exit
            spread_price = self.spread_model.get_spread_price(pos.symbol, bar=bar)
            exit_spread_cost = pos.size_lot * self._get_contract_size(pos.symbol) * (spread_price / 2.0)

            # Spread cost đã bao gồm trong entry. Khi close, nếu dùng bid/ask đúng:
            # Long: entry ở ask, exit ở bid → spread được tính từ entry đến exit.
            # Bid/Ask đã có spread, nên additional spread cost khi exit = 0.

            self.trade_recorder.log_decision(
                bar.timestamp, bar.bar_index, pos.order_id,
                DECISION_SL_HIT if reason == EXIT_SL else DECISION_TP_HIT,
                reason=f"{pos.symbol} {pos.direction:+d}",
                details=f"exit_price={exit_price:.5f}"
            )

            # Đóng position
            result = self.position_manager.close_position(
                pos, exit_price, bar.timestamp, bar.bar_index,
                reason, commission=exit_commission,
                additional_spread=0.0,
                slippage_cost=slippage,
            )
            if result:
                self.account_ledger.apply_realized_pnl(
                    result["net_pnl"], pos, bar.timestamp, "CLOSE", reason
                )
                self.account_ledger.apply_commission(
                    exit_commission, bar.timestamp,
                    position_id=pos.position_id, order_id=pos.order_id,
                    reason=f"exit_commission_{reason}"
                )
                self._total_commission += exit_commission
                events.append({"type": reason, "position": pos})

        return events

    def _process_expiry(self, bar: BarOHLC) -> None:
        """Kiểm tra và xử lý pending orders hết hạn."""
        pending = self.order_manager.get_active_orders()
        expired = self.pending_order_handler.check_expiry_all(
            pending, bar.bar_index, bar.timestamp
        )
        for o in expired:
            self.order_manager.expire_order(o)
            self.trade_recorder.log_decision(
                bar.timestamp, bar.bar_index, o.order_id,
                DECISION_ORDER_EXPIRED,
                reason=f"valid_until_bar={o.valid_until_bar}",
            )

    def _process_cancel_intents(self, intents: list[dict]) -> None:
        """Xử lý cancel/modify intents từ Strategy Layer."""
        for intent in intents:
            action = intent.get("action", "")
            if action == "CANCEL_ORDER":
                setup_id = intent.get("setup_id", "")
                orders = self.order_manager.get_orders_by_setup(setup_id)
                for o in orders:
                    if o.status in (ORDER_PENDING, ORDER_ACCEPTED):
                        self.order_manager.cancel_order(o, reason="strategy_cancel")
                        self.trade_recorder.log_decision(
                            self.current_timestamp, self.current_bar_index,
                            o.order_id, DECISION_ORDER_CANCELLED,
                            reason=f"strategy_cancel_setup={setup_id}"
                        )
            elif action == "MODIFY_ORDER":
                # V1: không hỗ trợ modify
                pass

    def _process_pending_fills(self, bar: BarOHLC) -> list[dict]:
        """Kiểm tra fill cho pending limit/stop orders."""
        events = []
        pending = self.order_manager.get_active_orders()

        for order in pending:
            if order.order_type in (ORDER_TYPE_MARKET,):
                continue  # Market orders handled in new intents

            filled, fill_price, reason = self.fill_model.check_fill(order, bar,
                                                                     bar.bar_index)
            if filled:
                self._fill_order(order, fill_price, bar)
                events.append({"type": "fill", "order": order})

        return events

    def _process_new_intents(self, intents: list[dict], bar: BarOHLC) -> None:
        """Xử lý order intents mới từ Strategy Layer."""
        for intent in intents:
            action = intent.get("action", "")
            if action == "PLACE_ORDER":
                self._process_place_order(intent, bar)

    def _process_place_order(self, intent: dict, bar: BarOHLC) -> Optional[Order]:
        """Xử lý một PLACE_ORDER intent."""
        # Parse intent
        symbol = intent.get("symbol", "")
        direction = int(intent.get("direction", 0))
        order_type = intent.get("order_type", ORDER_TYPE_MARKET)
        entry_price = float(intent.get("entry_price", 0))
        sl_price = float(intent.get("sl_price", 0))
        tp_price = float(intent.get("tp_price", 0))
        risk_pct = float(intent.get("risk_pct", 0))
        setup_id = intent.get("setup_id", "")
        valid_until = int(intent.get("valid_until", 0))
        timestamp = self.current_timestamp
        bar_index = self.current_bar_index

        # ── Kiểm tra position conflict (V1: 1 position/symbol) ──
        if not self.config.position.allow_hedging:
            existing = self.position_manager.get_open_position(symbol)
            if existing:
                # Có position cùng symbol → reject order
                self.trade_recorder.log_decision(
                    timestamp, bar_index, "",
                    DECISION_ORDER_REJECTED,
                    reason=f"position_exists:{symbol}",
                    details=f"existing_pos={existing.position_id}"
                )
                return None

        # ── Kiểm tra max total positions ──
        open_count = len(self.position_manager.get_all_open_positions())
        if open_count >= self.config.position.max_total_positions:
            self.trade_recorder.log_decision(
                timestamp, bar_index, "",
                DECISION_ORDER_REJECTED,
                reason="max_total_positions",
                details=f"open={open_count}_max={self.config.position.max_total_positions}"
            )
            return None

        # ── Kiểm tra daily loss limit ──
        if self._daily_loss_triggered:
            self.trade_recorder.log_decision(
                timestamp, bar_index, "",
                DECISION_ORDER_REJECTED,
                reason="daily_loss_limit_hit",
            )
            return None

        # ── Position sizing ──
        equity = self.account_ledger.account.equity
        lots, sizing_error = self.position_sizing.calculate_lots(
            equity, risk_pct, entry_price, sl_price, symbol
        )
        if sizing_error:
            self.trade_recorder.log_decision(
                timestamp, bar_index, "",
                DECISION_ORDER_REJECTED,
                reason=sizing_error,
                details=f"entry={entry_price}_sl={sl_price}_risk={risk_pct}"
            )
            return None

        # ── Margin check ──
        specs = self.symbol_specs.get(symbol, {})
        margin_req = self.margin_model.required_margin(lots, entry_price, symbol=symbol)
        free_margin = self.account_ledger.account.free_margin
        if margin_req > free_margin:
            self.trade_recorder.log_decision(
                timestamp, bar_index, "",
                DECISION_MARGIN_REJECT,
                reason="insufficient_margin",
                details=f"required={margin_req:.2f}_free={free_margin:.2f}"
            )
            return None

        # ── Tạo order ──
        valid_until_bar = 0
        if valid_until > 0:
            # Convert timestamp to approximate bar
            bar_duration = 15 * 60 * 1000  # 15 minutes in ms
            valid_until_bar = bar_index + max(1, int((valid_until - timestamp) / bar_duration))

        order = self.order_manager.create_order(
            setup_id=setup_id,
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            action="PLACE_ORDER",
            requested_price=entry_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            risk_pct=risk_pct,
            timestamp=timestamp,
            bar_index=bar_index,
            valid_until=valid_until,
            valid_until_bar=valid_until_bar,
        )

        # Accept order
        self.order_manager.accept_order(order)

        self.trade_recorder.log_decision(
            timestamp, bar_index, order.order_id,
            DECISION_ORDER_ACCEPTED,
            reason=f"{order_type}_{direction:+d}@{entry_price}",
            details=f"lot={lots:.2f}_sl={sl_price}_tp={tp_price}"
        )

        # ── Market order: fill ngay ──
        if order_type == ORDER_TYPE_MARKET:
            filled, fill_price, reason = self.fill_model.check_fill(
                order, bar, bar_index
            )
            if filled:
                self._fill_order(order, fill_price, bar)
            else:
                self.order_manager.reject_order(order, "market_order_fill_failed")
                self.trade_recorder.log_decision(
                    timestamp, bar_index, order.order_id,
                    DECISION_ORDER_REJECTED, reason="fill_failed"
                )
                return None

        # ── Limit/Stop order: để pending ──
        # Check if it can fill immediately
        if order_type in (ORDER_TYPE_LIMIT, ORDER_TYPE_STOP):
            filled, fill_price, reason = self.fill_model.check_fill(order, bar, bar_index)
            if filled:
                self._fill_order(order, fill_price, bar)

        return order

    def _fill_order(self, order: Order, fill_price: float, bar: BarOHLC) -> Optional[Position]:
        """Xử lý order đã khớp: tính phí, mở position."""
        symbol = order.symbol
        lots = 0.0

        # Tính lot size từ risk_pct (nếu chưa có)
        if order.size_lot > 0:
            lots = order.size_lot
        else:
            equity = self.account_ledger.account.equity
            lots, _ = self.position_sizing.calculate_lots(
                equity, order.risk_pct, order.requested_price,
                order.stop_loss, symbol
            )
            if lots <= 0:
                self.order_manager.reject_order(order, "position_sizing_failed")
                return None

        order.size_lot = lots

        # Spread cost khi entry
        spread_price = self.spread_model.get_spread_price(symbol, bar=bar)
        contract_size = self._get_contract_size(symbol)
        spread_cost = lots * contract_size * (spread_price / 2.0)

        # Slippage
        slippage_price = self.slippage_model.get_slippage_price(symbol)
        slippage_cost = lots * contract_size * slippage_price

        # Commission khi entry
        entry_commission = self.commission_model.calculate_entry_commission(
            symbol, lots, fill_price
        )

        # Đánh dấu order đã filled
        self.order_manager.fill_order(order, fill_price, bar.timestamp, bar.bar_index)

        self.trade_recorder.log_decision(
            bar.timestamp, bar.bar_index, order.order_id,
            DECISION_ORDER_FILLED,
            reason=f"fill@{fill_price:.5f}",
            details=f"lot={lots:.2f}_sl={order.stop_loss}_tp={order.take_profit}"
        )

        # Mở position
        pos = self.position_manager.open_position(
            order, fill_price, bar.timestamp, bar.bar_index,
            lots, entry_commission, spread_cost
        )
        if pos:
            self.trade_recorder.log_decision(
                bar.timestamp, bar.bar_index, order.order_id,
                DECISION_POSITION_OPENED,
                reason=f"opened_{symbol}_{order.direction:+d}",
                details=f"lot={lots:.2f}_entry={fill_price:.5f}"
            )

            # Ghi commission
            self.account_ledger.apply_commission(
                entry_commission, bar.timestamp,
                position_id=pos.position_id, order_id=order.order_id,
                reason="entry_commission"
            )
            self._total_commission += entry_commission
            self._total_spread_cost += spread_cost
            self._total_slippage_cost += slippage_cost

        return pos

    def _apply_exit_slippage(self, exit_price: float, direction: int,
                              slippage: float, is_sl: bool = True) -> float:
        """Apply slippage cho exit price."""
        if is_sl:
            # SL: long exit at bid, slippage làm giá worse
            if direction == DIRECTION_LONG:
                return exit_price - slippage  # exit thấp hơn (worse)
            else:
                return exit_price + slippage  # exit cao hơn (worse)
        else:
            # TP: similar logic
            if direction == DIRECTION_LONG:
                return exit_price - slippage
            else:
                return exit_price + slippage

    def _update_mae_mfe(self, bar: BarOHLC) -> None:
        """Update MAE/MFE cho positions đang mở."""
        for pos in self.position_manager.get_all_open_positions():
            # Use appropriate price based on direction
            if pos.direction == DIRECTION_LONG:
                current = bar.low_bid  # worst for long
                favorable = bar.high_bid  # best for long
            else:
                current = bar.high_ask  # worst for short
                favorable = bar.low_ask  # best for short

            self.position_manager.update_mae_mfe(pos, current)
            # Also track favorable
            entry = pos.entry_price
            if pos.direction == DIRECTION_LONG:
                adv = entry - current
                fav = favorable - entry
            else:
                adv = current - entry
                fav = entry - favorable
            if adv > pos.max_adverse:
                pos.max_adverse = adv
            if fav > pos.max_favorable:
                pos.max_favorable = fav

    def _check_margin_call(self, bar: BarOHLC) -> None:
        """Kiểm tra margin call và stop out."""
        if not self.config.margin.enabled:
            return

        acct = self.account_ledger.account
        if self.margin_model.check_margin_call(acct.equity, acct.used_margin):
            # Stop out tất cả positions
            open_positions = self.position_manager.get_all_open_positions()
            for pos in open_positions:
                exit_price = bar.close_bid if pos.direction == DIRECTION_LONG else bar.close_ask
                result = self.position_manager.close_position(
                    pos, exit_price, bar.timestamp, bar.bar_index,
                    EXIT_MARGIN_CALL
                )
                if result:
                    self.account_ledger.apply_realized_pnl(
                        result["net_pnl"], pos, bar.timestamp, "CLOSE", EXIT_MARGIN_CALL
                    )
                    self.trade_recorder.log_decision(
                        bar.timestamp, bar.bar_index, pos.order_id,
                        DECISION_POSITION_CLOSED, reason=EXIT_MARGIN_CALL,
                        details=f"margin_level={acct.margin_level:.2f}"
                    )

    def _check_daily_reset(self, bar: BarOHLC) -> None:
        """Kiểm tra và reset daily tracking."""
        # Đơn giản: dùng bar_index để ước lượng ngày
        # Giả sử 96 bars cho 15m timeframe = 1 ngày
        day = bar.bar_index // 96

        if day != self._last_trading_day:
            if self._last_trading_day >= 0:
                self.account_ledger.reset_daily_pnl()
            self._last_trading_day = day
            self._daily_loss_triggered = False

        # Kiểm tra daily loss limit
        max_loss = self.config.account.initial_balance * (
            self.config.risk_limits.max_daily_loss_pct / 100.0
        )
        daily_pnl = -(self.account_ledger.account.balance - self.config.account.initial_balance)
        if daily_pnl >= max_loss and self._last_trading_day >= 0:
            self._daily_loss_triggered = True

    # ── Queries ───────────────────────────────────────────────────

    def get_open_positions(self) -> list[Position]:
        """Lấy tất cả positions đang mở."""
        return self.position_manager.get_all_open_positions()

    def get_account(self):
        """Lấy trạng thái tài khoản hiện tại."""
        return self.account_ledger.account

    # ── Export ────────────────────────────────────────────────────

    def export_csv(self, output_dir: str = ".") -> dict[str, str]:
        """Xuất tất cả CSV output."""
        self.trade_recorder.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        paths = self.trade_recorder.export_all(
            orders=self.order_manager.orders,
            positions=self.position_manager.positions,
            account=self.account_ledger.account,
            ledger=self.account_ledger.ledger,
            equity_curve=self.account_ledger.equity_curve,
        )
        return paths

    # ── Summary ───────────────────────────────────────────────────

    def summarize(self) -> dict:
        """Thống kê kết quả backtest."""
        orders = self.order_manager.orders
        positions = self.position_manager.positions
        closed = [p for p in positions if p.status == "closed"]
        acct = self.account_ledger.account

        total_orders = len(orders)
        filled_orders = sum(1 for o in orders if o.status == ORDER_FILLED)
        rejected = sum(1 for o in orders if o.status == ORDER_REJECTED)
        cancelled = sum(1 for o in orders if o.status == ORDER_CANCELLED)
        expired = sum(1 for o in orders if o.status == ORDER_EXPIRED)

        winning_trades = sum(1 for p in closed if p.net_pnl > 0)
        losing_trades = sum(1 for p in closed if p.net_pnl <= 0)

        total_gross = sum(p.gross_pnl for p in closed)
        total_net = sum(p.net_pnl for p in closed)
        total_commission_paid = sum(p.commission for p in closed)
        total_spread = sum(p.spread_cost for p in closed)

        return {
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "rejected": rejected,
            "cancelled": cancelled,
            "expired": expired,
            "total_positions": len(positions),
            "closed_positions": len(closed),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": winning_trades / max(1, len(closed)) * 100,
            "total_gross_pnl": round(total_gross, 2),
            "total_net_pnl": round(total_net, 2),
            "total_commission": round(total_commission_paid, 2),
            "total_spread_cost": round(total_spread, 2),
            "account_balance": round(acct.balance, 2),
            "account_equity": round(acct.equity, 2),
            "total_realized_pnl": round(acct.realized_pnl, 2),
            "decision_count": len(self.trade_recorder.decisions),
        }

    def _get_contract_size(self, symbol: str) -> float:
        specs = self.symbol_specs.get(symbol, {})
        return specs.get("contract_size", 100000)
