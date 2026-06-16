"""
Optimized test runner — sliding window over objects, no full scan per bar.
"""
import sys, os, csv
from pathlib import Path
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(__file__))
os.environ["PYTHONUNBUFFERED"] = "1"

from strategy_layer.entry_strategies import (
    Model1_EQHEQL_Sweep_InternalCHOCH,
    Model2_FVG_PremiumDiscount,
    Model3_MTF_SwingCHOCH,
    Model4_SwingBOS_Continuation,
    Model5_StrongHighLow_Defense,
)

# ── Config ─────────────────────────────────────────────────
WINDOW = 30  # max bars back that an OB can be "active" (only recent OBs matter)
SAMPLE_BARS = 50000  # use last 50k bars for speed (≈ 1.5 years)

events_dir = Path("output_full/layer1")
print("Loading data...")

# Load snapshots (fast — sequential)
with open(events_dir / "snapshots.csv") as f:
    all_snaps = list(csv.DictReader(f))
print(f"  Snapshots: {len(all_snaps)}")

# Use last N bars
bar_snapshots = {int(s["bar_index"]): s for s in all_snaps[-SAMPLE_BARS:]}
bar_indices = sorted(bar_snapshots.keys())
min_bar = bar_indices[0]
max_bar = bar_indices[-1]
print(f"  Using bars {min_bar} → {max_bar} ({len(bar_indices)} bars)")

# Load events (filter by bar range)
with open(events_dir / "events.csv") as f:
    reader = csv.DictReader(f)
    events_by_bar = defaultdict(list)
    for row in reader:
        bi = int(row["bar_index"])
        if min_bar <= bi <= max_bar:
            events_by_bar[bi].append(row)
print(f"  Events in range: {sum(len(v) for v in events_by_bar.values())}")

# Load objects (filter by created_bar within window of range)
with open(events_dir / "objects.csv") as f:
    all_objects = list(csv.DictReader(f))

# Objects indexed by bar (done below after timestamp mapping)

# Build timestamp → bar_index map from snapshots
ts_to_bar = {}
for s in all_snaps:
    try:
        ts_to_bar[int(s["timestamp"])] = int(s["bar_index"])
    except (ValueError, KeyError):
        pass

# Pre-compute bar_index for each OB from created_at timestamp
for ob in all_objects:
    try:
        ob_ts = int(ob.get("created_at", 0))
        # Find the closest bar timestamp <= ob_ts
        ob_bar = ts_to_bar.get(ob_ts, -1)
        if ob_bar == -1 and ob_ts > 0:
            # Find nearest lower timestamp
            sorted_ts = sorted(k for k in ts_to_bar.keys() if k <= ob_ts)
            if sorted_ts:
                ob_bar = ts_to_bar[sorted_ts[-1]]
        ob["_bar_index"] = ob_bar
    except Exception:
        ob["_bar_index"] = -1

# Re-index by bar_index
objects_by_bar = defaultdict(list)
for ob in all_objects:
    bi = ob.get("_bar_index", -1)
    if bi >= 0:
        objects_by_bar[bi].append(ob)

print(f"  Objects indexed: {sum(len(v) for v in objects_by_bar.values())} mapped to bars")

# Build a sliding window cache: for each bar, collect OBs created in [bar-WINDOW, bar]
active_ob_cache = {}
recent_obs = []
print(f"  Building OB cache (window={WINDOW} bars)...")
for bi in range(min_bar, max_bar + 1):
    for ob in objects_by_bar.get(bi, []):
        recent_obs.append(ob)
    recent_obs = [ob for ob in recent_obs
                  if bi - ob.get("_bar_index", 0) <= WINDOW]
    active_ob_cache[bi] = list(recent_obs)
    if bi % 20000 == 0:
        print(f"    Cached bar {bi}/{max_bar} ({len(recent_obs)} active OBs)")

print(f"  OB cache ready: {len(active_ob_cache)} bars, ~{sum(len(v) for v in active_ob_cache.values())//len(active_ob_cache)} avg OBs/bar")

# ── Run each model ────────────────────────────────────────
models = [
    ("M1: EQH/EQL Sweep → Int CHOCH → Int OB → Equilibrium",
     Model1_EQHEQL_Sweep_InternalCHOCH()),
    ("M2: FVG tại Premium/Discount Zone",
     Model2_FVG_PremiumDiscount()),
    ("M3: MTF Level → Swing CHoCH → Swing OB",
     Model3_MTF_SwingCHOCH()),
    ("M4: Swing BOS → Swing OB Pullback → Continuation",
     Model4_SwingBOS_Continuation()),
    ("M5: Strong High/Low Defense → Swing OB",
     Model5_StrongHighLow_Defense()),
]

total_orders = 0
for model_name, model in models:
    print(f"\n{'='*60}")
    model_short = model_name.split(":")[0]
    print(f"RUNNING: {model_name}")
    all_orders = []

    for bi in bar_indices:
        bar_events = events_by_bar.get(bi, [])
        snapshot = bar_snapshots.get(bi, {})
        active_obs = active_ob_cache.get(bi, [])

        bar_orders = model.on_bar(bi, bar_events, snapshot, active_obs)
        if bar_orders:
            all_orders.extend(bar_orders)

    print(f"  Orders: {len(all_orders)}")
    total_orders += len(all_orders)

    if all_orders:
        dirs = Counter(o.direction for o in all_orders)
        print(f"  LONG: {dirs.get(1, 0)}, SHORT: {dirs.get(-1, 0)}")

        # Time range of orders
        timestamps = []
        dir_map = {1: "LONG", -1: "SHORT"}
        for o in all_orders[:15]:
            d = dir_map.get(o.direction, "?")
            print(f"    {o.setup_id}: {d} @ {o.entry_price:.2f} "
                  f"SL={o.sl_price:.2f} TP={o.tp_price:.2f}")
            print(f"      {o.reason[:100]}")
    else:
        print(f"  ❌ No orders (possible data gap: describe below)")

print(f"\n{'='*60}")
print(f"TOTAL across {len(models)} models: {total_orders} orders")
print(f"{'='*60}")
