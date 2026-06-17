#!/usr/bin/env python3
"""
verify_backtrader.py — Verification tool: Backtrader vs pipeline execution_core.

Mục đích:
  Cross-verify fill modeling giữa Backtrader broker và execution_core.py
  của pipeline SMC. Dùng V8 Rule A (Swing OB + trend) làm test case.

Cách chạy:
  python verify_backtrader.py

Output:
  - Comparison table: WR, trade count, avg R
  - Chi tiết trade list của mỗi engine
  - Backtrader plot (nếu mở được)
"""

import os, sys, csv, json
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd

# ── Config ────────────────────────────────────────────────────
DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
LAYER1 = Path("layer1_data")
MAX_TRADES_TO_PRINT = 20
COMMISSION_PCT = 0.002  # 0.2%

os.makedirs("output", exist_ok=True)

# Import execution_core từ _backup
sys.path.insert(0, str(Path("_backup")))
from execution_core import OrderIntent, simulate_orders, summarize_trades

# ═══════════════════════════════════════════════════════════════
#  PHASE 1: Load OB data & build OB cache (event-sourced)
# ═══════════════════════════════════════════════════════════════
print("=" * 60)
print("PHASE 1: Loading OB data from layer1_data")
print("=" * 60)

with open(LAYER1 / "objects.csv") as f:
    objects = list(csv.DictReader(f))
with open(LAYER1 / "events.csv") as f:
    raw_events = list(csv.DictReader(f))
with open(LAYER1 / "snapshots.csv") as f:
    snaps = list(csv.DictReader(f))

# Map timestamp → bar_index
ts_to_bi = {}
for s in snaps:
    try:
        ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
    except:
        pass
bi_to_ts = {v: k for k, v in ts_to_bi.items()}

# Gán _bar_index cho mỗi OB (bar mà OB được active từ)
for ob in objects:
    try:
        af = int(ob.get("active_from", 0))
        act_bi = ts_to_bi.get(af, -1)
        if act_bi == -1 and af > 0:
            act_bi = ts_to_bi[sorted(k for k in ts_to_bi if k <= af)[-1]]
        ob["_bar_index"] = act_bi
    except:
        ob["_bar_index"] = -1

# OBs theo bar_index (OB được tạo tại bar nào)
obs_at_bar = defaultdict(list)
for ob in objects:
    bi = ob["_bar_index"]
    if bi >= 0:
        obs_at_bar[bi].append(ob)

ob_by_id = {o.get("object_id", ""): o for o in objects if o.get("object_id", "")}

# Lifecycle events theo bar
lifecycle_by_bar = defaultdict(list)
for e in raw_events:
    if e.get("event_type", "") in ("OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"):
        lifecycle_by_bar[int(e["bar_index"])].append(e)

# Build OB cache: event-sourced → mỗi bar biết OB nào đang active
bar_indices = sorted(ts_to_bi.values())
active_ids = set()
ob_cache = {}
for bi in bar_indices:
    # Add new OBs at this bar
    for ob in obs_at_bar.get(bi, []):
        if ob.get("object_id", ""):
            active_ids.add(ob["object_id"])
    # Remove mitigated/invalidated/expired
    for ev in lifecycle_by_bar.get(bi, []):
        active_ids.discard(ev.get("object_id", ""))
    ob_cache[bi] = [ob_by_id[oid] for oid in active_ids
                    if oid in ob_by_id and bi - ob_by_id[oid].get("_bar_index", 0) <= 200]

# ── V8 Rule A: chỉ lấy Swing OB MỚI tại bar hiện tại ──
ob_signal_map = {}
for bi in bar_indices:
    # Chỉ lấy OBs được tạo TẠI bar này (SWING type + direction)
    new_swing = [ob for ob in obs_at_bar.get(bi, [])
                 if "SWING" in str(ob.get("type", "")).upper()
                 and ob.get("direction") in ("1", "-1")]
    # Chỉ lấy 1 OB đầu tiên
    if new_swing:
        ob = new_swing[0]
        ob_signal_map[bi] = {
            "top": max(float(ob.get("top", 0)), float(ob.get("bottom", 0))),
            "bottom": min(float(ob.get("top", 0)), float(ob.get("bottom", 0))),
            "dir": 1 if ob.get("direction") == "1" else -1,
            "oid": ob.get("object_id", ""),
        }

print(f"  Total OBs: {len(objects)}")
print(f"  Swing OBs: {len([o for o in objects if 'SWING' in str(o.get('type','')).upper()])}")
print(f"  Swing signals (1st per bar): {len(ob_signal_map)}")

# ═══════════════════════════════════════════════════════════════
#  PHASE 2: Load OHLC data
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 2: Loading OHLC data")
print("=" * 60)

df = pd.read_parquet(DATA_PATH)

