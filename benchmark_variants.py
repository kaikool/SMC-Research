#!/usr/bin/env python3
"""Full benchmark: 5 tuned variants + original M5 + M7.
Runs all 7 models in one pass, simulates with manual OHLC."""

import sys, os, csv
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)
from pathlib import Path
from collections import defaultdict
import time
import pandas as pd

from strategy_layer.entry_strategies import Model5_StrongDefense, Model7_IntCHOCH_OB
from strategy_layer.tuned_strategies import (
    V1_M5_Extended, V2_M7_Filtered, V2a_Vol6, V2b_Vol8,
    V2c_VolSwing, V2d_Vol8Session, V2e_Vol10, V2f_Vol6Session, V2g_Vol4Session,
    V3_M7_SwingOB, V4_EQHEQL_SwingOB, V8_Combined,
)

DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
LAYER1_DIR = Path("output") / "layer1"

# Params
SPREAD = 0.30; SLIPPAGE = 0.10
MAX_FILL_WAIT = 150; MAX_HOLD = 200

def load_data():
    print("Loading data...", flush=True)
    df = pd.read_parquet(DATA_PATH)
    
    with open(LAYER1_DIR / "snapshots.csv") as f:
        snaps = list(csv.DictReader(f))
    with open(LAYER1_DIR / "events.csv") as f:
        raw_events = list(csv.DictReader(f))
    with open(LAYER1_DIR / "objects.csv") as f:
        all_objects = list(csv.DictReader(f))
    
    ts_to_bi = {}
    for s in snaps:
        try: ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
        except: pass
    
    prices = {}
    for _, row in df.iterrows():
        ts = row["timestamp_utc"]
        ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
        bi = ts_to_bi.get(ts_ms, -1)
        if bi >= 0:
            prices[bi] = {"open": float(row["open"]), "high": float(row["high"]),
                          "low": float(row["low"]), "close": float(row["close"])}
    
    events_by_bar = defaultdict(list)
    for e in raw_events:
        events_by_bar[int(e["bar_index"])].append(e)
    
    for ob in all_objects:
        try:
            af = int(ob.get("active_from", 0)); act_bi = ts_to_bi.get(af, -1)
            if act_bi == -1 and af > 0:
                act_bi = ts_to_bi[sorted(k for k in ts_to_bi if k <= af)[-1]]
            ob["_bar_index"] = act_bi
            ot = int(ob.get("created_at", 0)); org_bi = ts_to_bi.get(ot, -1)
            if org_bi == -1 and ot > 0:
                org_bi = ts_to_bi[sorted(k for k in ts_to_bi if k <= ot)[-1]]
            ob["_origin_bar_index"] = org_bi
        except: ob["_bar_index"] = -1
    
    obs_at_bar = defaultdict(list)
    for ob in all_objects:
        if ob["_bar_index"] >= 0: obs_at_bar[ob["_bar_index"]].append(ob)
    ob_by_id = {o.get("object_id", ""): o for o in all_objects if o.get("object_id", "")}
    
    lifecycle_by_bar = defaultdict(list)
    for bi, evs in events_by_bar.items():
        for ev in evs:
            if ev.get("event_type", "") in ("OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"):
                lifecycle_by_bar[bi].append(ev)
    
    active_ids = set(); active_ob_cache = {}
    for bi in sorted(ts_to_bi.values()):
        for ob in obs_at_bar.get(bi, []):
            if ob.get("object_id", ""): active_ids.add(ob["object_id"])
        for ev in lifecycle_by_bar.get(bi, []):
            active_ids.discard(ev.get("object_id", ""))
        active_ob_cache[bi] = [ob_by_id[oid] for oid in active_ids
                               if oid in ob_by_id and bi - ob_by_id[oid].get("_bar_index", 0) <= 200]
    
    bar_snaps = {int(s["bar_index"]): s for s in snaps}
    bar_indices = sorted(bar_snaps.keys())
    
    return prices, events_by_bar, bar_snaps, bar_indices, active_ob_cache


def run_model(model, bar_indices, events_by_bar, bar_snaps, active_ob_cache):
    orders = []
    for bi in bar_indices:
        orders.extend(model.on_bar(bi, events_by_bar.get(bi, []), bar_snaps.get(bi, {}), active_ob_cache.get(bi, [])))
    return orders


