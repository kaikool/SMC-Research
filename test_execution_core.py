#!/usr/bin/env python3
"""Unit tests cho execution_core — fill, SL/TP, cost."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)

from execution_core import OrderIntent, simulate_orders, summarize_trades, entry_cost, exit_cost

# ── Fake prices helper ───────────────────────────────────────
def make_prices(ohlc_list, start_bar=0):
    """ohlc_list: list of (open, high, low, close).
       First bar is always dummy (no trade signal), rest are real bars."""
    return {start_bar + i: {"open": o, "high": h, "low": l, "close": c}
            for i, (o, h, l, c) in enumerate(ohlc_list)}

D = (100, 100, 100, 100)  # dummy bar

def test_fill_long_limit():
    """limit LONG khớp khi low <= entry"""
    prices = make_prices([D, (100, 102, 99, 101)], 50)
    intent = OrderIntent(setup_id="T1", direction=1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=98, take_profit=105, signal_bar=50, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1, f"got {len(trades)}"
    assert trades[0].fill_bar == 51
    print("✅ test_fill_long_limit PASS")

def test_fill_long_no_fill():
    """limit LONG không khớp khi low > entry"""
    prices = make_prices([D, (100, 102, 101, 101)], 50)
    intent = OrderIntent(setup_id="T2", direction=1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=98, take_profit=105, signal_bar=50, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 0
    print("✅ test_fill_long_no_fill PASS")

def test_tp_hit():
    """LONG TP hit khi high >= TP"""
    prices = make_prices([D, (101, 104, 100, 103)])
    intent = OrderIntent(setup_id="T3", direction=1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=98, take_profit=102, signal_bar=0, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1
    assert trades[0].exit_reason == "TP_HIT"
    assert trades[0].net_r > 0
    print("✅ test_tp_hit PASS")

def test_sl_hit():
    """LONG SL hit khi low <= cost-adjusted SL"""
    prices = make_prices([D, (100, 101, 97, 98)])
    intent = OrderIntent(setup_id="T4", direction=1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=99, take_profit=105, signal_bar=0, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1
    assert trades[0].exit_reason == "SL_HIT"
    assert trades[0].net_r <= 0
    print("✅ test_sl_hit PASS")

def test_sl_before_tp_same_bar():
    """Cùng bar chạm SL trước TP → SL thắng (conservative)"""
    prices = make_prices([D, (100, 105, 97, 102)])
    intent = OrderIntent(setup_id="T5", direction=1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=98, take_profit=104, signal_bar=0, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1
    assert trades[0].exit_reason == "SL_HIT", f"got {trades[0].exit_reason}"
    print("✅ test_sl_before_tp_same_bar PASS")

def test_short_tp_hit():
    """SHORT TP hit khi low <= cost-adjusted TP"""
    prices = make_prices([D, (100, 101, 97, 98)])
    intent = OrderIntent(setup_id="T6", direction=-1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=103, take_profit=97, signal_bar=0, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1
    assert trades[0].exit_reason == "TP_HIT", f"got {trades[0].exit_reason}"
    assert trades[0].net_r > 0
    print("✅ test_short_tp_hit PASS")

def test_short_sl_hit():
    """SHORT SL hit khi high >= cost-adjusted SL"""
    prices = make_prices([D, (100, 104, 99, 103)])
    intent = OrderIntent(setup_id="T6b", direction=-1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=102, take_profit=96, signal_bar=0, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1
    assert trades[0].exit_reason == "SL_HIT", f"got {trades[0].exit_reason}"
    print("✅ test_short_sl_hit PASS")

def test_expired():
    """Pending order expired nếu valid_until quá hạn"""
    prices = make_prices([D] + [(100, 102, 101, 101)] * 15)
    intent = OrderIntent(setup_id="T7", direction=1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=98, take_profit=105, signal_bar=0, timestamp=0,
        valid_until_bar=5, source="test")  # chỉ cho phép 5 bar
    trades = simulate_orders([intent], prices, max_fill_wait=20, max_hold=50)
    assert len(trades) == 0, f"Expected 0 (expired), got {len(trades)}"
    print("✅ test_expired PASS")

def test_cost_reduces_r():
    """Cost applied to both entry and exit — verify fill_price includes cost"""
    prices = make_prices([D, (100, 104, 98, 102)])
    intent = OrderIntent(setup_id="T8", direction=1, order_type="limit",
        entry_price=100, entry_zone_top=101, entry_zone_bottom=99,
        stop_loss=97, take_profit=104, signal_bar=0, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1
    assert trades[0].exit_reason == "TP_HIT", f"got {trades[0].exit_reason}"
    assert trades[0].net_r > 0
    # fill_price should be entry + cost for LONG
    assert trades[0].fill_price > 100, f"fill_price={trades[0].fill_price} should > 100"
    print(f"✅ test_cost_reduces_r PASS (fill={trades[0].fill_price:.2f}, R={trades[0].net_r:.2f})")

def test_market_order():
    """Market order fill at next bar"""
    prices = make_prices([D, (102, 103, 101, 102)], 10)
    intent = OrderIntent(setup_id="T9", direction=1, order_type="market",
        entry_price=0, entry_zone_top=0, entry_zone_bottom=0,
        stop_loss=99, take_profit=105, signal_bar=10, timestamp=0,
        valid_until_bar=99, source="test")
    trades = simulate_orders([intent], prices, max_fill_wait=10, max_hold=50)
    assert len(trades) == 1, f"got {len(trades)}"
    assert trades[0].fill_bar == 11
    print("✅ test_market_order PASS")

def test_summarize():
    """Summary function tính toán đúng"""
    from execution_core import TradeRecord
    trades = [
        TradeRecord("W", 1, 0, 1, 100, 2, 105, "TP_HIT", 2.0, 2.0, 1, "test"),
        TradeRecord("L", 1, 0, 1, 100, 2, 99, "SL_HIT", -1.0, -1.0, 1, "test"),
        TradeRecord("O", 1, 0, 1, 100, 0, 100, "OPEN", 0.0, 0.0, 0, "test"),
    ]
    s = summarize_trades(trades)
    assert s["wins"] == 1
    assert s["losses"] == 1
    assert s["open"] == 1
    assert s["win_rate"] == 50.0
    print("✅ test_summarize PASS")

if __name__ == "__main__":
    test_fill_long_limit()
    test_fill_long_no_fill()
    test_tp_hit()
    test_sl_hit()
    test_sl_before_tp_same_bar()
    test_short_tp_hit()
    test_short_sl_hit()
    test_expired()
    test_cost_reduces_r()
    test_market_order()
    test_summarize()
    print("\n🎯 ALL 11 execution_core tests PASSED")
