"""
Final pipeline: optimized 3 models + execution layer + report.
"""
import csv, sys, os
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(__file__))
os.environ["PYTHONUNBUFFERED"] = "1"
csv.field_size_limit(10 * 1024 * 1024)

# Only use the 3 winning models
from strategy_layer.entry_strategies import (
    Model1_EQHEQL_Sweep_InternalCHOCH,
    Model5_StrongDefense,
    Model7_IntCHOCH_OB,
)

WINDOW = 200
SAMPLE_BARS = 50000

def main():
    layer1_dir = Path("output_full_fvg/layer1")
    out_dir = Path("output_full_fvg")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("Loading data...")
    with open(layer1_dir / "snapshots.csv") as f:
        all_snaps = list(csv.DictReader(f))
    bar_snapshots = {int(s["bar_index"]): s for s in all_snaps[-SAMPLE_BARS:]}
    bar_indices = sorted(bar_snapshots.keys())
    print(f"  Bars: {min(bar_indices)} → {max(bar_indices)} ({len(bar_indices)})")
    
    with open(layer1_dir / "events.csv") as f:
        events_by_bar = defaultdict(list)
        for row in csv.DictReader(f):
            bi = int(row["bar_index"])
            if bi in bar_snapshots: events_by_bar[bi].append(row)
    print(f"  Events: {sum(len(v) for v in events_by_bar.values())}")
    
    with open(layer1_dir / "objects.csv") as f:
        all_objects = list(csv.DictReader(f))
    
    ts_to_bar = {}
    for s in all_snaps:
        try: ts_to_bar[int(s["timestamp"])] = int(s["bar_index"])
        except: pass
    
    for ob in all_objects:
        try:
            ob_ts = int(ob.get("created_at", 0))
            bi = ts_to_bar.get(ob_ts, -1)
            if bi == -1 and ob_ts > 0:
                sorted_ts = sorted(k for k in ts_to_bar.keys() if k <= ob_ts)
                if sorted_ts: bi = ts_to_bar[sorted_ts[-1]]
            ob["_bar_index"] = bi
        except: ob["_bar_index"] = -1
    
    objects_by_bar = defaultdict(list)
    for ob in all_objects:
        bi = ob.get("_bar_index", -1)
        if bi >= 0: objects_by_bar[bi].append(ob)
    
    active_ob_cache = {}
    recent_obs = []
    for bi in bar_indices:
        for ob in objects_by_bar.get(bi, []): recent_obs.append(ob)
        recent_obs = [ob for ob in recent_obs if bi - ob.get("_bar_index", 0) <= WINDOW]
        active_ob_cache[bi] = list(recent_obs)
    print(f"  OB cache: ~{sum(len(v) for v in active_ob_cache.values())//len(active_ob_cache)} avg/bar")
    
    # Load prices for PnL simulation
    print("Loading prices...")
    import pandas as pd
    df = pd.read_parquet("D:/PHUCTD/SMC Research/data/XAUUSD_15m.parquet")
    prices = {}
    for _, row in df.iterrows():
        ts = row["timestamp_utc"]
        ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, 'timestamp') else 0
        bi = ts_to_bar.get(ts_ms, -1)
        if bi >= 0:
            prices[bi] = {"open": float(row["open"]), "high": float(row["high"]), 
                         "low": float(row["low"]), "close": float(row["close"])}
    print(f"  Prices: {len(prices)} bars")
    
    # Models
    models = [
        ("M1_EQHEQL_CHOCH_OB", Model1_EQHEQL_Sweep_InternalCHOCH()),
        ("M5_STRONG_DEFENSE", Model5_StrongDefense()),
        ("M7_INTCHOCH_OB", Model7_IntCHOCH_OB()),
    ]
    
    all_orders = []
    model_results = {}
    
    for model_name, model in models:
        orders = []
        for bi in bar_indices:
            bar_events = events_by_bar.get(bi, [])
            snapshot = bar_snapshots.get(bi, {})
            obs = active_ob_cache.get(bi, [])
            bar_orders = model.on_bar(bi, bar_events, snapshot, obs)
            orders.extend(bar_orders)
        
        print(f"\n{model_name}: {len(orders)} orders")
        
        # PnL simulation
        wins = 0; losses = 0; total_r = 0.0; win_r = 0.0; loss_r = 0.0
        results = []
        
        for o in orders:
            # Simulate forward
            entry_bar = o.bar_index
            direction = o.direction
            entry = o.entry_price
            sl = o.sl_price
            tp = o.tp_price
            
            result = "open"
            exit_price = entry
            bars_held = 0
            r_mult = 0.0
            
            risk = abs(entry - sl) if sl != entry else 1
            reward = abs(tp - entry)
            
            for offset in range(1, 201):
                bi = entry_bar + offset
                bar = prices.get(bi)
                if not bar:
                    result = "open"; break
                
                if direction == 1:  # LONG
                    if bar["low"] <= sl:
                        result = "loss"; exit_price = sl; bars_held = offset; r_mult = -1.0; break
                    if bar["high"] >= tp:
                        result = "win"; exit_price = tp; bars_held = offset; r_mult = reward/risk; break
                else:  # SHORT
                    if bar["high"] >= sl:
                        result = "loss"; exit_price = sl; bars_held = offset; r_mult = -1.0; break
                    if bar["low"] <= tp:
                        result = "win"; exit_price = tp; bars_held = offset; r_mult = reward/risk; break
            else:
                last = prices.get(entry_bar + 200, {})
                lc = last.get("close", entry) if last else entry
                result = "timeout"
                if direction == 1: r_mult = (lc - entry) / risk
                else: r_mult = (entry - lc) / risk
            
            if result == "win": wins += 1; win_r += r_mult; total_r += r_mult
            elif result == "loss": losses += 1; loss_r += abs(r_mult); total_r += r_mult
            results.append(result)
        
        closed = wins + losses
        wr = wins/closed*100 if closed > 0 else 0
        pf = win_r/loss_r if loss_r > 0 else float('inf')
        
        model_results[model_name] = {
            "orders": len(orders), "wins": wins, "losses": losses,
            "wr": round(wr, 1), "total_r": round(total_r, 2),
            "pf": round(pf, 2),
        }
        print(f"  Wins: {wins}, Losses: {losses}, WR: {wr:.1f}%")
        print(f"  Total R: {total_r:.2f}, PF: {pf:.2f}")
        
        all_orders.extend(orders)
    
    # ── Summary ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"FINAL RESULTS — 3 Models (optimized)")
    print(f"{'='*60}")
    print(f"{'Model':<25} {'Orders':>7} {'Wins':>5} {'Losses':>6} {'WR':>6} {'Total R':>8} {'PF':>7}")
    print(f"{'-'*25} {'-'*7} {'-'*5} {'-'*6} {'-'*6} {'-'*8} {'-'*7}")
    
    t_orders = 0; t_wins = 0; t_losses = 0; t_r = 0.0
    for mn, mr in sorted(model_results.items()):
        s = mn.split("_")[0]
        print(f"{s:<25} {mr['orders']:>7} {mr['wins']:>5} {mr['losses']:>6} {mr['wr']:>6}% {mr['total_r']:>8.2f} {mr['pf']:>7}")
        t_orders += mr['orders']; t_wins += mr['wins']; t_losses += mr['losses']; t_r += mr['total_r']
    
    wr_all = round(t_wins/(t_wins+t_losses)*100, 1) if (t_wins+t_losses) > 0 else 0
    print(f"{'='*25} {'='*7} {'='*5} {'='*6} {'='*6} {'='*8} {'='*7}")
    print(f"{'TOTAL':<25} {t_orders:>7} {t_wins:>5} {t_losses:>6} {wr_all:>6}% {t_r:>8.2f}")
    
    # Weekly projection
    weeks = len(bar_indices) / (96 * 5)  # ~96 bars/day × 5 days
    orders_per_week = t_orders / weeks if weeks > 0 else 0
    print(f"\n  Data span: ~{weeks:.1f} weeks")
    print(f"  Orders/week: {orders_per_week:.1f}")
    print(f"  Target: 3/week → {'✅' if orders_per_week >= 3 else '❌'}")
    print(f"  Target WR >65% → {'✅' if wr_all > 65 else '❌'}")
    
    # Export report
    report_path = out_dir / "final_report.csv"
    with open(report_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "orders", "wins", "losses", "win_rate", "total_r", "profit_factor"])
        for mn, mr in sorted(model_results.items()):
            w.writerow([mn, mr["orders"], mr["wins"], mr["losses"], mr["wr"], mr["total_r"], mr["pf"]])
    print(f"\nReport: {report_path}")

if __name__ == "__main__":
    main()
