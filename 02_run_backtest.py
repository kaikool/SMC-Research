#!/usr/bin/env python3
"""
[Step 2/4] Backtest 3 SMC models — vectorbt-powered PnL simulation.
Chạy sau 01_run_layer1.py.

3 models:
  M1  EQH/EQL → Int CHOCH → Int OB
  M5  Strong Defense (swing H/L → swing OB)
  M7  Int CHOCH → Int OB

Key improvements over v1:
  - OB cache: pre-grouped by bar (O(n_bars) not O(n_bars × n_objects))
  - vectorbt Portfolio for SL/TP simulation (vectorized, not per-order loop)
  - Cost model: spread 0.30 + slippage 0.10
  - Limit fill: price checks using pandas rolling window

Output: output/backtest/results.csv + orders.csv + console summary
"""
import sys, os, csv
from pathlib import Path
from collections import defaultdict
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)
csv.field_size_limit(10 * 1024 * 1024)

import numpy as np
import pandas as pd
import vectorbt as vbt

from strategy_layer.entry_strategies import (
    Model1_EQHEQL_Sweep_InternalCHOCH,
    Model5_StrongDefense,
    Model7_IntCHOCH_OB,
)

DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
LAYER1_DIR = Path("output") / "layer1"
OUTPUT_DIR = Path("output") / "backtest"
WINDOW = 200  # OB cache window (bars)

# Cost model (XAUUSD approximate, in price units)
SPREAD = 0.30
SLIPPAGE = 0.10
MAX_FILL_WAIT = 150  # bars to wait for limit fill


def load_prices_and_bars():
    """Load parquet prices + snapshots, align by bar_index."""
    print("  Loading parquet...", flush=True)
    df = pd.read_parquet(DATA_PATH)

    print("  Loading snapshots...", flush=True)
    with open(LAYER1_DIR / "snapshots.csv") as f:
        snaps = list(csv.DictReader(f))

    ts_to_bi = {}
    for s in snaps:
        try:
            ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
        except:
            pass

    # Build bar_index-indexed price arrays
    prices = {}  # bi -> {open, high, low, close}
    for _, row in df.iterrows():
        ts = row["timestamp_utc"]
        ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
        bi = ts_to_bi.get(ts_ms, -1)
        if bi >= 0:
            prices[bi] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }

    return prices, snaps, ts_to_bi


def build_active_ob_cache(all_objects, ts_to_bi, events_by_bar, bar_indices):
    """Build event-sourced active OB cache — O(n_bars), not O(n_bars × n_objects).

    1. Map timestamps → bar_index for each OB (_bar_index from active_from)
    2. Pre-group OBs by activation bar
    3. Bar loop: add OBs activating at this bar, remove dying OBs via lifecycle events
    """
    print("  Mapping OB timestamps...", flush=True)

    # Pre-compute _bar_index for each OB from active_from timestamp
    for ob in all_objects:
        try:
            af = int(ob.get("active_from", 0))
            act_bi = ts_to_bi.get(af, -1)
            if act_bi == -1 and af > 0:
                st = sorted(k for k in ts_to_bi if k <= af)
                if st:
                    act_bi = ts_to_bi[st[-1]]
            ob["_bar_index"] = act_bi

            # Also origin bar (created_at) for debugging
            ot = int(ob.get("created_at", 0))
            org_bi = ts_to_bi.get(ot, -1)
            if org_bi == -1 and ot > 0:
                st = sorted(k for k in ts_to_bi if k <= ot)
                if st:
                    org_bi = ts_to_bi[st[-1]]
            ob["_origin_bar_index"] = org_bi
        except:
            ob["_bar_index"] = -1

    # Pre-group by activation bar
    obs_at_bar = defaultdict(list)
    for ob in all_objects:
        act_bi = ob.get("_bar_index", -1)
        if act_bi >= 0:
            obs_at_bar[act_bi].append(ob)

    # Index by object_id for fast lookup
    ob_by_id = {}
    for ob in all_objects:
        oid = ob.get("object_id", "")
        if oid:
            ob_by_id[oid] = ob

    # Lifecycle events (OB_MITIGATED, OB_INVALIDATED, OB_EXPIRED)
    lifecycle_events_by_bar = defaultdict(list)
    for bi, evs in events_by_bar.items():
        for ev in evs:
            if ev.get("event_type", "") in ("OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"):
                lifecycle_events_by_bar[bi].append(ev)

    print(f"  Building event-sourced OB cache ({len(bar_indices):,} bars)...", flush=True)
    active_ob_ids = set()
    active_ob_cache = {}
    for bi in bar_indices:
        # OBs becoming active at this bar
        for ob in obs_at_bar.get(bi, []):
            oid = ob.get("object_id", "")
            if oid:
                active_ob_ids.add(oid)

        # OBs dying at this bar (lifecycle)
        for ev in lifecycle_events_by_bar.get(bi, []):
            oid = ev.get("object_id", "")
            active_ob_ids.discard(oid)

        # Build bar's active OB dict list (fast: only scanning live set)
        active_ob_cache[bi] = [
            ob_by_id[oid] for oid in active_ob_ids
            if oid in ob_by_id
            and bi - ob_by_id[oid].get("_bar_index", 0) <= WINDOW
        ]

    total_live = sum(len(v) for v in active_ob_cache.values())
    print(f"    ~{total_live // len(active_ob_cache)} avg/bar", flush=True)
    return active_ob_cache