def sim_orders(orders, prices):
    """Manual OHLC simulation — returns result dict."""
    filled_total = 0; wins = 0; losses = 0; total_r = 0.0
    
    for o in orders:
        entry = o.entry_price; sl = o.sl_price; tp = o.tp_price
        direction = o.direction
        cost = SPREAD / 2 + SLIPPAGE
        entry_cost = entry + cost if direction == 1 else entry - cost
        risk = abs(entry_cost - sl)
        if risk <= 0: risk = 1
        
        # Find fill bar
        fill_bar = None
        for offset in range(1, MAX_FILL_WAIT + 1):
            bi = o.bar_index + offset
            bar = prices.get(bi)
            if not bar: break
            if direction == 1 and bar["low"] <= entry:
                fill_bar = bi; break
            if direction == -1 and bar["high"] >= entry:
                fill_bar = bi; break
        
        if fill_bar is None: continue  # unfilled
        
        filled_total += 1
        result = None
        for offset in range(0, MAX_HOLD + 1):
            bi = fill_bar + offset
            bar = prices.get(bi)
            if not bar: break
            if direction == 1:
                if bar["low"] <= sl: result = "loss"; break
                if bar["high"] >= tp:
                    total_r += abs(tp - entry_cost) / risk
                    result = "win"; break
            else:
                if bar["high"] >= sl: result = "loss"; break
                if bar["low"] <= tp:
                    total_r += abs(tp - entry_cost) / risk
                    result = "win"; break
        
        if result == "loss":
            total_r += -1.0
            losses += 1
        elif result == "win":
            wins += 1
    
    total = wins + losses
    return {
        "generated": len(orders), "filled": filled_total,
        "wins": wins, "losses": losses,
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
        "total_r": round(total_r, 2),
    }


def main():
    prices, events_by_bar, bar_snaps, bar_indices, ob_cache = load_data()
    
    models = [
        ("M5_ORIGINAL", Model5_StrongDefense()),
        ("M7_ORIGINAL", Model7_IntCHOCH_OB()),
        ("V1_M5_EXTENDED", V1_M5_Extended()),
        ("V2_VOL4", V2_M7_Filtered()),
        ("V2A_VOL6", V2a_Vol6()),
        ("V2B_VOL8", V2b_Vol8()),
        ("V2C_SWINGOB", V2c_VolSwing()),
        ("V2D_VOL8SES", V2d_Vol8Session()),
        ("V2E_VOL10", V2e_Vol10()),
        ("V2F_VOL6SES", V2f_Vol6Session()),
        ("V2G_VOL4SES", V2g_Vol4Session()),
        ("V3_M7_SWINGOB", V3_M7_SwingOB()),
        ("V4_EQHEQL_SWINGOB", V4_EQHEQL_SwingOB()),
        ("V8_COMBINED", V8_Combined()),
    ]
    
    results = []
    print(f"\n{'Model':<20} {'Gen':>5} {'Fill':>5} {'W':>5} {'L':>5} {'WR':>6} {'Tot R':>8} {'R/trade':>8} {'Sig/wk':>7}", flush=True)
    print("-" * 75, flush=True)
    
    for name, model in models:
        t0 = time.time()
        orders = run_model(model, bar_indices, events_by_bar, bar_snaps, ob_cache)
        t1 = time.time()
        res = sim_orders(orders, prices)
        elapsed = t1 - t0
        closed = res["wins"] + res["losses"]
        orders_pw = round(closed / (len(bar_indices) / (96*5)), 2)
        avg_r = round(res["total_r"] / closed, 2) if closed > 0 else 0
        
        results.append((name, res, orders_pw))
        
        print(f"{name:<20} {res['generated']:>5} {res['filled']:>5} {res['wins']:>5} {res['losses']:>5} {res['win_rate']:>6}% {res['total_r']:>8.2f} {avg_r:>8} {orders_pw:>7}", flush=True)
        print(f"{'':>20} {'took':>5} {elapsed:.0f}s{'':>20} {'gen/sig':>8} {res['generated']/elapsed:.0f}", flush=True)
    
    # Summary: best combos
    print("\n" + "=" * 75, flush=True)
    print("COMBINED BEST — selecting winners", flush=True)
    print("=" * 75, flush=True)
    
    # Find variants meeting both criteria
    for name, res, opw in results:
        wr = res["win_rate"]
        fits = "✅" if wr >= 65 and opw >= 3 else ("⚠️" if wr >= 60 and opw >= 2 else "❌")
        print(f"  {fits} {name:<18} WR={wr:>5}%  Sig/wk={opw:>5}  R={res['total_r']:>8.2f}", flush=True)
    
    # Find best combo of variants
    print("\nBest combination:", flush=True)
    # Use whichever models pass criteria OR combine complementary ones
    for name, res, opw in results:
        wr = res["win_rate"]
        if wr >= 60 and opw >= 2:
            print(f"  ✅ {name}: {wr}% WR, {opw}/wk, {res['total_r']}R", flush=True)


if __name__ == "__main__":
    main()
