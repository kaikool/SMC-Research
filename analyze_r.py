#!/usr/bin/env python3
"""Analyze model R stats + session distribution."""
import sys, os, csv
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
from collections import defaultdict
from strategy_layer.entry_strategies import Model5_StrongDefense, Model7_IntCHOCH_OB
from datetime import datetime, timezone
import pandas as pd

LAYER1_DIR = Path("output") / "layer1"
DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
df = pd.read_parquet(DATA_PATH)

with open(LAYER1_DIR / "objects.csv") as f:
    all_objects = list(csv.DictReader(f))
with open(LAYER1_DIR / "snapshots.csv") as f:
    snaps = list(csv.DictReader(f))
with open(LAYER1_DIR / "events.csv") as f:
    raw_events = list(csv.DictReader(f))

ts_to_bi = {}
for s in snaps:
    try: ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
    except: pass

events_by_bar = defaultdict(list)
for e in raw_events:
    events_by_bar[int(e["bar_index"])].append(e)

bar_snaps = {int(s["bar_index"]): s for s in snaps}
bar_indices = sorted(bar_snaps.keys())

# OB cache
for ob in all_objects:
    try:
        af=int(ob.get("active_from",0)); act_bi=ts_to_bi.get(af,-1)
        if act_bi==-1 and af>0: act_bi=ts_to_bi[sorted(k for k in ts_to_bi if k<=af)[-1]]
        ob["_bar_index"]=act_bi
    except: ob["_bar_index"]=-1

obs_at_bar=defaultdict(list)
for ob in all_objects:
    if ob["_bar_index"]>=0: obs_at_bar[ob["_bar_index"]].append(ob)
ob_by_id={o.get("object_id",""): o for o in all_objects if o.get("object_id","")}

lifecycle_by_bar=defaultdict(list)
for bi,evs in events_by_bar.items():
    for ev in evs:
        if ev.get("event_type","") in ("OB_MITIGATED","OB_INVALIDATED","OB_EXPIRED"):
            lifecycle_by_bar[bi].append(ev)

active_ids=set(); active_ob_cache={}
for bi in bar_indices:
    for ob in obs_at_bar.get(bi,[]):
        if ob.get("object_id",""): active_ids.add(ob["object_id"])
    for ev in lifecycle_by_bar.get(bi,[]):
        active_ids.discard(ev.get("object_id",""))
    active_ob_cache[bi]=[ob_by_id[oid] for oid in active_ids if oid in ob_by_id and bi-ob_by_id[oid].get("_bar_index",0)<=200]

SPREAD=0.30; SLIPPAGE=0.10
def r_of(o):
    cost=SPREAD/2+SLIPPAGE
    ec=o.entry_price+cost if o.direction==1 else o.entry_price-cost
    risk=abs(ec-o.sl_price); reward=abs(o.tp_price-ec)
    return reward/risk if risk>0 else 0

# M7
m7=Model7_IntCHOCH_OB()
o7=[]
for bi in bar_indices:
    o7.extend(m7.on_bar(bi, events_by_bar.get(bi,[]), bar_snaps.get(bi,{}), active_ob_cache.get(bi,[])))
r7=sorted([r_of(o) for o in o7])
n7=len(r7)
print(f"M7: {n7} orders")
print(f"  R: p25={r7[n7//4]:.2f} p50={r7[n7//2]:.2f} avg={sum(r7)/n7:.2f} p75={r7[3*n7//4]:.2f} max={r7[-1]:.2f}")
print(f"  R<0.3: {sum(1 for r in r7 if r<0.3)/n7*100:.0f}%  R<1: {sum(1 for r in r7 if r<1)/n7*100:.0f}%  R>2: {sum(1 for r in r7 if r>2)/n7*100:.0f}%")

# M5
m5=Model5_StrongDefense()
o5=[]
for bi in bar_indices:
    o5.extend(m5.on_bar(bi, events_by_bar.get(bi,[]), bar_snaps.get(bi,{}), active_ob_cache.get(bi,[])))
r5=sorted([r_of(o) for o in o5])
n5=len(r5)
print(f"\nM5: {n5} orders")
print(f"  R: p25={r5[n5//4]:.2f} p50={r5[n5//2]:.2f} avg={sum(r5)/n5:.2f} p75={r5[3*n5//4]:.2f} max={r5[-1]:.2f}")
print(f"  R<0.3: {sum(1 for r in r5 if r<0.3)/n5*100:.0f}%  R<1: {sum(1 for r in r5 if r<1)/n5*100:.0f}%  R>2: {sum(1 for r in r5 if r>2)/n5*100:.0f}%")

# Sessions for M7
print(f"\nSession breakdown for M7 (first 3000):")
sessions=defaultdict(int)
for o in o7[:3000]:
    ts=int(bar_snaps.get(o.bar_index,{}).get("timestamp",0))
    if ts:
        dt=datetime.fromtimestamp(ts/1000,tz=timezone.utc); hr=dt.hour
        if 13<=hr<17: ses='london_ny'
        elif 8<=hr<13: ses='london'
        elif 13<=hr<22: ses='ny'
        elif 0<=hr<9: ses='asia'
        else: ses='off'
        sessions[ses]+=1
for s,c in sorted(sessions.items()): print(f"  {s}: {c}")

# What's the min R if we filter M7 by session + volatility?
print(f"\nIf we filter M7 to only London/NY (50-70% signals removed), need WR from 26% -> 65%")
print(f"Required improvement: 26% -> 65% = 2.5x WR")
print(f"That's too aggressive for session filter alone.")

# Check M5: what if we relax conditions?
print(f"\nM5 only has {n5} orders in 210k bars.")
print(f"Need ~3/week = ~1315 fills in 438 weeks.")
print(f"Currently 475 fills. Need {1315-475}=840 more = 2.8x current.")
print(f"If WR drops from 71% to 55% with more signals, that might not hit target.")
