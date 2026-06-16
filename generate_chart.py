"""
Generate TradingView lightweight chart with trade markers.
"""
import csv, json, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
sys.path.insert(0, ".")
csv.field_size_limit(10*1024*1024)

# ── Load data ────────────────────────────────────────────
print("Loading data for chart...")
out = Path("output_full_fvg")

# Prices
import pandas as pd
df = pd.read_parquet("D:/PHUCTD/SMC Research/data/XAUUSD_15m.parquet")

# Map timestamp to bar_index
with open(out/"layer1/snapshots.csv") as f:
    snaps = list(csv.DictReader(f))
ts_to_bi = {}
for s in snaps:
    try: ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
    except: pass

# Build OHLC for chart (last 5000 bars)
n_bars = 5000
candle_data = []
for _, r in df.tail(n_bars).iterrows():
    ts = r["timestamp_utc"]
    ts_ms = int(ts.timestamp()*1000) if hasattr(ts,'timestamp') else 0
    candle_data.append({
        "time": ts_ms//1000,  # seconds for lightweight-charts
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
    })

print(f"Candles: {len(candle_data)}")

# ── Run models to get trades ─────────────────────────────
from strategy_layer.entry_strategies import (
    Model1_EQHEQL_Sweep_InternalCHOCH,
    Model5_StrongDefense,
    Model7_IntCHOCH_OB,
)

with open(out/"layer1/events.csv") as f:
    eb = defaultdict(list)
    for r in csv.DictReader(f): eb[int(r["bar_index"])].append(r)

with open(out/"layer1/objects.csv") as f:
    all_obs = list(csv.DictReader(f))

for ob in all_obs:
    try:
        ot = int(ob.get("created_at",0))
        bi = ts_to_bi.get(ot,-1)
        if bi==-1 and ot>0:
            st = sorted(k for k in ts_to_bi.keys() if k<=ot)
            if st: bi=ts_to_bi[st[-1]]
        ob["_bar_index"] = bi
    except: ob["_bar_index"]=-1

obb = defaultdict(list)
for ob in all_obs:
    bi = ob.get("_bar_index",-1)
    if bi>=0: obb[bi].append(ob)

# Build OB cache
bar_snaps = {int(s["bar_index"]): s for s in snaps}
bix = sorted(bar_snaps.keys())[-50000:]  # use last 50k for models
cache = {}
recent = []
for bi in bix:
    for ob in obb.get(bi,[]): recent.append(ob)
    recent = [ob for ob in recent if bi-ob.get("_bar_index",0)<=200]
    cache[bi] = list(recent)

# Run models
min_bar = candle_data[0]["time"] * 1000  # first candle timestamp in ms
min_bi = None
for ts, bi in ts_to_bi.items():
    if ts >= min_bar:
        min_bi = bi
        break

models = [
    ("M1", Model1_EQHEQL_Sweep_InternalCHOCH()),
    ("M5", Model5_StrongDefense()),
    ("M7", Model7_IntCHOCH_OB()),
]

trades = []  # (time, direction, entry, sl, tp, model, outcome)

for mn, model in models:
    orders = []
    for bi in bix:
        oo = model.on_bar(bi, eb.get(bi,[]), bar_snaps.get(bi,{}), cache.get(bi,[]))
        orders.extend(oo)
    
    # Simulate and collect visible trades
    for o in orders:
        if o.bar_index < (min_bi or 0):
            continue
        
        entry = o.entry_price; sl = o.sl_price; tp = o.tp_price
        risk = abs(entry-sl) if sl!=entry else 1
        reward = abs(tp-entry)
        
        result="open"; exit_price=entry; bars_held=0
        for off in range(1, 201):
            bi = o.bar_index+off
            # Get price from cached data
            ts_bi = bi
            # find candle
            found = False
            for c in candle_data:
                ctime = c["time"]*1000
                cbi = ts_to_bi.get(ctime)
                if cbi == bi:
                    if o.direction==1:
                        if c["low"]<=sl: result="loss"; exit_price=sl; bars_held=off; found=True; break
                        if c["high"]>=tp: result="win"; exit_price=tp; bars_held=off; found=True; break
                    else:
                        if c["high"]>=sl: result="loss"; exit_price=sl; bars_held=off; found=True; break
                        if c["low"]<=tp: result="win"; exit_price=tp; bars_held=off; found=True; break
            if found: break
        
        ts = bar_snaps.get(o.bar_index, {}).get("timestamp", 0)
        try: ts_s = int(ts)//1000
        except: ts_s = 0
        
        trades.append({
            "time": ts_s,
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "direction": "LONG" if o.direction==1 else "SHORT",
            "model": mn,
            "result": result,
            "exit": round(exit_price, 2),
            "bars": bars_held,
        })

