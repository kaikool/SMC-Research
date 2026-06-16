"""
Pipeline tổng hợp: test 5 models + PnL trên Layer 1 output (FVG).
Chạy: python test_all.py [--dir output_full_fvg] [--bars N]
"""
import csv, sys, os, argparse, time
from pathlib import Path
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(__file__))
os.environ["PYTHONUNBUFFERED"] = "1"

# Increase CSV field size limit
csv.field_size_limit(10 * 1024 * 1024)  # 10MB

from strategy_layer.entry_strategies import (
    Model1_EQHEQL_Sweep_InternalCHOCH,
    Model2_FVG_PremiumDiscount,
    Model3_PureSwingOB,
    Model4_IntBOS_OB,
    Model5_StrongDefense,
    Model6_OB_Retest,
    Model7_IntCHOCH_OB,
    Model8_Sweep_OB,
)
from strategy_layer.pnl_calculator import load_bar_prices, calculate_pnl


WINDOW = 200  # OB cache window (bars) — tăng lên cho fallback OB
SAMPLE_BARS = 50000  # last 50k bars


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="output_full_fvg", help="Layer 1 output dir")
    parser.add_argument("--bars", type=int, default=SAMPLE_BARS)
    args = parser.parse_args()
    
    layer1_dir = Path(args.dir) / "layer1"
    out_dir = Path(args.dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading data from {layer1_dir}...")
    
    # ── Snapshots ──────────────────────────────────────────
    with open(layer1_dir / "snapshots.csv") as f:
        all_snaps = list(csv.DictReader(f))
    print(f"  Snapshots: {len(all_snaps)}")
    
    bar_snapshots = {int(s["bar_index"]): s for s in all_snaps[-args.bars:]}
    bar_indices = sorted(bar_snapshots.keys())
    min_bar = bar_indices[0]
    max_bar = bar_indices[-1]
    print(f"  Bars: {min_bar} → {max_bar} ({len(bar_indices)})")
    
    # ── Events ─────────────────────────────────────────────
    with open(layer1_dir / "events.csv") as f:
        events_by_bar = defaultdict(list)
        for row in csv.DictReader(f):
            bi = int(row["bar_index"])
            if min_bar <= bi <= max_bar:
                events_by_bar[bi].append(row)
    print(f"  Events in range: {sum(len(v) for v in events_by_bar.values())}")
    
    # ── Objects ────────────────────────────────────────────
    with open(layer1_dir / "objects.csv") as f:
        all_objects = list(csv.DictReader(f))
    
    # Map timestamp→bar_index for objects
    ts_to_bar = {}
    for s in all_snaps:
        try:
            ts_to_bar[int(s["timestamp"])] = int(s["bar_index"])
        except:
            pass
    
    for ob in all_objects:
        try:
            ob_ts = int(ob.get("created_at", 0))
            bi = ts_to_bar.get(ob_ts, -1)
            if bi == -1 and ob_ts > 0:
                sorted_ts = sorted(k for k in ts_to_bar.keys() if k <= ob_ts)
                if sorted_ts:
                    bi = ts_to_bar[sorted_ts[-1]]
            ob["_bar_index"] = bi
        except:
            ob["_bar_index"] = -1
    
    objects_by_bar = defaultdict(list)
    for ob in all_objects:
        bi = ob.get("_bar_index", -1)
        if bi >= 0:
            objects_by_bar[bi].append(ob)
    print(f"  Objects: {len(all_objects)} ({sum(len(v) for v in objects_by_bar.values())} mapped)")
    
    # ── OB cache (sliding window) ──────────────────────────
    active_ob_cache = {}
    recent_obs = []
    for bi in range(min_bar, max_bar + 1):
        for ob in objects_by_bar.get(bi, []):
            recent_obs.append(ob)
        recent_obs = [ob for ob in recent_obs if bi - ob.get("_bar_index", 0) <= WINDOW]
        active_ob_cache[bi] = list(recent_obs)
    avg_obs = sum(len(v) for v in active_ob_cache.values()) // max(len(active_ob_cache), 1)
    print(f"  OB cache: ~{avg_obs} avg/bar (window={WINDOW})")
    
    # ── Load OHLC prices ───────────────────────────────────
    print("\nLoading OHLC prices from parquet...")
    prices = load_bar_prices(str(layer1_dir / "events.csv"), str(layer1_dir / "snapshots.csv"))
    print(f"  Price bars: {len(prices)}")
    
    # ── Initialize models ──────────────────────────────────
    models = [
        ("M1: EQH/EQL → Internal CHOCH → Internal OB", Model1_EQHEQL_Sweep_InternalCHOCH()),
        ("M2: FVG → Premium/Discount Zone", Model2_FVG_PremiumDiscount()),
        ("M3: Pure Swing OB at MTF Level", Model3_PureSwingOB()),
        ("M4: Internal BOS → Internal OB", Model4_IntBOS_OB()),
        ("M5: Strong High/Low → Swing OB", Model5_StrongDefense()),
        ("M6: Simple OB Retest (no conditions)", Model6_OB_Retest()),
        ("M7: Internal CHOCH → Internal OB (no sweep)", Model7_IntCHOCH_OB()),
        ("M8: Liquidity Sweep → OB (skip CHOCH)", Model8_Sweep_OB()),
    ]
    
    # ── Run all models ─────────────────────────────────────
    all_results = []
    model_orders = {}
    
    for model_name, model in models:
        print(f"\n{'='*60}")
        print(f"RUNNING: {model_name}")
        
        orders = []
        for bi in bar_indices:
            bar_events = events_by_bar.get(bi, [])
            snapshot = bar_snapshots.get(bi, {})
            obs = active_ob_cache.get(bi, [])
            bar_orders = model.on_bar(bi, bar_events, snapshot, obs)
            orders.extend(bar_orders)
        
        model_orders[model.name] = orders
        print(f"  Orders: {len(orders)}")
        
        if orders:
            dirs = Counter(o.direction for o in orders)
            print(f"  LONG: {dirs.get(1, 0)}, SHORT: {dirs.get(-1, 0)}")
            
            # PnL calculation
            pnl = calculate_pnl(orders, prices, max_bars=200)
            print(f"\n  ── PnL ──")
            print(f"  Wins: {pnl['wins']}, Losses: {pnl['losses']}, Open: {pnl['open']}")
            print(f"  Win Rate: {pnl['win_rate']}%")
            print(f"  Total R: {pnl['total_r']}")
            print(f"  Avg R: {pnl['avg_r']}")
            print(f"  Profit Factor: {pnl['profit_factor']}")
            print(f"  Avg Bars Held: {pnl['avg_bars_held']}")
            
            all_results.append((model.name, pnl))
            
            # Show sample wins/losses
            wins = [r for r in pnl["results"] if r["result"] == "win"]
            losses = [r for r in pnl["results"] if r["result"] == "loss"]
            
            if wins:
                print(f"\n  Sample wins:")
                for w in wins[:5]:
                    print(f"    {w['setup_id']}: {w['direction']} entry={w['entry']:.2f} → {w['exit_price']:.2f} ({w['bars_held']} bars, R={w['r_multiple']:.2f})")
            if losses:
                print(f"\n  Sample losses:")
                for l_ in losses[:5]:
                    print(f"    {l_['setup_id']}: {l_['direction']} entry={l_['entry']:.2f} → SL={l_['sl']:.2f} ({l_['bars_held']} bars)")
        else:
            print(f"  (no data for this model)")
    
    # ── Final summary ──────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"{'='*60}")
    print(f"FINAL SUMMARY")
    print(f"{'='*60}")
    
    total_orders = sum(len(v) for v in model_orders.values())
    print(f"\nTotal orders across all models: {total_orders}")
    
    print(f"\n{'Model':<35} {'Orders':>7} {'Wins':>5} {'Losses':>6} {'WR':>6} {'Total R':>8} {'PF':>7}")
    print(f"{'-'*35} {'-'*7} {'-'*5} {'-'*6} {'-'*6} {'-'*8} {'-'*7}")
    
    total_wins = 0
    total_losses = 0
    total_r = 0.0
    total_closed = 0
    
    for model_name, pnl in all_results:
        short = model_name.split(":")[0]
        wr = f"{pnl['win_rate']}%" if pnl['closed'] > 0 else "N/A"
        pf = f"{pnl['profit_factor']:.2f}" if pnl['losses'] > 0 else "∞"
        print(f"{short:<35} {pnl['total_orders']:>7} {pnl['wins']:>5} {pnl['losses']:>6} {wr:>6} {pnl['total_r']:>8.2f} {pf:>7}")
        total_wins += pnl['wins']
        total_losses += pnl['losses']
        total_r += pnl['total_r']
        total_closed += pnl['closed']
    
    total_wr = round(total_wins / total_closed * 100, 1) if total_closed > 0 else 0
    print(f"{'='*35} {'='*7} {'='*5} {'='*6} {'='*6} {'='*8} {'='*7}")
    print(f"{'TOTAL':<35} {total_orders:>7} {total_wins:>5} {total_losses:>6} {total_wr:>6} {total_r:>8.2f}")
    
    # Export
    csv_path = out_dir / "pnl_summary.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "orders", "wins", "losses", "open", "win_rate", "total_r", "avg_r", "profit_factor", "avg_bars"])
        for model_name, pnl in all_results:
            w.writerow([
                model_name.split(":")[0],
                pnl['total_orders'], pnl['wins'], pnl['losses'], pnl['open'],
                pnl['win_rate'], pnl['total_r'], pnl['avg_r'],
                pnl['profit_factor'], pnl['avg_bars_held']
            ])
    print(f"\nExport: {csv_path}")
    
    # Export all orders with PnL
    orders_path = out_dir / "all_orders_pnl.csv"
    with open(orders_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["setup_id", "model", "direction", "entry", "sl", "tp", "result", "exit_price", "bars_held", "r_multiple", "reason"])
        for model_name, pnl in all_results:
            for r in pnl["results"]:
                w.writerow([
                    r["setup_id"], r["model"], r["direction"],
                    f"{r['entry']:.2f}", f"{r['sl']:.2f}", f"{r['tp']:.2f}",
                    r["result"], f"{r['exit_price']:.2f}",
                    r["bars_held"], f"{r['r_multiple']:.2f}", r["reason"],
                ])
    print(f"Export: {orders_path}")
    
    return all_results


if __name__ == "__main__":
    main()