# Xác định range chứa OB signals
min_date = None
for bi, ts in bi_to_ts.items():
    if bi in ob_signal_map:
        d = pd.to_datetime(ts // 1000, unit="s", utc=True)
        if min_date is None or d < min_date:
            min_date = d

df = df[df["timestamp_utc"] >= (min_date or df["timestamp_utc"].min())].tail(30000).copy()
df.rename(columns={
    "timestamp_utc": "Date", "open": "Open", "high": "High",
    "low": "Low", "close": "Close",
}, inplace=True)
df["Date"] = pd.to_datetime(df["Date"])
df.set_index("Date", inplace=True)

# Map bar_index ↔ DataFrame index
df_indices = {}
ohlc_map = {}
for idx, (_, row) in enumerate(df.iterrows()):
    ts_ms = int(row.name.timestamp() * 1000) if hasattr(row.name, "timestamp") else 0
    bi = ts_to_bi.get(ts_ms, -1)
    if bi >= 0:
        df_indices[bi] = idx
        ohlc_map[idx] = bi

# Build OHLC price dict (for execution_core)
prices = {}
for idx, (_, row) in enumerate(df.iterrows()):
    ts_ms = int(row.name.timestamp() * 1000) if hasattr(row.name, "timestamp") else 0
    bi = ts_to_bi.get(ts_ms, -1)
    if bi >= 0:
        prices[bi] = {"open": float(row["Open"]), "high": float(row["High"]),
                       "low": float(row["Low"]), "close": float(row["Close"])}

print(f"  OHLC bars: {len(df)}")
print(f"  Range: {df.index[0]} → {df.index[-1]}")
print(f"  Mapped bar_indices: {len(ohlc_map)}")

# Compute trend SMA(40)
df["sma40"] = df["Close"].rolling(40).mean()

# ═══════════════════════════════════════════════════════════════
#  PHASE 3: Generate signals (V8 Rule A — Swing OB + trend)
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 3: Generating V8 Rule A signals")
print("=" * 60)

intents = []
signals_generated = 0
for bi, ob in ob_signal_map.items():
    idx = df_indices.get(bi, -1)
    if idx < 0 or idx >= len(df):
        continue

    close = float(df.iloc[idx]["Close"])
    sma40 = float(df.iloc[idx]["sma40"]) if not pd.isna(df.iloc[idx]["sma40"]) else None
    direction = ob["dir"]
    height = max(ob["top"] - ob["bottom"], 0.3)

    # Trend filter: close > SMA(40) for long, close < SMA(40) for short
    if sma40 is None:
        continue
    if direction == 1 and close <= sma40:
        continue
    if direction == -1 and close >= sma40:
        continue

    if direction == 1:  # Bullish OB → LONG at OB top
        entry = ob["top"]
        sl = ob["bottom"] - height * 0.5
        tp = entry + height * 2
    else:  # Bearish OB → SHORT at OB bottom
        entry = ob["bottom"]
        sl = ob["top"] + height * 0.5
        tp = entry - height * 2

    intents.append(OrderIntent(
        setup_id=f"V8_{bi}_{ob['oid']}",
        direction=direction,
        order_type="limit",
        entry_price=round(entry, 2),
        entry_zone_top=ob["top"],
        entry_zone_bottom=ob["bottom"],
        stop_loss=round(sl, 2),
        take_profit=round(tp, 2),
        signal_bar=bi,
        timestamp=bi_to_ts.get(bi, 0),
        valid_until_bar=bi + 150,
        source="V8_RuleA",
    ))
    signals_generated += 1

print(f"  Swing OB signals (pre-trend): {len(ob_signal_map)}")
print(f"  After trend filter: {signals_generated}")
print(f"  Total intents: {len(intents)}")

# ═══════════════════════════════════════════════════════════════
#  PHASE 4: Run execution_core (pipeline reference)
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 4: Running execution_core (pipeline engine)")
print("=" * 60)

pipeline_trades = simulate_orders(intents, prices)
pipeline_summary = summarize_trades(pipeline_trades)

print(f"  Trades (filled): {pipeline_summary['total']}")
print(f"  Wins: {pipeline_summary['wins']}")
print(f"  Losses: {pipeline_summary['losses']}")
print(f"  WR: {pipeline_summary['win_rate']}%")
print(f"  Total R: {pipeline_summary['total_r']}")
print(f"  Avg R: {pipeline_summary['avg_r']}")

# ═══════════════════════════════════════════════════════════════
#  PHASE 5: Run Backtrader
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PHASE 5: Running Backtrader")
print("=" * 60)

import backtrader as bt


class V8SwingOB_BT(bt.Strategy):
    """
    Backtrader V8 Rule A — Swing OB + Trend filter.
    Limit order at OB boundary, SL/TP managed by broker.
    """
    params = (
        ("commission", COMMISSION_PCT),
    )

    def __init__(self):
        # Pre-build signal lookup: DataFrame index → OB info
        self.signal_at_idx = {}
        for bi, ob in ob_signal_map.items():
            idx = df_indices.get(bi, -1)
            if idx < 0 or idx >= len(self.data):
                continue
            # Apply trend filter here too
            try:
                close_val = self.data.close.array[idx] if hasattr(self.data.close, 'array') else None
            except:
                close_val = None
            self.signal_at_idx[idx] = ob

        self.sma40 = bt.ind.SMA(self.data.close, period=40)
        self.trade_log = []

    def next(self):
        i = len(self.data) - 1  # current OHLC index

        if i not in self.signal_at_idx:
            return
        if len(self.data) < 40:
            return

        ob = self.signal_at_idx[i]
        direction = ob["dir"]
        close_val = self.data.close[0]
        sma_val = self.sma40[0]

        # Trend filter
        if direction == 1 and close_val <= sma_val:
            return
        if direction == -1 and close_val >= sma_val:
            return

        height = max(ob["top"] - ob["bottom"], 0.3)

        if direction == 1:
            entry = round(ob["top"], 2)
            sl = round(ob["bottom"] - height * 0.5, 2)
            tp = round(entry + height * 2, 2)
            o = self.buy(exectype=bt.Order.Limit, price=entry, sl=sl, tp=tp, transmit=False)
            self.trade_log.append(("LONG", entry, sl, tp, self.data.num, self.data.datetime.datetime(0)))
        else:
            entry = round(ob["bottom"], 2)
            sl = round(ob["top"] + height * 0.5, 2)
            tp = round(entry - height * 2, 2)
            o = self.sell(exectype=bt.Order.Limit, price=entry, sl=sl, tp=tp, transmit=False)
            self.trade_log.append(("SHORT", entry, sl, tp, self.data.num, self.data.datetime.datetime(0)))


print("  Building Backtrader data feed...")

# Backtrader PandasData feed
data = bt.feeds.PandasData(dataname=df)

cerebro = bt.Cerebro(stdstats=False)
cerebro.addstrategy(V8SwingOB_BT)
cerebro.adddata(data)
cerebro.broker.setcash(100000.0)
cerebro.broker.setcommission(commission=COMMISSION_PCT)
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0)
cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

