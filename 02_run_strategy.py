#!/usr/bin/env python3
"""
[Step 2/4] Strategy + Execution pipeline.
Đọc Layer 1 output → OB cache → V8 model → OrderIntent → execution_core → trades.

Usage:
    python 02_run_strategy.py

Output: output/backtest/results.csv, trades.csv
"""
import sys, os, csv, time
sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)
from pathlib import Path
from collections import defaultdict
import pandas as pd

from strategy_layer.tuned_strategies import V8_Combined
from execution_core import OrderIntent, simulate_orders, summarize_trades

DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
LAYER1_DIR = Path("output") / "layer1"
OUTPUT_DIR = Path("output") / "backtest"
WINDOW = 200


def load_data():
    """Load prices, events, objects, snapshots — 1 pass."""
    print("Loading Layer 1 data...", flush=True)
    df = pd.read_parquet(DATA_PATH)

    with open(LAYER1_DIR / "events.csv") as f:
        raw_events = list(csv.DictReader(f))
    with open(LAYER1_DIR / "objects.csv") as f:
        all_objects = list(csv.DictReader(f))
    with open(LAYER1_DIR / "snapshots.csv") as f:
        snaps = list(csv.DictReader(f))

    # Map timestamps → bar_index
    ts_to_bi = {}
    for s in snaps:
        try: ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
        except: pass

    # Prices
    prices = {}
    for _, row in df.iterrows():
        bi = ts_to_bi.get(int(row["timestamp_utc"].timestamp() * 1000)
                          if hasattr(row["timestamp_utc"], "timestamp") else 0, -1)
        if bi < 0:  # fallback: scan all
            for _, r in df.iterrows():
                ts = r["timestamp_utc"]
                ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
                bi2 = ts_to_bi.get(ts_ms, -1)
                if bi2 >= 0:
                    prices[bi2] = {"open": float(r["open"]), "high": float(r["high"]),
                                   "low": float(r["low"]), "close": float(r["close"])}
            break
        else:
            prices[bi] = {"open": float(row["open"]), "high": float(row["high"]),
                          "low": float(row["low"]), "close": float(row["close"])}
    else:
        # Normal path: map prices correctly
        prices = {}
        for _, row in df.iterrows():
            ts = row["timestamp_utc"]
            ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
            bi = ts_to_bi.get(ts_ms, -1)
            if bi >= 0:
                prices[bi] = {"open": float(row["open"]), "high": float(row["high"]),
                              "low": float(row["low"]), "close": float(row["close"])}

    # Events by bar
    events_by_bar = defaultdict(list)
    for e in raw_events:
        events_by_bar[int(e["bar_index"])].append(e)

    # Snapshots by bar
    bar_snaps = {int(s["bar_index"]): s for s in snaps}
    bar_indices = sorted(bar_snaps.keys())

    return prices, events_by_bar, bar_snaps, bar_indices, all_objects, ts_to_bi


