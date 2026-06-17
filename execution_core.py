#!/usr/bin/env python3
"""
execution_core.py — Fill, SL/TP, Cost model tối giản.
Generic: không biết OB, SMC, CHOCH, gì hết.
Chỉ biết order -> price -> bar -> spread -> PnL.
"""
from dataclasses import dataclass, field
from typing import Optional


# ── Order Intent (generic, không SMC) ─────────────────────────
@dataclass
class OrderIntent:
    setup_id: str
    direction: int           # 1 = long, -1 = short
    order_type: str          # "market" / "limit"
    entry_price: float
    entry_zone_top: float    # OB top / zone biên trên
    entry_zone_bottom: float # OB bottom / zone biên dưới
    stop_loss: float
    take_profit: float
    signal_bar: int          # bar_index khi signal được tạo
    timestamp: int
    valid_until_bar: int     # max bar chờ fill trước khi expired
    source: str = ""         # model name / reason


@dataclass
class TradeRecord:
    setup_id: str
    direction: int
    signal_bar: int
    fill_bar: int
    fill_price: float
    exit_bar: int
    exit_price: float
    exit_reason: str         # SL_HIT / TP_HIT / EXPIRED / TIMEOUT / OPEN
    gross_r: float
    net_r: float
    holding_bars: int
    source: str = ""


# ── Cost functions ────────────────────────────────────────────
COST_SPREAD = 0.30
COST_SLIPPAGE = 0.10

def entry_cost(direction: int, raw_price: float) -> float:
    """LONG pay ask, SHORT receive bid."""
    half = COST_SPREAD / 2 + COST_SLIPPAGE
    return raw_price + half if direction == 1 else raw_price - half

def exit_cost(direction: int, raw_price: float) -> float:
    """LONG receive bid, SHORT pay ask."""
    half = COST_SPREAD / 2 + COST_SLIPPAGE
    return raw_price - half if direction == 1 else raw_price + half


# ── Fill & SL/TP simulation ──────────────────────────────────
MAX_FILL_WAIT = 150  # bars to wait for limit fill
MAX_HOLD = 200       # bars to hold after fill

def simulate_orders(
    intents: list[OrderIntent],
    prices: dict[int, dict],   # {bar_index: {"open","high","low","close"}}
    max_fill_wait: int = MAX_FILL_WAIT,
    max_hold: int = MAX_HOLD,
) -> list[TradeRecord]:
    """Simulate all intents bar-by-bar.

    Args:
        intents: list of OrderIntent from strategy
        prices: OHLC dict keyed by bar_index

    Returns:
        list of TradeRecord
    """
    trades: list[TradeRecord] = []

    for intent in intents:
        direction = intent.direction
        order_type = intent.order_type
        raw_entry = intent.entry_price
        sl_raw = intent.stop_loss
        tp_raw = intent.take_profit
        signal_bar = intent.signal_bar
        valid_until = intent.valid_until_bar

        # ── Phase 1: find fill ──
        fill_bar = None
        max_look = min(max_fill_wait, valid_until - signal_bar if valid_until > signal_bar else max_fill_wait)

        if order_type == "market":
            fill_bar = signal_bar + 1  # fill at next bar open
        else:
            # limit order
            for offset in range(1, max_look + 1):
                bi = signal_bar + offset
                bar = prices.get(bi)
                if not bar:
                    break
                if direction == 1 and bar["low"] <= raw_entry:
                    fill_bar = bi
                    break
                if direction == -1 and bar["high"] >= raw_entry:
                    fill_bar = bi
                    break

        if fill_bar is None:
            # unfilled — skip
            continue

        # ── Phase 2: cost-adjusted prices ──
        entry_px = entry_cost(direction, raw_entry)
        sl_px = exit_cost(direction, sl_raw)
        tp_px = exit_cost(direction, tp_raw)
        risk = abs(entry_px - sl_px)
        if risk <= 0:
            risk = 1.0

        # ── Phase 3: scan bars for SL/TP ──
        result = None
        exit_bar = fill_bar
        exit_price = entry_px
        r_mult = 0.0

        for offset in range(0, max_hold + 1):
            bi = fill_bar + offset
            bar = prices.get(bi)
            if not bar:
                result = "OPEN"
                break
            if direction == 1:
                if bar["low"] <= sl_px:
                    result = "SL_HIT"
                    exit_bar = bi
                    exit_price = sl_px
                    r_mult = -1.0
                    break
                if bar["high"] >= tp_px:
                    result = "TP_HIT"
                    exit_bar = bi
                    exit_price = tp_px
                    r_mult = abs(tp_px - entry_px) / risk
                    break
            else:
                if bar["high"] >= sl_px:
                    result = "SL_HIT"
                    exit_bar = bi
                    exit_price = sl_px
                    r_mult = -1.0
                    break
                if bar["low"] <= tp_px:
                    result = "TP_HIT"
                    exit_bar = bi
                    exit_price = tp_px
                    r_mult = abs(tp_px - entry_px) / risk
                    break
        else:
            # Timeout
            result = "TIMEOUT"
            exit_bar = fill_bar + max_hold
            last_bar = prices.get(exit_bar)
            if last_bar:
                exit_px = exit_cost(direction, last_bar["close"])
                if direction == 1:
                    r_mult = (exit_px - entry_px) / risk
                else:
                    r_mult = (entry_px - exit_px) / risk
            else:
                r_mult = -1.0

        trades.append(TradeRecord(
            setup_id=intent.setup_id,
            direction=direction,
            signal_bar=signal_bar,
            fill_bar=fill_bar,
            fill_price=round(entry_px, 2),
            exit_bar=exit_bar,
            exit_price=round(exit_price, 2),
            exit_reason=result or "UNKNOWN",
            gross_r=round(r_mult, 4),
            net_r=round(r_mult, 4),  # cost already in entry/exit prices
            holding_bars=exit_bar - fill_bar,
            source=intent.source,
        ))

    return trades


# ── Summary ──────────────────────────────────────────────────
def summarize_trades(trades: list[TradeRecord]) -> dict:
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_r": 0, "avg_r": 0, "open": 0, "timeouts": 0}

    closed = [t for t in trades if t.exit_reason in ("SL_HIT", "TP_HIT", "TIMEOUT")]
    wins = [t for t in closed if t.net_r > 0]
    losses = [t for t in closed if t.net_r <= 0]
    open_trades = [t for t in trades if t.exit_reason == "OPEN"]
    timeout_trades = [t for t in trades if t.exit_reason == "TIMEOUT"]

    total_r = sum(t.net_r for t in closed)
    n_closed = len(closed)

    return {
        "total": len(trades),
        "fills": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "open": len(open_trades),
        "timeouts": len(timeout_trades),
        "win_rate": round(len(wins) / n_closed * 100, 1) if n_closed > 0 else 0,
        "total_r": round(total_r, 2),
        "avg_r": round(total_r / n_closed, 2) if n_closed > 0 else 0,
    }