print("  Running Backtrader...")
bt_results = cerebro.run()
bt_strat = bt_results[0]

# Parse Backtrader TradeAnalyzer
bt_ta = bt_strat.analyzers.trades.get_analysis()

bt_trades_total = bt_ta.get("total", {}).get("total", 0)
bt_won = bt_ta.get("won", {}).get("total", 0)
bt_lost = bt_ta.get("lost", {}).get("total", 0)
bt_won_pnl = bt_ta.get("won", {}).get("pnl", {}).get("total", 0)
bt_lost_pnl = bt_ta.get("lost", {}).get("pnl", {}).get("total", 0)
bt_pnl_net = bt_ta.get("pnl", {}).get("net", {}).get("total", 0)

bt_wr = (bt_won / bt_trades_total * 100) if bt_trades_total > 0 else 0.0
bt_pf = abs(bt_won_pnl / bt_lost_pnl) if bt_lost_pnl != 0 else float('inf')

print(f"  Trades: {bt_trades_total}")
print(f"  Wins: {bt_won}")
print(f"  Losses: {bt_lost}")
print(f"  WR: {bt_wr:.1f}%")
print(f"  Profit Factor: {bt_pf:.2f}")
print(f"  Net PnL: ${bt_pnl_net:.2f}")

# Backtrader signals sent
bt_signals_sent = len(bt_strat.trade_log)
print(f"  Signals sent to broker: {bt_signals_sent}")

# ═══════════════════════════════════════════════════════════════
#  PHASE 6: Compare
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("CROSS-VERIFICATION RESULTS")
print("=" * 60)

# Check if close
trades_close = abs(pipeline_summary['total'] - bt_trades_total) <= 5
wr_close = abs(pipeline_summary['win_rate'] - bt_wr) <= 5.0

print(f"""
{'Metric':<25} {'execution_core':<18} {'Backtrader':<18} {'MATCH?':<10}
{'-'*25} {'-'*18} {'-'*18} {'-'*10}
Total Trades       {pipeline_summary['total']:<18} {bt_trades_total:<18} {'✓' if trades_close else '✗':<10}
Wins               {pipeline_summary['wins']:<18} {bt_won:<18} {'✓' if abs(pipeline_summary['wins'] - bt_won) <= 5 else '✗':<10}
Losses             {pipeline_summary['losses']:<18} {bt_lost:<18} {'✓' if abs(pipeline_summary['losses'] - bt_lost) <= 5 else '✗':<10}
Win Rate [%]       {pipeline_summary['win_rate']:<18.1f} {bt_wr:<18.1f} {'✓' if wr_close else '✗':<10}
Total R            {pipeline_summary['total_r']:<18.2f} {'N/A (USD)':<18} {'—':<10}
Avg R              {pipeline_summary['avg_r']:<18.2f} {'N/A':<18} {'—':<10}
Profit Factor      {'N/A':<18} {bt_pf:<18.2f} {'—':<10}
""")

