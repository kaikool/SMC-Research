#!/usr/bin/env python
"""
Run SMC Event Engine + Strategy Layer on real XAUUSD 15m parquet data.
"""
import argparse
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

from smc_event_engine.data_loader import load_bars_from_parquet
from smc_event_engine.config import EngineConfig
from smc_event_engine.main import SMCEngine


def ts_to_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main():
    parser = argparse.ArgumentParser(description="Run on real XAUUSD 15m data")
    parser.add_argument("--bars", type=int, default=210398,
                        help="Number of bars (default: 210398 = full)")
    parser.add_argument("--output-dir", type=str, default="output_real")
    parser.add_argument("--layer1-only", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    layer1_dir = out_dir / "layer1"
    layer1_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load data ────────────────────────────────────────────
    print("=" * 60)
    print("STEP 1: Loading XAUUSD 15m parquet data...")
    data_path = "D:/PHUCTD/SMC Research/data/XAUUSD_15m.parquet"
    all_bars = load_bars_from_parquet(data_path, symbol="XAUUSD", timeframe="15")
    print(f"  Total bars available: {len(all_bars)}")

    n = min(args.bars, len(all_bars))
    bars = all_bars[-n:]
    prices = [b.close for b in bars]
    print(f"  Using last {n} bars: {ts_to_str(bars[0].timestamp)} → {ts_to_str(bars[-1].timestamp)}")
    print(f"  Price range: {min(prices):.2f} → {max(prices):.2f}")

    # ── 2. Run Layer 1 (SMC Event Engine) ───────────────────────
    print("\n" + "=" * 60)
    print("STEP 2: Running SMC Event Engine...")

    config = EngineConfig()
    config.symbol = "XAUUSD"
    config.timeframe = "15"
    config.logging.events_path = str(layer1_dir / "events.csv")
    config.logging.snapshots_path = str(layer1_dir / "snapshots.csv")
    config.logging.objects_path = str(layer1_dir / "objects.csv")
    config.logging.snapshot_every_bar = True
    config.swing_length = 50
    config.internal_length = 5
    config.show_swing_structure = True
    config.show_internals = True
    config.show_high_low_swings = True
    config.show_swing_points = True
    config.show_equal_highs_lows = True
    config.show_fair_value_gaps = False
    config.show_premium_discount_zones = True

    engine = SMCEngine(config)
    engine.run(bars)

    summary = engine.summary()
    print(f"  Bars processed: {summary['bar_count']}")
    print(f"  Events emitted: {summary['total_events']}")
    print(f"  Lookahead violations: {summary['violations']}")
    print(f"  Active OBs: {summary['active_obs']}")
    print(f"  Active FVGs: {summary['active_fvgs']}")

    # ── Event stats ────────────────────────────────────────────
    import csv
    event_counts = Counter()
    with open(config.logging.events_path) as f:
        for row in csv.DictReader(f):
            event_counts[row["event_type"]] += 1
    print(f"\n  Event breakdown (top 20):")
    for ev_type, count in event_counts.most_common(20):
        print(f"    {ev_type}: {count}")

    # ── Sweep events ───────────────────────────────────────────
    sweep_count = sum(1 for k in event_counts if "SWEEP" in k or "LIQUIDITY" in k)
    bos_count = sum(v for k, v in event_counts.items() if "BOS" in k)
    choch_count = sum(v for k, v in event_counts.items() if "CHOCH" in k)
    ob_count = sum(v for k, v in event_counts.items() if "OB" in k or "ORDER_BLOCK" in k)
    print(f"\n  SMC Pattern ingredients:")
    print(f"    Sweep/Liquidity events: {sweep_count}")
    print(f"    BOS events: {bos_count}")
    print(f"    CHOCH events: {choch_count}")
    print(f"    OB events: {ob_count}")

    print(f"  Output → {layer1_dir}")

    if args.layer1_only:
        return

    # ── 3. Run Layer 2 (Strategy Layer) ─────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3: Running Strategy Layer...")

    from strategy_layer.config import StrategyConfig
    from strategy_layer.strategy_runner import StrategyRunner

    strat_config = StrategyConfig()
    strat_config.events_path = str(layer1_dir / "events.csv")
    strat_config.snapshots_path = str(layer1_dir / "snapshots.csv")
    strat_config.objects_path = str(layer1_dir / "objects.csv")
    strat_config.symbol = "XAUUSD"
    strat_config.timeframe = "15"
    strat_config.session_enabled = False  # Layer 1 Snapshot chưa có session_id

    strat_config.name = "sweep_choch_ob_real"
    strat_config.allow_long = True
    strat_config.allow_short = True
    strat_config.max_bars_sweep_to_choch = 50
    strat_config.max_bars_wait_entry = 50
    strat_config.sl_type = "sweep_extreme"
    strat_config.sl_buffer_atr_ratio = 20.0
    strat_config.tp_type = "fixed_r"
    strat_config.tp_r_multiple = 2.0
    strat_config.min_rr_ratio = 1.0     # min RR = 1:1

    runner = StrategyRunner(strat_config)
    runner.load_layer1(
        strat_config.events_path,
        strat_config.snapshots_path,
        strat_config.objects_path,
    )
    stats = runner.run()

    print(f"  Strategy: {stats['strategy']}")
    print(f"  Setups: {stats['total_setups']}")
    print(f"  Orders: {stats['total_orders']}")
    print(f"  Decisions: {stats['total_decisions']}")
    for status, count in sorted(stats.get("status_counts", {}).items()):
        print(f"    {status}: {count}")

    # ── Debug: show first rejections ───────────────────────────
    if stats['total_setups'] == 0 and runner.decision_logger.decisions:
        print(f"\n  First 10 REJECT_SETUP reasons:")
        shown = 0
        for d in runner.decision_logger.decisions[:50]:
            if d.decision == "REJECT_SETUP" and d.failed_reasons:
                print(f"    bar={d.bar_index}: {d.failed_reasons}")
                shown += 1
                if shown >= 10:
                    break
        # Show all unique rejection reasons
        reasons = Counter()
        for d in runner.decision_logger.decisions:
            if d.decision == "REJECT_SETUP" and d.failed_reasons:
                for r in d.failed_reasons:
                    reasons[r] += 1
        print(f"\n  Rejection reason breakdown:")
        for reason, count in reasons.most_common(10):
            print(f"    {reason}: {count}")

    # Export
    out_paths = runner.export_csv(str(out_dir))
    print(f"\n  Output files:")
    for name, path in out_paths.items():
        print(f"    {name} → {path}")

    if runner.order_intents:
        print(f"\n  Orders generated ({len(runner.order_intents)}):")
        for o in runner.order_intents[:10]:
            direction_str = "LONG" if o.direction == 1 else "SHORT"
            print(f"    {o.setup_id}: {direction_str} {o.order_type} @ {o.entry_price:.2f} "
                  f"SL={o.sl_price:.2f} TP={o.tp_price:.2f}")

    print("\n" + "=" * 60)
    print("DONE ✅")


if __name__ == "__main__":
    main()
