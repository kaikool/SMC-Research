#!/usr/bin/env python3
"""
[Step 3/4] Generate TradingView-style HTML chart với trade markers + OB zones.
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

    # ── Load OB zones with lifecycle ──
    print("Loading OB zones for chart...", flush=True)
    end_bi = max(ts_to_bi.values()) if ts_to_bi else max(bar_indices)
    start_bi = max(0, end_bi - 50000)

    ob_lifecycle = {}
    for bar_evs in events_by_bar.values():
        for e in bar_evs:
            et = e.get("event_type", "")
            if et in ("OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"):
                oid = e.get("object_id", "")
                bi = int(e.get("bar_index", 0))
                if oid and (oid not in ob_lifecycle or bi > ob_lifecycle[oid]["bar"]):
                    ob_lifecycle[oid] = {"type": et, "bar": bi}

    ob_zones = []
    seen_prices = set()
    for ob in all_objects:
        try:
            oid = ob.get("object_id", "")
            if not ob.get("_bar_index"):
                af = int(ob.get("active_from", 0))
                ob["_bar_index"] = ts_to_bi.get(af, -1)
            ob_bi = ob.get("_bar_index", -1)
            if ob_bi < start_bi or ob_bi > end_bi:
                continue

            top = float(ob.get("top", 0))
            bottom = float(ob.get("bottom", 0))
            key = (round(top, 2), round(bottom, 2), ob.get("direction", ""))
            if key in seen_prices:
                continue
            seen_prices.add(key)

            active_ts = int(ob.get("active_from", 0))

            lc = ob_lifecycle.get(oid)
            end_ts = 0
            if lc:
                for s in snaps:
                    if int(s["bar_index"]) == lc["bar"]:
                        end_ts = int(s["timestamp"])
                        break

            ob_zones.append({
                "time_start": active_ts // 1000,
                "time_end": end_ts // 1000 if end_ts else 0,
                "top": top,
                "bottom": bottom,
                "direction": "bullish" if ob.get("direction") == "1" else "bearish",
            })
        except:
            pass
    print(f"  OB zones: {len(ob_zones)} (with lifecycle)", flush=True)

    # ── Run V8 model ──
    print("Running V8 for chart...", flush=True)
    model = V8_Combined()
    orders = []
    for bi in bar_indices:
        orders.extend(model.on_bar(bi, events_by_bar.get(bi, []), bar_snaps.get(bi, {}), cache.get(bi, [])))
    print(f"  Orders: {len(orders)}", flush=True)

    # ── Simulate trades via execution_core ──
    print("Simulating trades for chart...", flush=True)
    from execution_core import OrderIntent, simulate_orders

    prices = {}
    for _, row in df.iterrows():
        ts = row["timestamp_utc"]
        ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
        bi = ts_to_bi.get(ts_ms, -1)
        if bi >= 0:
            prices[bi] = {"open": float(row["open"]), "high": float(row["high"]),
                           "low": float(row["low"]), "close": float(row["close"])}

    intents = []
    for o in orders:
        intents.append(OrderIntent(
            setup_id=f"V8_{len(intents)}",
            direction=o.direction, order_type="limit",
            entry_price=o.entry_price,
            entry_zone_top=o.entry_zone_top, entry_zone_bottom=o.entry_zone_bottom,
            stop_loss=o.sl_price, take_profit=o.tp_price,
            signal_bar=o.bar_index, timestamp=o.timestamp,
            valid_until_bar=o.bar_index + 150, source=o.model,
        ))

    trades_records = simulate_orders(intents, prices)

    trades = []
    for t in trades_records:
        ts_raw = bar_snaps.get(t.signal_bar, {}).get("timestamp", 0)
        try: ts_s = int(ts_raw) // 1000
        except: ts_s = 0
        trades.append({
            "time": ts_s,
            "entry": round(t.fill_price, 2),
            "direction": "LONG" if t.direction == 1 else "SHORT",
            "result": "win" if t.net_r > 0 else "loss",
            "exit": round(t.exit_price, 2),
            "bars": t.holding_bars,
        })

    wins = sum(1 for t in trades if t["result"] == "win")
    losses = sum(1 for t in trades if t["result"] == "loss")
    print(f"  Trades: {len(trades)} (wins={wins}, losses={losses})", flush=True)

    # ── Generate HTML ──
    candles_json = json.dumps(candle_data)
    trades_json = json.dumps([t for t in trades if t["time"] > 0])
    ob_zones_json = json.dumps(ob_zones[:500])

    # Build JS separately to avoid f-string escaping hell
    js = f"""
const candleData = {candles_json};
const tradeData = {trades_json};
const obZones = {ob_zones_json};

const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    layout: {{ textColor: '#d1d4dc', background: {{ type: 'solid', color: '#131722' }} }},
    grid: {{ vertLines: {{ color: '#2a2e39' }}, horzLines: {{ color: '#2a2e39' }} }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    timeScale: {{ timeVisible: true, secondsVisible: true, borderColor: '#2a2e39' }},
    rightPriceScale: {{ borderColor: '#2a2e39' }},
}});

