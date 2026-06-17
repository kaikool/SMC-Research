#!/usr/bin/env python3
"""Trace OB cache + V8 for lookahead detection."""
import sys, os, csv
sys.path.insert(0, "D:/Antigravity/SMC Research")
sys.stdout.reconfigure(line_buffering=True)
from pathlib import Path
from collections import defaultdict

LAYER1_DIR = Path("output") / "layer1"

# Load events
with open(LAYER1_DIR / "events.csv") as f:
    events = list(csv.DictReader(f))

# Load objects
with open(LAYER1_DIR / "objects.csv") as f:
    objects = list(csv.DictReader(f))

# Load snapshots  
with open(LAYER1_DIR / "snapshots.csv") as f:
    snaps = list(csv.DictReader(f))

# Build ts_to_bi
ts_to_bi = {}
for s in snaps:
    try: ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
    except: pass

# Map OB active_from to bar_index
print("=== OB SAMPLE (first 10) ===")
for ob in objects[:10]:
    af = int(ob.get("active_from", 0))
    act_bi = ts_to_bi.get(af, -1)
    ct = int(ob.get("created_at", 0))
    ct_bi = ts_to_bi.get(ct, -1)
    print(f"  OB {ob['object_id']}: created_at_bi={ct_bi}, active_from_bi={act_bi}, src={ob.get('source_event','')}")

# Check: is there any OB where active_from_bi < created_at_bi?
print("\n=== OB with active_from < created_at ===")
bad = 0
for ob in objects:
    af = int(ob.get("active_from", 0))
    act_bi = ts_to_bi.get(af, -1)
    ct = int(ob.get("created_at", 0))
    ct_bi = ts_to_bi.get(ct, -1)
    if act_bi >= 0 and ct_bi >= 0 and act_bi < ct_bi:
        bad += 1
        if bad <= 3:
            print(f"  ** {ob['object_id']}: created_bi={ct_bi}, active_bi={act_bi}")
print(f"  Total OBs with active_bi < created_bi: {bad}")

print(f"\nTotal OBs: {len(objects)}")
print(f"Events: {len(events)}")
print(f"Snapshots: {len(snaps)}")

import pandas as pd
DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
df = pd.read_parquet(DATA_PATH)

from strategy_layer.tuned_strategies import V8_Combined

events_by_bar = defaultdict(list)
for e in events:
    events_by_bar[int(e["bar_index"])].append(e)

bar_snaps = {int(s["bar_index"]): s for s in snaps}
bar_indices = sorted(bar_snaps.keys())

# Build OB cache (event-sourced)
for ob in objects:
    try:
        af = int(ob.get("active_from", 0))
        act_bi = ts_to_bi.get(af, -1)
        if act_bi == -1 and af > 0:
            st = sorted(k for k in ts_to_bi if k <= af)
            if st: act_bi = ts_to_bi[st[-1]]
        ob["_bar_index"] = act_bi
    except: ob["_bar_index"] = -1

obs_at_bar = defaultdict(list)
for ob in objects:
    if ob["_bar_index"] >= 0: obs_at_bar[ob["_bar_index"]].append(ob)

ob_by_id = {o.get("object_id", ""): o for o in objects if o.get("object_id", "")}

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
    cache[bi] = [ob_by_id[oid] for oid in active_ids if oid in ob_by_id and bi - ob_by_id[oid].get("_bar_index", 0) <= 200]

# Run V8 and trace trades
model = V8_Combined()
traced = []

for bi in bar_indices[:10000]:  # first 10k bars for trace
    orders = model.on_bar(bi, events_by_bar.get(bi, []), bar_snaps.get(bi, {}), cache.get(bi, []))
    for o in orders:
        if o.bar_index >= 0:
            traced.append({
                "bar_idx": o.bar_index,
                "direction": o.direction,
                "entry": o.entry_price,
                "source": o.model,
                "reason": o.reason,
            })

print(f"\n=== FIRST 5 V8 TRADES ===")
for t in traced[:5]:
    print(f"  bar={t['bar_idx']}, dir={'LONG' if t['direction']==1 else 'SHORT'}, entry={t['entry']:.2f}, src={t['source']}, reason={t['reason']}")

# Deep trace: first trade
if traced:
    t = traced[0]
    bi = t["bar_idx"]
    obs_at_signal = cache.get(bi, [])
    print(f"\n=== DEEP TRACE bar {bi} ===")
    print(f"  Signal: {t['direction']} {t['reason']}")
    print(f"  OB cache at bar {bi}: {len(obs_at_signal)} OBs")
    for ob in obs_at_signal[:5]:
        print(f"    {ob.get('object_id','')} dir={ob.get('direction','')} _bi={ob.get('_bar_index','')} src={ob.get('source_event','')}")
    print(f"  Events at bar {bi}:")
    for e in events_by_bar.get(bi, [])[:5]:
        print(f"    {e['event_type']} dir={e.get('direction','')}")

# Now cross-validate: run mode on bar bi, check if the OB it uses has _bar_index <= bi and _bar_index >= setup.bar_idx
print("\n=== CHECK lookahead: OB._bar_index vs signal bar ===")
lookahead_count = 0
for bi in bar_indices[:10000]:
    for ob in cache.get(bi, []):
        ob_bi = ob.get("_bar_index", -1)
        if ob_bi > bi:
            lookahead_count += 1
            if lookahead_count <= 3:
                print(f"  LOOKAHEAD: OB {ob['object_id']} _bi={ob_bi} > current bar {bi}")
        elif ob_bi == bi:
            if lookahead_count <= 3:
                print(f"  SAME BAR: OB {ob['object_id']} _bi={ob_bi} == current bar {bi}")
print(f"  Total lookahead cases (OB._bi > bar): {lookahead_count}")