# ── Detailed trades ──
print("\n--- Pipeline Trades (first {}):".format(MAX_TRADES_TO_PRINT))
print(f"{'ID':<8} {'Dir':<4} {'Entry':<8} {'Exit':<8} {'R':<8} {'Reason':<10}")
print("-" * 56)
for t in pipeline_trades[:MAX_TRADES_TO_PRINT]:
    d = "L" if t.direction == 1 else "S"
    print(f"{t.setup_id:<8} {d:<4} {t.fill_price:<8.2f} {t.exit_price:<8.2f} {t.net_r:<+8.2f} {t.exit_reason:<10}")
if len(pipeline_trades) > MAX_TRADES_TO_PRINT:
    print(f"  ... and {len(pipeline_trades) - MAX_TRADES_TO_PRINT} more")

print(f"\n  Pipeline total: {pipeline_summary['total']} trades | WR: {pipeline_summary['win_rate']}% | Total R: {pipeline_summary['total_r']:.2f}")

# Backtrader signals log
print(f"\n--- Backtrader signals sent (first {MAX_TRADES_TO_PRINT}):")
if bt_strat.trade_log:
    print(f"{'Dir':<6} {'Entry':<10} {'SL':<10} {'TP':<10} {'Bar#':<6} {'DateTime':<20}")
    print("-" * 66)
    for tr in bt_strat.trade_log[:MAX_TRADES_TO_PRINT]:
        d, entry, sl, tp, bn, dt = tr
        print(f"{d:<6} {entry:<10.2f} {sl:<10.2f} {tp:<10.2f} {bn:<6} {str(dt):<20}")
    if len(bt_strat.trade_log) > MAX_TRADES_TO_PRINT:
        print(f"  ... and {len(bt_strat.trade_log) - MAX_TRADES_TO_PRINT} more")

# ═══════════════════════════════════════════════════════════════
#  ANALYSIS
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("ANALYSIS")
print("=" * 60)

pipe_signal_bars = set(t.signal_bar for t in pipeline_trades)
fill_rate = len(pipeline_trades) / signals_generated * 100 if signals_generated else 0
print(f"  Signals generated: {signals_generated}")
print(f"  Pipeline filled: {len(pipeline_trades)} ({fill_rate:.1f}%)")
print(f"  Backtrader filled: {bt_trades_total}")
print(f"  Signals not in OHLC range: {len(ob_signal_map) - signals_generated}")

if not trades_close:
    print("\n  ⚠️  Trade count mismatch — possible causes:")
    print("     1. Backtrader fills limit orders differently (exact price)")
    print("     2. Pipeline checks low/high touch; Backtrader uses OHLC-based fill model")
    print("     3. SL/TP execution timing: Backtrader can fill before bar close")
    print("     4. Commission model: execution_core embeds cost in price; Backtrader deducts cash")

if not wr_close:
    print("\n  ⚠️  Win rate mismatch — possible causes:")
    print("     1. Different SL/TP trigger logic (intra-bar vs bar-level)")
    print("     2. Different fill price (cost-adjusted vs raw)")

# ═══════════════════════════════════════════════════════════════
#  SAVE
# ═══════════════════════════════════════════════════════════════
output_data = {
    "pipeline": {
        "total": pipeline_summary["total"],
        "wins": pipeline_summary["wins"],
        "losses": pipeline_summary["losses"],
        "win_rate": pipeline_summary["win_rate"],
        "total_r": pipeline_summary["total_r"],
        "avg_r": pipeline_summary["avg_r"],
    },
    "backtrader": {
        "total": bt_trades_total,
        "wins": bt_won,
        "losses": bt_lost,
        "win_rate": round(bt_wr, 1),
        "net_pnl": round(bt_pnl_net, 2),
    },
    "config": {
        "data": DATA_PATH,
        "commission": COMMISSION_PCT,
        "signals": signals_generated,
    }
}

with open("output/verify_backtrader.json", "w") as f:
    json.dump(output_data, f, indent=2)
print(f"\n[✓] Results saved → output/verify_backtrader.json")

# Try plot
try:
    cerebro.plot(style='candlestick', volume=False, iplot=False)
    print("[✓] Plot generated")
except Exception as e:
    print(f"  Plot note: {e}")

print("\n" + "=" * 60)
print("DONE — verify_backtrader.py")
print("=" * 60)