const candleSeries = chart.addCandlestickSeries({{
    upColor: '#089981', downColor: '#f23645',
    borderUpColor: '#089981', borderDownColor: '#f23645',
    wickUpColor: '#089981', wickDownColor: '#f23645',
}});
candleSeries.setData(candleData);

// ── OB Canvas Rectangles ──
function drawRectangles() {{
    const canvas = document.getElementById('obCanvas');
    const wrapper = document.getElementById('wrapper');
    canvas.width = wrapper.clientWidth;
    canvas.height = wrapper.clientHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!chart.timeScale().getVisibleLogicalRange()) return;
    const vr = chart.timeScale().getVisibleRange();
    obZones.forEach((ob) => {{
        const startSec = ob.time_start;
        const endSec = ob.time_end;
        if ((endSec && endSec < vr.from) || startSec > vr.to) return;
        const px1 = chart.timeScale().timeToCoordinate(startSec);
        let px2 = endSec ? chart.timeScale().timeToCoordinate(endSec) : null;
        if (px1 == null || (endSec && px2 == null)) return;
        if (px2 == null) px2 = canvas.width;
        const yTop = chart.priceScale().priceToCoordinate(ob.top);
        const yBot = chart.priceScale().priceToCoordinate(ob.bottom);
        if (yTop == null || yBot == null || px2 <= px1) return;
        const color = ob.direction === 'bullish' ? 'rgba(8,153,129,0.20)' : 'rgba(242,54,69,0.20)';
        const borderColor = ob.direction === 'bullish' ? '#089981' : '#f23645';
        ctx.fillStyle = color;
        ctx.fillRect(px1, Math.min(yTop, yBot), px2 - px1, Math.abs(yTop - yBot));
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = 0.5;
        ctx.strokeRect(px1, Math.min(yTop, yBot), px2 - px1, Math.abs(yTop - yBot));
    }});
}}

chart.timeScale().subscribeVisibleTimeRangeChange(drawRectangles);
chart.timeScale().subscribeVisibleLogicalRangeChange(drawRectangles);
window.addEventListener('resize', () => {{ chart.resize(wrapper.clientWidth, wrapper.clientHeight); drawRectangles(); }});
setTimeout(drawRectangles, 300);

// ── Trade Markers ──
const markers = [];
let wins = 0, losses = 0;
tradeData.forEach((t) => {{
    if (!t.time) return;
    if (t.result === 'win') wins++; else if (t.result === 'loss') losses++;
    markers.push({{
        time: t.time,
        position: t.direction === 'LONG' ? 'belowBar' : 'aboveBar',
        color: t.result === 'win' ? '#089981' : '#f23645',
        shape: t.direction === 'LONG' ? 'arrowUp' : 'arrowDown',
        text: `${{t.direction}} @${{t.entry}} → ${{t.exit}} (${{t.result}})`,
    }});
}});
candleSeries.setMarkers(markers);

// ── Legend ──
const total = wins + losses;
document.getElementById('tradeCount').textContent = total;
document.getElementById('winCount').textContent = wins;
document.getElementById('lossCount').textContent = losses;
document.getElementById('wrPct').textContent = total > 0 ? (wins/total*100).toFixed(1)+'%' : '0%';
document.getElementById('obCount').textContent = obZones.length;

chart.timeScale().fitContent();
window.addEventListener('resize', () => {{ drawRectangles(); }});
"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>XAUUSD M15 — V8 Combined Trades + OB Zones</title>
<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
  body {{ margin: 0; background: #131722; font-family: -apple-system, sans-serif; overflow: hidden; }}
  #wrapper {{ position: relative; width: 100%; height: 100vh; }}
  #chart {{ width: 100%; height: 100vh; }}
  #obCanvas {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 10; }}
  .legend {{ position: fixed; top: 10px; left: 10px; z-index: 100; background: rgba(19,23,34,0.9); padding: 12px 16px; border-radius: 8px; border: 1px solid #2a2e39; color: #d1d4dc; font-size: 12px; }}
  .legend h3 {{ margin: 0 0 8px 0; color: #fff; font-size: 14px; }}
  .legend span {{ margin-right: 16px; }}
  .green {{ color: #089981; }} .red {{ color: #f23645; }} .blue {{ color: #2962FF; }}
</style>
</head>
<body>
<div id="wrapper">
  <div id="chart"></div>
  <canvas id="obCanvas"></canvas>
</div>
<div class="legend" id="legend">
  <h3>XAUUSD M15 — V8 Combined</h3>
  <span>Trades: <b id="tradeCount">0</b></span>
  <span>Wins: <b class="green" id="winCount">0</b></span>
  <span>Losses: <b class="red" id="lossCount">0</b></span>
  <span>WR: <b class="blue" id="wrPct">0%</b></span>
  <span>OB: <b id="obCount">0</b></span>
</div>
<script>
{js}
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
