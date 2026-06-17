#!/usr/bin/env python3
"""
[Step 3/4] Generate TradingView-style HTML chart với trade markers.
Chạy sau 02_run_strategy.py.
Output: output/chart/tradingview_chart.html
"""
import csv, json, sys, os
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)
csv.field_size_limit(10 * 1024 * 1024)

import pandas as pd

DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
LAYER1_DIR = Path("output") / "layer1"
OUTPUT_DIR = Path("output") / "chart"

from strategy_layer.tuned_strategies import V8_Combined


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load prices ──
    print("Loading data...", flush=True)
    df = pd.read_parquet(DATA_PATH)

    with open(LAYER1_DIR / "snapshots.csv") as f:
        snaps = list(csv.DictReader(f))

    ts_to_bi = {}
    for s in snaps:
        try: ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
        except: pass

    # Build candle data (all bars)
    candle_data = []
    for _, r in df.iterrows():
        ts = r["timestamp_utc"]
        ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
        candle_data.append({
            "time": ts_ms // 1000,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        })
    print(f"  Candles: {len(candle_data)}", flush=True)

    # ── Load Layer 1 ──
    with open(LAYER1_DIR / "events.csv") as f:
        events_by_bar = defaultdict(list)
        for r in csv.DictReader(f):
            events_by_bar[int(r["bar_index"])].append(r)

    bar_snaps = {int(s["bar_index"]): s for s in snaps}
    bar_indices = sorted(bar_snaps.keys())

    with open(LAYER1_DIR / "objects.csv") as f:
        all_objects = list(csv.DictReader(f))

    # Build OB cache (event-sourced)
    for ob in all_objects:
        try:
            af = int(ob.get("active_from", 0))
            act_bi = ts_to_bi.get(af, -1)
            if act_bi == -1 and af > 0:
                act_bi = ts_to_bi[sorted(k for k in ts_to_bi if k <= af)[-1]]
            ob["_bar_index"] = act_bi
        except:
            ob["_bar_index"] = -1

    obs_at_bar = defaultdict(list)
    for ob in all_objects:
        if ob["_bar_index"] >= 0:
            obs_at_bar[ob["_bar_index"]].append(ob)

    ob_by_id = {o.get("object_id", ""): o for o in all_objects if o.get("object_id", "")}

    lifecycle_by_bar = defaultdict(list)
    for bi, evs in events_by_bar.items():
        for ev in evs:
            if ev.get("event_type", "") in ("OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"):
                lifecycle_by_bar[bi].append(ev)

    active_ids = set()
    cache = {}
    for bi in bar_indices:
        for ob in obs_at_bar.get(bi, []):
            if ob.get("object_id", ""): active_ids.add(ob["object_id"])
        for ev in lifecycle_by_bar.get(bi, []):
            active_ids.discard(ev.get("object_id", ""))
        cache[bi] = [ob_by_id[oid] for oid in active_ids
                     if oid in ob_by_id and bi - ob_by_id[oid].get("_bar_index", 0) <= 200]

    # ── Run V8 model ──
    print("Running V8 for chart...", flush=True)
    model = V8_Combined()
    orders = []
    for bi in bar_indices:
        orders.extend(model.on_bar(bi, events_by_bar.get(bi, []), bar_snaps.get(bi, {}), cache.get(bi, [])))
    print(f"  Orders: {len(orders)}", flush=True)

    # ── Simulate trades ──
    SPREAD = 0.30; SLIPPAGE = 0.10
    trades = []
    for o in orders:
        entry = o.entry_price
        sl = o.sl_price
        tp = o.tp_price
        direction = o.direction
        cost = SPREAD / 2 + SLIPPAGE
        entry_cost = entry + cost if direction == 1 else entry - cost
        sl_exit = sl - cost if direction == 1 else sl + cost
        tp_exit = tp - cost if direction == 1 else tp + cost

        result = "open"; exit_price = entry_cost; bars_held = 0
        for off in range(1, 201):
            bi = o.bar_index + off
            bd = None
            cbi = ts_to_bi.get(candle_data[bi]["time"] * 1000 if bi < len(candle_data) else 0)
            # find bar data by bar_index
            if bi < len(bar_indices):
                for c in candle_data:
                    if ts_to_bi.get(c["time"] * 1000) == bi:
                        bd = c; break
            if not bd: break
            if direction == 1:
                if bd["low"] <= sl_exit:
                    result = "loss"; exit_price = sl_exit; bars_held = off; break
                if bd["high"] >= tp_exit:
                    result = "win"; exit_price = tp_exit; bars_held = off; break
            else:
                if bd["high"] >= sl_exit:
                    result = "loss"; exit_price = sl_exit; bars_held = off; break
                if bd["low"] <= tp_exit:
                    result = "win"; exit_price = tp_exit; bars_held = off; break

        ts_raw = bar_snaps.get(o.bar_index, {}).get("timestamp", 0)
        try: ts_s = int(ts_raw) // 1000
        except: ts_s = 0

        trades.append({
            "time": ts_s, "entry": round(entry_cost, 2),
            "sl": round(sl, 2), "tp": round(tp, 2),
            "direction": "LONG" if direction == 1 else "SHORT",
            "model": "V8", "result": result,
            "exit": round(exit_price, 2), "bars": bars_held,
        })

    print(f"  Trades: {len([t for t in trades if t['time'] > 0])}", flush=True)

    # ── Generate HTML ──
    candles_json = json.dumps(candle_data)
    trades_json = json.dumps([t for t in trades if t["time"] > 0])

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>XAUUSD M15 — V8 Combined Trades</title>
<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
  body {{ margin: 0; background: #131722; font-family: -apple-system, sans-serif; }}
  #chart {{ width: 100%; height: 100vh; }}
  .legend {{ position: fixed; top: 10px; left: 10px; z-index: 100; background: rgba(19,23,34,0.9); padding: 12px 16px; border-radius: 8px; border: 1px solid #2a2e39; color: #d1d4dc; font-size: 12px; }}
  .legend h3 {{ margin: 0 0 8px 0; color: #fff; font-size: 14px; }}
  .legend span {{ margin-right: 16px; }}
  .green {{ color: #089981; }} .red {{ color: #f23645; }} .blue {{ color: #2962FF; }}
</style>
</head>
<body>
<div id="chart"></div>
<div class="legend" id="legend">
  <h3>XAUUSD M15 — V8 Combined</h3>
  <span>Trades: <b id="tradeCount">0</b></span>
  <span>Wins: <b class="green" id="winCount">0</b></span>
  <span>Losses: <b class="red" id="lossCount">0</b></span>
  <span>WR: <b class="blue" id="wrPct">0%</b></span>
</div>

<script>
const candleData = {candles_json};
const tradeData = {trades_json};

const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    layout: {{ textColor: '#d1d4dc', background: {{ type: 'solid', color: '#131722' }} }},
    grid: {{ vertLines: {{ color: '#2a2e39' }}, horzLines: {{ color: '#2a2e39' }} }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    timeScale: {{ timeVisible: true, secondsVisible: false, borderColor: '#2a2e39' }},
    rightPriceScale: {{ borderColor: '#2a2e39' }},
}});

const candleSeries = chart.addCandlestickSeries({{
    upColor: '#089981', downColor: '#f23645',
    borderUpColor: '#089981', borderDownColor: '#f23645',
    wickUpColor: '#089981', wickDownColor: '#f23645',
}});
candleSeries.setData(candleData);

const markers = [];
let wins = 0, losses = 0;
tradeData.forEach((t) => {{
    if (!t.time) return;
    if (t.result === 'win') wins++; else if (t.result === 'loss') losses++;
    const color = t.result === 'win' ? '#089981' : '#f23645';
    const pos = t.direction === 'LONG' ? 'belowBar' : 'aboveBar';
    const shape = t.direction === 'LONG' ? 'arrowUp' : 'arrowDown';
    markers.push({{
        time: t.time, position: pos, color: color, shape: shape,
        text: `${{t.direction}} @${{t.entry}} → ${{t.exit}} (${{t.result}})`,
    }});
}});
candleSeries.setMarkers(markers);

const total = wins + losses;
document.getElementById('tradeCount').textContent = total;
document.getElementById('winCount').textContent = wins;
document.getElementById('lossCount').textContent = losses;
document.getElementById('wrPct').textContent = total > 0 ? (wins/total*100).toFixed(1)+'%' : '0%';

chart.timeScale().fitContent();
</script>
</body>
</html>"""

    out_path = OUTPUT_DIR / "tradingview_chart.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Chart: {out_path}", flush=True)
    print(f"[✓] Chart → {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
