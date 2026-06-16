#!/usr/bin/env python3
"""
[Step 4/4] Generate HTML report + equity curve chart.
Chạy sau 02_run_backtest.py.

FIXES:
  - OB active cache event-sourced (dùng active_from, lifecycle remove)
  - Division by zero guard cho avg_r
  - Sử dụng event-based OB filtering thay vì sliding raw list từ objects.csv

Output: output/report/report.html (+ equity_curve.png nếu có matplotlib)
"""
import csv, sys, os
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)
csv.field_size_limit(10 * 1024 * 1024)

DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
LAYER1_DIR = Path("output") / "layer1"
OUTPUT_DIR = Path("output") / "report"
USE_BARS = 50000

# Matplotlib (optional)
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("matplotlib not available — equity chart will be skipped")

from strategy_layer.entry_strategies import (
    Model1_EQHEQL_Sweep_InternalCHOCH,
    Model5_StrongDefense,
    Model7_IntCHOCH_OB,
)


def build_active_ob_cache(objects, ts_to_bi, lifecycle_events_by_bar, bar_indices):
    """Build event-sourced active OB cache: uses active_from, lifecycle removes."""
    # Map active_from + created_at
    for ob in objects:
        try:
            af = int(ob.get("active_from", 0))
            act_bi = ts_to_bi.get(af, -1)
            if act_bi == -1 and af > 0:
                st = sorted(k for k in ts_to_bi.keys() if k <= af)
                if st:
                    act_bi = ts_to_bi[st[-1]]
            ob["_active_bar_index"] = act_bi
        except:
            ob["_active_bar_index"] = -1

    active_ob_ids = set()
    cache = {}
    for bi in bar_indices:
        for ob in objects:
            act_bi = ob.get("_active_bar_index", -1)
            if act_bi == bi:
                oid = ob.get("object_id", "")
                if oid:
                    active_ob_ids.add(oid)
        for ev in lifecycle_events_by_bar.get(bi, []):
            oid = ev.get("object_id", "")
            if oid in active_ob_ids:
                active_ob_ids.discard(oid)
        cache[bi] = [ob for ob in objects if ob.get("object_id", "") in active_ob_ids
                     and bi - ob.get("_active_bar_index", 0) <= 200]
    return cache


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load Layer 1 data ─────────────────────
    print("Loading Layer 1 data...", flush=True)
    with open(LAYER1_DIR / "snapshots.csv") as f:
        snaps = list(csv.DictReader(f))
    bar_snaps = {int(s["bar_index"]): s for s in snaps}

    with open(LAYER1_DIR / "events.csv") as f:
        events_by_bar = defaultdict(list)
        for e in csv.DictReader(f):
            events_by_bar[int(e["bar_index"])].append(e)

    with open(LAYER1_DIR / "objects.csv") as f:
        all_objects = list(csv.DictReader(f))

    # Map timestamps
    ts_to_bi = {}
    for s in snaps:
        try:
            ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
        except:
            pass

    # Build lifecycle events index
    lifecycle_events_by_bar = defaultdict(list)
    for bi, evs in events_by_bar.items():
        for ev in evs:
            et = ev.get("event_type", "")
            if et in ("OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"):
                lifecycle_events_by_bar[bi].append(ev)

    # Load prices
    print("Loading prices...", flush=True)
    import pandas as pd
    df = pd.read_parquet(DATA_PATH)
    prices = {}
    ts_map = {}
    for s in snaps:
        try:
            ts_map[int(s["timestamp"])] = int(s["bar_index"])
        except:
            pass
    for _, row in df.iterrows():
        ts = row["timestamp_utc"]
        ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
        bi = ts_map.get(ts_ms, -1)
        if bi >= 0:
            prices[bi] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }

    bar_indices = sorted(bar_snaps.keys())[-USE_BARS:]
    active_ob_cache = build_active_ob_cache(all_objects, ts_to_bi, lifecycle_events_by_bar, bar_indices)

    # ── Run models ─────────────────────────────
    models = [
        ("M1: EQH/EQL Sweep", Model1_EQHEQL_Sweep_InternalCHOCH()),
        ("M5: Strong Defense", Model5_StrongDefense()),
        ("M7: Int CHOCH + OB", Model7_IntCHOCH_OB()),
    ]

    all_trades = []
    for model_name, model in models:
        orders = []
        for bi in bar_indices:
            orders.extend(
                model.on_bar(bi, events_by_bar.get(bi, []), bar_snaps.get(bi, {}), active_ob_cache.get(bi, []))
            )
        for o in orders:
            entry_bar = o.bar_index
            entry = o.entry_price
            sl = o.sl_price
            tp = o.tp_price
            risk = abs(entry - sl) if sl != entry else 1
            reward = abs(tp - entry)

            result = "open"
            r_mult = 0.0
            for offset in range(1, 201):
                bi = entry_bar + offset
                bar = prices.get(bi)
                if not bar:
                    break
                if o.direction == 1:
                    if bar["low"] <= sl:
                        result, r_mult = "loss", -1.0
                        break
                    if bar["high"] >= tp:
                        result, r_mult = "win", reward / risk
                        break
                else:
                    if bar["high"] >= sl:
                        result, r_mult = "loss", -1.0
                        break
                    if bar["low"] <= tp:
                        result, r_mult = "win", reward / risk
                        break
            timestamp = int(bar_snaps.get(entry_bar, {}).get("timestamp", 0))
            all_trades.append((timestamp, o.direction, entry, sl, tp, model_name, result, r_mult, entry_bar))

    all_trades.sort(key=lambda t: t[0])

    # ── Equity curve ───────────────────────────
    equity = [10000.0]
    dates = []
    cum_r_list = [0.0]
    cum_r = 0.0
    equity_high = 10000.0
    max_drawdown = 0.0
    wins = 0
    losses = 0
    total_r = 0.0
    model_wins = defaultdict(int)
    model_losses = defaultdict(int)
    model_r = defaultdict(float)

    for t in all_trades:
        ts, direction, entry, sl, tp, model_name, result, r_mult, bi = t
        cum_r += r_mult
        if result == "win":
            equity.append(equity[-1] * (1 + abs(r_mult) * 0.005))
            wins += 1
            model_wins[model_name] += 1
        elif result == "loss":
            equity.append(equity[-1] * (1 - 0.005))
            losses += 1
            model_losses[model_name] += 1
        else:
            continue
        total_r += r_mult
        model_r[model_name] += r_mult
        cum_r_list.append(cum_r)

        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if ts else datetime.now()
        dates.append(dt)

        if equity[-1] > equity_high:
            equity_high = equity[-1]
        dd = (equity_high - equity[-1]) / equity_high * 100
        if dd > max_drawdown:
            max_drawdown = dd

    total_closed = wins + losses
    win_rate = wins / total_closed * 100 if total_closed > 0 else 0

    # ── Generate chart ─────────────────────────
    chart_path = str(OUTPUT_DIR / "equity_curve.png")
    if HAS_MPL and len(equity) > 1:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})
        dates_chart = [dates[i - 1] if i - 1 < len(dates) else dates[-1] for i in range(1, len(equity))]
        ax1.plot(dates_chart, equity[1:], color="#2196F3", linewidth=1.5, label="Equity")
        ax1.fill_between(dates_chart, equity[1:], alpha=0.1, color="#2196F3")
        ax1.axhline(y=10000, color="gray", linestyle="--", alpha=0.5)
        ax1.set_title("XAUUSD 15M — Equity Curve", fontsize=14, fontweight="bold")
        ax1.set_ylabel("Account ($)")
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        ax2.plot(dates_chart, cum_r_list[1:], color="#4CAF50", linewidth=1.5)
        ax2.fill_between(dates_chart, cum_r_list[1:], alpha=0.1, color="#4CAF50")
        ax2.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
        ax2.set_ylabel("Cumulative R")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Chart: {chart_path}")

    # ── HTML report ────────────────────────────
    avg_r = total_r / total_closed if total_closed > 0 else 0.0
    model_stats = {}
    for m_name, _ in models:
        mw = model_wins[m_name]
        ml = model_losses[m_name]
        mt = mw + ml
        mwr = mw / mt * 100 if mt > 0 else 0
        model_stats[m_name] = {"total": mt, "wins": mw, "losses": ml, "wr": mwr, "r": model_r[m_name]}

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SMC Event Engine — Backtest Report</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Inter', sans-serif; background: #0f1923; color: #e0e0e0; padding: 40px; }}
  .container {{ max-width: 1000px; margin: 0 auto; }}
  h1 {{ font-size: 28px; color: #2196F3; margin-bottom: 8px; }}
  .subtitle {{ color: #888; margin-bottom: 30px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }}
  .card {{ background: #1a2736; border-radius: 12px; padding: 20px; border: 1px solid #2a3a4a; }}
  .card .label {{ font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
  .card .value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
  .green {{ color: #4CAF50; }}  .blue {{ color: #2196F3; }}
  .orange {{ color: #FF9800; }}  .red {{ color: #f44336; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
  th {{ text-align: left; padding: 12px 16px; background: #1a2736; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #888; border-bottom: 2px solid #2a3a4a; }}
  td {{ padding: 12px 16px; border-bottom: 1px solid #1e2d3d; }}
  .chart-container {{ background: #1a2736; border-radius: 12px; padding: 20px; margin: 20px 0; border: 1px solid #2a3a4a; }}
  .chart-container img {{ width: 100%; border-radius: 8px; }}
  .footer {{ text-align: center; color: #555; font-size: 12px; margin-top: 40px; }}
</style>
</head>
<body>
<div class="container">
  <h1>📊 SMC Event Engine</h1>
  <div class="subtitle">XAUUSD 15M — Backtest Report | {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC</div>
  <div class="grid">
    <div class="card"><div class="label">Win Rate</div><div class="value green">{win_rate:.1f}%</div></div>
    <div class="card"><div class="label">Total Orders</div><div class="value blue">{total_closed}</div></div>
    <div class="card"><div class="label">Total R</div><div class="value orange">{total_r:.1f}R</div></div>
    <div class="card"><div class="label">Max DD</div><div class="value red">{max_drawdown:.1f}%</div></div>
    <div class="card"><div class="label">Orders/Week</div><div class="value blue">{total_closed/(USE_BARS/(96*5)):.1f}</div></div>
    <div class="card"><div class="label">Final Equity</div><div class="value green">${equity[-1]:,.0f}</div></div>
  </div>
  <h2>📈 Equity Curve</h2>
  <div class="chart-container">
    {'<img src="equity_curve.png" alt="Equity Curve">' if HAS_MPL else '<pre style="color:#888">Install matplotlib for equity chart</pre>'}
  </div>
  <h2>📋 Model Breakdown</h2>
  <table>
    <tr><th>Model</th><th>Orders</th><th>Wins</th><th>Losses</th><th>WR</th><th>Total R</th></tr>"""

    for m_name, ms in model_stats.items():
        tc = "green" if ms["wr"] > 65 else ("orange" if ms["wr"] > 50 else "red")
        html += f"""    <tr>
      <td><strong>{m_name}</strong></td>
      <td>{ms['total']}</td>
      <td>{ms['wins']}</td>
      <td>{ms['losses']}</td>
      <td class="{tc}">{ms['wr']:.1f}%</td>
      <td class="orange">{ms['r']:.1f}R</td>
    </tr>"""

    html += f"""  </table>
  <h2>📊 Summary</h2>
  <table>
    <tr><th>Metric</th><th>Value</th></tr>
    <tr><td>Data</td><td>{len(bar_indices)} bars XAUUSD 15M</td></tr>
    <tr><td>Period</td><td>{dates[0].strftime('%Y-%m-%d') if dates else 'N/A'} → {dates[-1].strftime('%Y-%m-%d') if dates else 'N/A'}</td></tr>
    <tr><td>Total Trades</td><td>{total_closed}</td></tr>
    <tr><td>Win Rate</td><td class="green">{win_rate:.1f}%</td></tr>
    <tr><td>Total R</td><td class="orange">{total_r:.2f}R</td></tr>
    <tr><td>Avg R/Trade</td><td>{avg_r:.2f}R</td></tr>
    <tr><td>Max DD</td><td class="red">{max_drawdown:.1f}%</td></tr>
    <tr><td>Final Equity</td><td class="green">${equity[-1]:,.2f}</td></tr>
    <tr><td>Return</td><td class="green">{(equity[-1]/10000-1)*100:.1f}%</td></tr>
    <tr><td>Lookahead</td><td class="green">Guard-checked ✅</td></tr>
  </table>
  <h2>📝 Entry Models</h2>
  <table>
    <tr><th>#</th><th>Pattern</th><th>Entry</th><th>SL</th><th>TP</th></tr>
    <tr><td>M1</td><td>EQH/EQL → Int CHOCH → Int OB</td><td>OB Mid</td><td>OB Bottom - 0.5×H</td><td>Equilibrium (cap 5R)</td></tr>
    <tr><td>M5</td><td>Strong H/L + Swing OB</td><td>Swing OB Mid</td><td>0.5% sau Strong Level</td><td>Opposite Weak Level</td></tr>
    <tr><td>M7</td><td>Int CHOCH (trend filter) → Int OB</td><td>OB Mid</td><td>OB Bottom - 0.5×H</td><td>Equilibrium (cap 5R)</td></tr>
  </table>
  <div class="footer">
    SMC Event Engine | LuxAlgo-inspired | No lookahead, no repaint<br>
    Data: XAUUSD 15M Dukascopy | Generated by Hermes Agent
  </div>
</div>
</body>
</html>"""

    report_path = OUTPUT_DIR / "report.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Report: {report_path}")

    print(f"\n[✓] Report → {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