def simulate_limit_fills(orders, prices):
    """Determine fill bar for each limit order using price matching.

    For each order, scans up to MAX_FILL_WAIT bars forward.
    Returns list of (order, fill_bar) for filled orders, and list of unfilled orders.
    """
    filled = []  # (order, fill_bar)
    unfilled = []
    for o in orders:
        entry = o.entry_price
        direction = o.direction
        fill_bar = None
        for offset in range(1, MAX_FILL_WAIT + 1):
            bi = o.bar_index + offset
            bar = prices.get(bi)
            if not bar:
                break
            if direction == 1:  # Long: price dips to entry
                if bar["low"] <= entry:
                    fill_bar = bi
                    break
            else:  # Short: price rises to entry
                if bar["high"] >= entry:
                    fill_bar = bi
                    break
        if fill_bar is not None:
            filled.append((o, fill_bar))
        else:
            unfilled.append(o)
    return filled, unfilled


def analyze_vectorbt(model_name, filled_orders, prices, bar_indices):
    """Simulate filled orders using vectorbt Portfolio with SL/TP stops.

    Runs vectorbt TWICE: once for longs, once for shorts (avoids direction='both' quirks).
    Uses only OHLC arrays, no explicit short_entries.
    """
    if not filled_orders:
        return {"model": model_name, "generated": 0, "filled": 0,
                "wins": 0, "losses": 0, "win_rate": 0.0, "total_r": 0.0}

    min_bi = min(bar_indices)
    max_bi = max(bar_indices)
    n = max_bi - min_bi + 1

    # Build OHLC arrays from price dict
    oa = np.full(n, np.nan)
    ha = np.full(n, np.nan)
    la = np.full(n, np.nan)
    ca = np.full(n, np.nan)
    for bi in bar_indices:
        idx = bi - min_bi
        bar = prices.get(bi)
        if bar:
            oa[idx] = bar["open"]
            ha[idx] = bar["high"]
            la[idx] = bar["low"]
            ca[idx] = bar["close"]

    def run_vbt(direction):
        """Run vectorbt for one direction."""
        sgl = np.zeros(n, dtype=bool)
        prc = np.full(n, np.nan)
        slv = np.full(n, np.nan)
        tpv = np.full(n, np.nan)

        for o, fill_bar in filled_orders:
            if o.direction != (1 if direction == 'longonly' else -1):
                continue
            idx = fill_bar - min_bi
            if idx < 0 or idx >= n:
                continue
            entry_cost = o.entry_price + (SPREAD / 2 + SLIPPAGE) if direction == 'longonly' else \
                         o.entry_price - (SPREAD / 2 + SLIPPAGE)
            sgl[idx] = True
            prc[idx] = entry_cost
            if direction == 'longonly':
                slv[idx] = max(0.001, (entry_cost - o.sl_price) / entry_cost)
                tpv[idx] = max(0.001, (o.tp_price - entry_cost) / entry_cost)
            else:
                slv[idx] = max(0.001, (o.sl_price - entry_cost) / entry_cost)
                tpv[idx] = max(0.001, (entry_cost - o.tp_price) / entry_cost)

        # Forward-fill stop values so they persist beyond entry bar
        for i in range(1, n):
            if np.isnan(slv[i]) and not np.isnan(slv[i-1]):
                slv[i] = slv[i-1]
                tpv[i] = tpv[i-1]

        if sgl.sum() == 0:
            return {"wins": 0, "losses": 0, "total_r": 0.0, "filled": 0}

        try:
            pf = vbt.Portfolio.from_signals(
                close=ca, entries=sgl, price=prc,
                sl_stop=slv, tp_stop=tpv,
                open=oa, high=ha, low=la,
                direction=direction,
                init_cash=10000 / (2 if direction == 'longonly' and any(o.direction == -1 for o, _ in filled_orders) else 1),
                freq='15min',
            )
        except Exception as e:
            print(f"      ⚠️ vbt error ({direction}): {e}", flush=True)
            return {"wins": 0, "losses": 0, "total_r": 0.0, "filled": 0}

        trades = pf.trades
        if trades is None or len(trades) == 0:
            return {"wins": 0, "losses": 0, "total_r": 0.0, "filled": int(sgl.sum())}

        wins = int((trades.pnl > 0).sum())
        losses = int((trades.pnl <= 0).sum())
        total_r = 0.0
        for i in range(len(trades)):
            entry_idx = int(trades.entry_idx.values[i])
            if entry_idx < n and not np.isnan(prc[entry_idx]) and slv[entry_idx] > 0:
                risk = prc[entry_idx] * slv[entry_idx]
                total_r += trades.pnl.values[i] / risk if risk > 0 else 0

        return {"wins": wins, "losses": losses, "total_r": total_r, "filled": int(sgl.sum())}

    long_res = run_vbt('longonly')
    short_res = run_vbt('shortonly')

    total_wins = long_res["wins"] + short_res["wins"]
    total_losses = long_res["losses"] + short_res["losses"]
    total_closed = total_wins + total_losses

    return {
        "model": model_name,
        "generated": long_res["filled"] + short_res["filled"] + 0,
        "filled": long_res["filled"] + short_res["filled"],
        "wins": total_wins,
        "losses": total_losses,
        "win_rate": round(total_wins / total_closed * 100, 1) if total_closed > 0 else 0,
        "total_r": round(long_res["total_r"] + short_res["total_r"], 2),
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load Layer 1 ───────────────────────────
    print("Loading Layer 1 data...", flush=True)
    prices, snaps, ts_to_bi = load_prices_and_bars()

    with open(LAYER1_DIR / "events.csv") as f:
        events_by_bar = defaultdict(list)
        for row in csv.DictReader(f):
            events_by_bar[int(row["bar_index"])].append(row)
    print(f"  Events: {sum(len(v) for v in events_by_bar.values()):,}")

    with open(LAYER1_DIR / "objects.csv") as f:
        all_objects = list(csv.DictReader(f))
    print(f"  Objects: {len(all_objects):,}")

    bar_snaps = {}
    with open(LAYER1_DIR / "snapshots.csv") as f:
        for s in csv.DictReader(f):
            bar_snaps[int(s["bar_index"])] = s
    bar_indices = sorted(bar_snaps.keys())
    print(f"  Bars: {len(bar_indices):,}")

    # ── Build OB cache ─────────────────────────
    active_ob_cache = build_active_ob_cache(all_objects, ts_to_bi, events_by_bar, bar_indices)

    # ── Run 3 models ───────────────────────────
    models = [
        ("M1_EQHEQL_CHOCH_OB", Model1_EQHEQL_Sweep_InternalCHOCH()),
        ("M5_STRONG_DEFENSE", Model5_StrongDefense()),
        ("M7_INTCHOCH_OB", Model7_IntCHOCH_OB()),
    ]

    all_results = []
    combined_orders = []

    print("\n" + "=" * 60, flush=True)
    print("RUNNING 3 MODELS — 210k bars", flush=True)
    print("=" * 60, flush=True)

    for model_name, model in models:
        orders = []
        n = len(bar_indices)
        for idx, bi in enumerate(bar_indices):
            bar_orders = model.on_bar(
                bi,
                events_by_bar.get(bi, []),
                bar_snaps.get(bi, {}),
                active_ob_cache.get(bi, []),
            )
            orders.extend(bar_orders)
            if (idx + 1) % 70000 == 0:
                print(f"  {model_name}: {idx+1}/{n} bars, {len(orders)} orders", flush=True)

        print(f"  {model_name}: {len(orders)} orders generated", flush=True)

        # ── Limit fill simulation ─────────────
        filled, unfilled = simulate_limit_fills(orders, prices)
        print(f"    Filled: {len(filled)}, Unfilled: {len(unfilled)}", flush=True)

        # ── vectorbt simulation ───────────────
        result = analyze_vectorbt(model_name, filled, prices, bar_indices)
        result["generated"] = len(orders)
        result["unfilled"] = len(unfilled)
        result["open_at_end"] = 0  # vectorbt handles this
        result["timeouts"] = 0
        all_results.append(result)
        combined_orders.extend(orders)

        print(f"    WR: {result['win_rate']}%  |  Total R: {result['total_r']}  |  Filled: {result['filled']}", flush=True)

    # ── Summary ─────────────────────────────────
    t_gen = sum(r["generated"] for r in all_results)
    t_fill = sum(r["filled"] for r in all_results)
    t_wins = sum(r["wins"] for r in all_results)
    t_losses = sum(r["losses"] for r in all_results)
    t_r = sum(r["total_r"] for r in all_results)
    total_closed = t_wins + t_losses
    wr_all = round(t_wins / total_closed * 100, 1) if total_closed > 0 else 0
    orders_pw = round(total_closed / (len(bar_indices) / (96*5)), 1) if total_closed > 0 else 0

    print("\n" + "=" * 60, flush=True)
    print("FINAL RESULTS — 3 Models, 210k bars XAUUSD M15", flush=True)
    print("=" * 60, flush=True)
    print(f"{'Model':<25} {'Gen':>5} {'Fill':>5} {'W':>5} {'L':>5} {'WR':>6} {'Total R':>8}", flush=True)
    print("-" * 60, flush=True)
    for r in all_results:
        print(f"{r['model']:<25} {r['generated']:>5} {r['filled']:>5} {r['wins']:>5} {r['losses']:>5} {r['win_rate']:>6}% {r['total_r']:>8.2f}", flush=True)
    print("=" * 60, flush=True)
    print(f"{'TOTAL':<25} {t_gen:>5} {t_fill:>5} {t_wins:>5} {t_losses:>5} {wr_all:>6}% {t_r:>8.2f}", flush=True)
    print(f"\n  Orders/week: {orders_pw}  {'✅ target ≥ 3' if orders_pw >= 3 else '❌ target ≥ 3'}", flush=True)
    print(f"  WR: {wr_all}%  {'✅ target > 65%' if wr_all > 65 else '❌ target > 65%'}", flush=True)

    # ── CSV export ──────────────────────────────
    fieldnames = ["model", "generated", "filled", "unfilled",
                  "wins", "losses", "win_rate", "total_r"]
    out_path = OUTPUT_DIR / "results.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_results:
            w.writerow({k: r.get(k, 0) for k in fieldnames})
    print(f"\n  Report: {out_path}", flush=True)

    # Export all orders (for charting / debugging)
    orders_path = OUTPUT_DIR / "orders.csv"
    with open(orders_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "direction", "entry", "sl", "tp",
                     "entry_zone_top", "entry_zone_bottom", "reason", "bar_index"])
        for o in combined_orders:
            w.writerow([o.model, "LONG" if o.direction == 1 else "SHORT",
                        o.entry_price, o.sl_price, o.tp_price,
                        o.entry_zone_top, o.entry_zone_bottom,
                        o.reason, o.bar_index])
    print(f"  Orders: {orders_path} ({len(combined_orders)} orders)", flush=True)

    print(f"\n[✓] Backtest → {OUTPUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
