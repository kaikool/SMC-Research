"""
CLI runner for SMC Event Engine.

Usage:
    python -m smc_event_engine.run --csv data.csv [--config config.yaml] [--symbol EURUSD] [--tf 15]
    python -m smc_event_engine.run --demo                         # Run with synthetic data
"""

import argparse
import sys
import os
from pathlib import Path

from .config import EngineConfig
from .data_loader import load_bars_from_csv, generate_sample_bars
from .main import SMCEngine


def main():
    parser = argparse.ArgumentParser(description="SMC Event Engine")
    parser.add_argument("--csv", type=str, help="Path to OHLCV CSV file")
    parser.add_argument("--config", type=str, help="Path to YAML config file")
    parser.add_argument("--symbol", type=str, default="EURUSD", help="Symbol name")
    parser.add_argument("--tf", type=str, default="15", help="Timeframe in minutes")
    parser.add_argument("--demo", action="store_true", help="Run with synthetic demo data")
    parser.add_argument("--output-dir", type=str, default=".", help="Output directory for CSVs")
    args = parser.parse_args()

    # ── Load config ──────────────────────────────────────────────
    config = EngineConfig()
    if args.config:
        config = EngineConfig.from_yaml(args.config)
    elif args.demo:
        pass  # Use defaults
    else:
        # Load from default path if exists
        default_cfg = Path("smc_config.yaml")
        if default_cfg.exists():
            config = EngineConfig.from_yaml(str(default_cfg))

    # ── Load data ────────────────────────────────────────────────
    if args.demo:
        print("Generating synthetic data...")
        bars = generate_sample_bars(1000, timeframe=args.tf)
    elif args.csv:
        print(f"Loading data from {args.csv}...")
        bars = load_bars_from_csv(args.csv, symbol=args.symbol, timeframe=args.tf)
    else:
        print("Error: provide --csv path or --demo flag.")
        sys.exit(1)

    # ── Override config paths ────────────────────────────────────
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    config.logging.events_path = str(out_dir / "events.csv")
    config.logging.snapshots_path = str(out_dir / "snapshots.csv")
    config.logging.objects_path = str(out_dir / "objects.csv")

    # Fill symbol/timeframe
    if not config.symbol:
        config.symbol = args.symbol
    if not config.timeframe:
        config.timeframe = args.tf

    # ── Run engine ───────────────────────────────────────────────
    print(f"Running SMC Event Engine on {len(bars)} bars...")
    engine = SMCEngine(config)
    engine.run(bars)

    # ── Report ───────────────────────────────────────────────────
    summary = engine.summary()
    guard_report = engine.guard.summary()

    print(f"\n{'='*50}")
    print("SMC EVENT ENGINE — COMPLETE")
    print(f"{'='*50}")
    print(f"  Bars processed: {summary['bar_count']}")
    print(f"  Events emitted: {summary['total_events']}")
    print(f"  Lookahead violations: {summary['violations']}")
    print(f"  Active OBs: {summary['active_obs']}")
    print(f"  Active FVGs: {summary['active_fvgs']}")
    print(f"\n  {guard_report}")
    print(f"\n  Events   → {config.logging.events_path}")
    print(f"  Snapshots → {config.logging.snapshots_path}")
    print(f"  Objects  → {config.logging.objects_path}")
    print(f"{'='*50}")

    # Show sample events
    if summary['total_events'] > 0:
        print("\nSample events (first 10):")
        try:
            import csv
            with open(config.logging.events_path) as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    if i >= 10:
                        break
                    ts = row.get("timestamp", "")
                    ev = row.get("event_type", "")
                    direct = row.get("direction", "")
                    price = row.get("price", "")
                    print(f"  {ts} | {ev} | dir={direct} | price={price}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
