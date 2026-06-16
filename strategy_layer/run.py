#!/usr/bin/env python
"""
CLI cho Strategy Layer — chạy strategy với dữ liệu từ Layer 1.

Usage:
    python run.py --events events.csv --snapshots snapshots.csv --objects objects.csv
    python run.py --demo              # Dùng synthetic data (yêu cầu pip install smc_event_engine)
    python run.py --config my_strategy.yaml --events ...
"""

import argparse
import os
import sys
import csv
from collections import defaultdict

# Add parent to path for smc_event_engine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from strategy_layer.config import StrategyConfig
from strategy_layer.strategy_runner import StrategyRunner


def find_layer1_output(base_dir: str) -> dict[str, str]:
    """Tự động tìm 3 file output của Layer 1 trong thư mục."""
    paths = {}
    for fname in ["events.csv", "snapshots.csv", "objects.csv"]:
        fpath = os.path.join(base_dir, fname)
        if os.path.exists(fpath):
            paths[fname.replace(".csv", "")] = fpath
    return paths


def run_demo(config: StrategyConfig) -> dict:
    """Chạy demo với dữ liệu từ Layer 1 events.csv có sẵn."""
    base = config.events_path or os.path.dirname(__file__)
    if not config.events_path:
        # Tìm trong thư mục hiện tại và parent
        for d in [os.path.dirname(__file__), os.path.join(os.path.dirname(__file__), ".."),
                  os.path.join(os.path.dirname(__file__), "..", "smc_event_engine")]:
            events = os.path.join(d, "events.csv")
            if os.path.exists(events):
                config.events_path = os.path.join(d, "events.csv")
                config.snapshots_path = os.path.join(d, "snapshots.csv")
                config.objects_path = os.path.join(d, "objects.csv")
                break

    if not config.events_path or not os.path.exists(config.events_path):
        print("ERROR: Không tìm thấy events.csv.", file=sys.stderr)
        print("Chạy Layer 1 (smc_event_engine) trước, hoặc dùng --events.", file=sys.stderr)
        sys.exit(1)

    print(f"Events : {config.events_path}")
    print(f"Snapshots: {config.snapshots_path}")
    print(f"Objects: {config.objects_path}")

    runner = StrategyRunner(config)
    runner.load_layer1(config.events_path, config.snapshots_path, config.objects_path)
    stats = runner.run()

    return runner, stats


def main():
    parser = argparse.ArgumentParser(description="SMC Strategy Layer")
    parser.add_argument("--events", default="", help="Path to events.csv from Layer 1")
    parser.add_argument("--snapshots", default="", help="Path to snapshots.csv from Layer 1")
    parser.add_argument("--objects", default="", help="Path to objects.csv from Layer 1")
    parser.add_argument("--config", default="", help="Path to YAML config file")
    parser.add_argument("--output", default=".", help="Output directory for results")
    parser.add_argument("--demo", action="store_true", help="Run demo with found data")
    args = parser.parse_args()

    # Load config
    if args.config and os.path.exists(args.config):
        config = StrategyConfig.from_yaml(args.config)
        print(f"Loaded config: {config.name}")
    else:
        config = StrategyConfig()
        if args.config:
            print(f"Config file not found: {args.config}, using defaults")

    # Override paths from CLI
    if args.events:
        config.events_path = args.events
    if args.snapshots:
        config.snapshots_path = args.snapshots
    if args.objects:
        config.objects_path = args.objects

    # Run
    runner, stats = run_demo(config)

    print(f"\n{'='*60}")
    print(f"Strategy: {stats['strategy']}")
    print(f"Setups created: {stats['total_setups']}")
    print(f"Orders generated: {stats['total_orders']}")
    print(f"Decisions logged: {stats['total_decisions']}")
    print(f"\nBy status:")
    for status, count in sorted(stats['status_counts'].items()):
        print(f"  {status}: {count}")
    print(f"\nDecisions:")
    for decision, count in sorted(stats['decision_summary']['by_decision'].items()):
        print(f"  {decision}: {count}")

    # Export CSV
    out_paths = runner.export_csv(args.output)
    print(f"\nOutput:")
    for name, path in out_paths.items():
        print(f"  {name}.csv → {os.path.abspath(path)}")

    # Quick stats from setups
    if runner.setups:
        all_status = defaultdict(int)
        for s in runner.setups:
            all_status[s.status] += 1

        print(f"\n{'='*60}")
        print(f"Setup Flow (by status):")
        for status in ["created", "pending", "armed", "triggered", "entered", "completed", "cancelled", "expired"]:
            if all_status.get(status, 0) > 0:
                print(f"  {status:12s}: {all_status[status]}")
        print(f"  {'orders':12s}: {len(runner.order_intents)}")

        if runner.order_intents:
            print(f"\nSample orders:")
            for o in runner.order_intents[:5]:
                print(f"  {o.action} {o.direction:+d} {o.order_type} @ {o.entry_price:.5f} "
                      f"SL={o.sl_price:.5f} TP={o.tp_price:.5f} [{o.setup_id}]")


if __name__ == "__main__":
    main()