print(f"Trades in chart range: {len([t for t in trades if t['time']>0])}")

# ── Generate HTML ────────────────────────────────────────
candles_json = json.dumps(candle_data)
trades_json = json.dumps([t for t in trades if t["time"] > 0])

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>XAUUSD 15M — SMC Trades</title>
<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
  body {{ margin: 0; background: #131722; font-family: -apple-system, sans-serif; }}
  #chart {{ width: 100%; height: 100vh; }}
  .legend {{ position: fixed; top: 10px; left: 10px; z-index: 100; background: rgba(19,23,34,0.9); padding: 12px 16px; border-radius: 8px; border: 1px solid #2a2e39; color: #d1d4dc; font-size: 12px; }}
  .legend h3 {{ margin: 0 0 8px 0; color: #fff; font-size: 14px; }}
  .legend span {{ margin-right: 16px; }}
  .green {{ color: #089981; }}
  .red {{ color: #f23645; }}
  .blue {{ color: #2962FF; }}
  .controls {{ position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); z-index: 100; display: flex; gap: 8px; }}
  .controls button {{ background: #2a2e39; border: 1px solid #3a3e49; color: #d1d4dc; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 11px; }}
  .controls button:hover {{ background: #3a3e49; }}
  .controls button.active {{ background: #2962FF; border-color: #2962FF; color: #fff; }}
</style>
</head>
<body>
<div id="chart"></div>
<div class="legend" id="legend">
  <h3>XAUUSD 15M — SMC Event Engine</h3>
  <span>Trades: <b id="tradeCount">0</b></span>
  <span>Wins: <b class="green" id="winCount">0</b></span>
  <span>Losses: <b class="red" id="lossCount">0</b></span>
  <span>WR: <b class="blue" id="wrPct">0%</b></span>
</div>
<div class="controls">
  <button class="active" onclick="showAll()">All Models</button>
  <button onclick="showModel('M1')">M1</button>
  <button onclick="showModel('M5')">M5</button>
  <button onclick="showModel('M7')">M7</button>
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

// Markers for trades
let allMarkers = [];
tradeData.forEach((t, i) => {{
    if (!t.time) return;
    const color = t.result === 'win' ? '#089981' : '#f23645';
    const pos = t.direction === 'LONG' ? 'belowBar' : 'aboveBar';
    const shape = t.direction === 'LONG' ? 'arrowUp' : 'arrowDown';
    allMarkers.push({{
        time: t.time,
        position: pos,
        color: color,
        shape: shape,
        text: `${{t.model}} ${{t.direction}} @${{t.entry}} → ${{t.exit}} (${{t.result}})`,
    }});
}});

function showAll() {{
    candleSeries.setMarkers(allMarkers);
    updateLegend(tradeData);
}}

function showModel(model) {{
    const filtered = allMarkers.filter((m, i) => tradeData[i] && tradeData[i].model === model);
    candleSeries.setMarkers(filtered);
    const td = tradeData.filter(t => t.model === model);
    updateLegend(td);
    
    document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
}}

function updateLegend(td) {{
    const wins = td.filter(t => t.result === 'win').length;
    const losses = td.filter(t => t.result === 'loss').length;
    const total = wins + losses;
    document.getElementById('tradeCount').textContent = total;
    document.getElementById('winCount').textContent = wins;
    document.getElementById('lossCount').textContent = losses;
    document.getElementById('wrPct').textContent = total > 0 ? (wins/total*100).toFixed(1)+'%' : '0%';
}}

// Initial render
showAll();
chart.timeScale().fitContent();
</script>
</body>
</html>
"""

path = out / "tradingview_chart.html"
with open(path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"Chart saved: {path}")