def build_ob_cache(all_objects, ts_to_bi, events_by_bar, bar_indices):
    """Event-sourced OB cache — O(n)."""
    print("  Mapping OB timestamps...", flush=True)

    for ob in all_objects:
        try:
            af = int(ob.get("active_from", 0))
            act_bi = ts_to_bi.get(af, -1)
            if act_bi == -1 and af > 0:
                st = sorted(k for k in ts_to_bi if k <= af)
                if st: act_bi = ts_to_bi[st[-1]]
            ob["_bar_index"] = act_bi
            ot = int(ob.get("created_at", 0))
            org_bi = ts_to_bi.get(ot, -1)
            if org_bi == -1 and ot > 0:
                st = sorted(k for k in ts_to_bi if k <= ot)
                if st: org_bi = ts_to_bi[st[-1]]
            ob["_origin_bar_index"] = org_bi
        except:
            ob["_bar_index"] = -1

    obs_at_bar = defaultdict(list)
    for ob in all_objects:
        if ob["_bar_index"] >= 0: obs_at_bar[ob["_bar_index"]].append(ob)

    ob_by_id = {o.get("object_id", ""): o for o in all_objects if o.get("object_id", "")}

    lifecycle_by_bar = defaultdict(list)
    for bi, evs in events_by_bar.items():
        for ev in evs:
            if ev.get("event_type", "") in ("OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"):
                lifecycle_by_bar[bi].append(ev)

    print(f"  Building OB cache ({len(bar_indices):,} bars)...", flush=True)
    active_ids = set(); active_ob_cache = {}
    for bi in bar_indices:
        for ob in obs_at_bar.get(bi, []):
            if ob.get("object_id", ""): active_ids.add(ob["object_id"])
        for ev in lifecycle_by_bar.get(bi, []):
            active_ids.discard(ev.get("object_id", ""))
        active_ob_cache[bi] = [ob_by_id[oid] for oid in active_ids
                               if oid in ob_by_id and bi - ob_by_id[oid].get("_bar_index", 0) <= WINDOW]

    avg = sum(len(v) for v in active_ob_cache.values()) // len(active_ob_cache)
    print(f"    ~{avg} avg/bar", flush=True)
    return active_ob_cache


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load ──
    prices, events_by_bar, bar_snaps, bar_indices, all_objects, ts_to_bi = load_data()
    print(f"  Bars: {len(bar_indices):,}  Events: {sum(len(v) for v in events_by_bar.values()):,}")
    active_ob_cache = build_ob_cache(all_objects, ts_to_bi, events_by_bar, bar_indices)

    # ── Run V8 model ──
    print("\nRunning V8_Combined...", flush=True)
    model = V8_Combined()
    intents = []
    n = len(bar_indices)
    t0 = time.time()

    for idx, bi in enumerate(bar_indices):
        orders = model.on_bar(bi, events_by_bar.get(bi, []), bar_snaps.get(bi, {}),
                              active_ob_cache.get(bi, []))
        for o in orders:
            intents.append(OrderIntent(
                setup_id=f"V8_{int(len(intents))}", direction=o.direction,
                order_type="limit", entry_price=o.entry_price,
                entry_zone_top=o.entry_zone_top, entry_zone_bottom=o.entry_zone_bottom,
                stop_loss=o.sl_price, take_profit=o.tp_price,
                signal_bar=o.bar_index, timestamp=o.timestamp,
                valid_until_bar=o.bar_index + 150,
                source=o.model,
            ))
        if (idx + 1) % 70000 == 0:
            print(f"  {idx+1}/{n} bars, {len(intents)} intents", flush=True)

    elapsed = time.time() - t0
    print(f"  Generated {len(intents)} intents in {elapsed:.0f}s", flush=True)

    # ── Execute ──
    print("Simulating orders...", flush=True)
    trades = simulate_orders(intents, prices)
    summary = summarize_trades(trades)
    orders_pw = round(summary["total"] / (len(bar_indices) / (96*5)), 1)

    print(f"\n{'='*60}", flush=True)
    print("V8_COMBINED — 210k bars XAUUSD M15", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  Generated: {len(intents)}")
    print(f"  Filled:    {summary['total']}")
    print(f"  Wins:      {summary['wins']}  Losses: {summary['losses']}")
    print(f"  WR:        {summary['win_rate']}%")
    print(f"  Total R:   {summary['total_r']}")
    print(f"  Avg R:     {summary['avg_r']}")
    print(f"  Open:      {summary['open']}  Timeouts: {summary['timeouts']}")
    print(f"  /week:     {orders_pw}")
    print(f"  Target:    {'✅' if summary['win_rate'] >= 65 and orders_pw >= 3 else '❌'}", flush=True)

    # ── Save results ──
    with open(OUTPUT_DIR / "results.csv", "w") as f:
        w = csv.writer(f)
        w.writerow(["model", "generated", "filled", "wins", "losses", "win_rate", "total_r", "avg_r", "orders_per_week"])
        w.writerow(["V8_COMBINED", len(intents), summary["total"], summary["wins"],
                    summary["losses"], summary["win_rate"], summary["total_r"],
                    summary["avg_r"], orders_pw])

    with open(OUTPUT_DIR / "trades.csv", "w") as f:
        w = csv.writer(f)
        w.writerow(["setup_id", "direction", "signal_bar", "fill_bar", "fill_price",
                     "exit_bar", "exit_price", "exit_reason", "net_r", "holding_bars", "source"])
        for t in trades:
            w.writerow([t.setup_id, "LONG" if t.direction == 1 else "SHORT",
                        t.signal_bar, t.fill_bar, t.fill_price,
                        t.exit_bar, t.exit_price, t.exit_reason,
                        t.net_r, t.holding_bars, t.source])

    print(f"\n[✓] Results → {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
