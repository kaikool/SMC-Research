"""Run Strategy Layer (Layer 2) on full Layer 1 output."""
import sys, os, csv
from pathlib import Path
from collections import Counter
sys.path.insert(0, os.path.dirname(__file__))
from strategy_layer.config import StrategyConfig
from strategy_layer.strategy_runner import StrategyRunner

layer1_dir = Path("output_full/layer1")
out_dir = Path("output_full")
out_dir.mkdir(parents=True, exist_ok=True)

# Count events
with open(layer1_dir / "events.csv") as f:
    events = list(csv.DictReader(f))
event_types = Counter(r["event_type"] for r in events)
print(f"Events loaded: {len(events)}")
print(f"  Sweeps: {event_types.get('LIQUIDITY_SWEEP', 0)}")
print(f"  BOS: {event_types.get('SWING_BOS_BULLISH', 0) + event_types.get('SWING_BOS_BEARISH', 0)}")
print(f"  CHOCH: {sum(v for k,v in event_types.items() if 'CHOCH' in k)}")
print(f"  OB Created: {event_types.get('ORDER_BLOCK_CREATED', 0)}")

with open(layer1_dir / "snapshots.csv") as f:
    snaps = list(csv.DictReader(f))
print(f"Snapshots loaded: {len(snaps)}")
print(f"  Bars: {snaps[0]['bar_index']} → {snaps[-1]['bar_index']}")

with open(layer1_dir / "objects.csv") as f:
    objs = list(csv.DictReader(f))
print(f"Objects loaded: {len(objs)}")

# Run strategy
cfg = StrategyConfig()
cfg.events_path = str(layer1_dir / "events.csv")
cfg.snapshots_path = str(layer1_dir / "snapshots.csv")
cfg.objects_path = str(layer1_dir / "objects.csv")
cfg.symbol = "XAUUSD"
cfg.timeframe = "15"
cfg.session_enabled = False
cfg.name = "sweep_choch_ob_full"
cfg.allow_long = True
cfg.allow_short = True
cfg.max_bars_sweep_to_choch = 50
cfg.max_bars_wait_entry = 50
cfg.sl_type = "sweep_extreme"
cfg.sl_buffer_atr_ratio = 20.0
cfg.tp_type = "fixed_r"
cfg.tp_r_multiple = 2.0
cfg.min_rr_ratio = 1.0

print("\nRunning Strategy Layer...")
runner = StrategyRunner(cfg)
runner.load_layer1(cfg.events_path, cfg.snapshots_path, cfg.objects_path)
stats = runner.run()

print(f"\n{'='*50}")
print(f"STRATEGY RESULTS — {stats['strategy']}")
print(f"{'='*50}")
print(f"  Bars: {stats['total_decisions']}")
print(f"  Setups: {stats['total_setups']}")
print(f"  Orders: {stats['total_orders']}")
for status, count in sorted(stats.get("status_counts", {}).items()):
    print(f"    {status}: {count}")

out_paths = runner.export_csv(str(out_dir))
print(f"\n  Output files:")
for name, path in out_paths.items():
    print(f"    {name} → {path}")

if runner.order_intents:
    print(f"\n  Orders ({len(runner.order_intents)}):")
    for o in runner.order_intents:
        d = "LONG" if o.direction == 1 else "SHORT"
        print(f"    {o.setup_id}: {d} {o.order_type} @ {o.entry_price:.2f} | SL={o.sl_price:.2f} TP={o.tp_price:.2f} | dist={abs(o.entry_price-o.sl_price):.2f}")
else:
    # Debug: check rejection reasons
    reasons = Counter()
    for d in runner.decision_logger.decisions[:2000]:
        if d.decision == "REJECT_SETUP" and d.failed_reasons:
            for r in d.failed_reasons:
                reasons[r] += 1
    print(f"\n  Top rejection reasons (first 2000 decisions):")
    for reason, count in reasons.most_common(10):
        print(f"    {reason}: {count}")
