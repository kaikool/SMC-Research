#!/usr/bin/env python
"""
Run Layer 1 (SMC Event Engine) on full XAUUSD 15m parquet data.
Output goes to output_full/layer1/
"""
import sys, os
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

# Unbuffered output so we can see progress
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from smc_event_engine.data_loader import load_bars_from_parquet
from smc_event_engine.config import EngineConfig
from smc_event_engine.main import SMCEngine


def ts_to_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main():
    out_dir = Path("output_full")
    out_dir.mkdir(parents=True, exist_ok=True)
    layer1_dir = out_dir / "layer1"
    layer1_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load data ────────────────────────────────────────────
    print("[1/4] Loading XAUUSD 15m parquet data...", flush=True)
    data_path = "D:/PHUCTD/SMC Research/data/XAUUSD_15m.parquet"
    all_bars = load_bars_from_parquet(data_path, symbol="XAUUSD", timeframe="15")
    print(f"      → {len(all_bars)} bars loaded", flush=True)
    print(f"      → {ts_to_str(all_bars[0].timestamp)} → {ts_to_str(all_bars[-1].timestamp)}", flush=True)
    prices = [b.close for b in all_bars]
    print(f"      → price range: {min(prices):.2f} → {max(prices):.2f}", flush=True)

    # ── 2. Config ───────────────────────────────────────────────
    print("[2/4] Configuring engine...", flush=True)
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

    # ── 3. Run Engine ───────────────────────────────────────────
    print("[3/4] Running SMC Event Engine...", flush=True)
    print(f"      → processing {len(all_bars)} bars bar-by-bar (no lookahead)", flush=True)

    engine = SMCEngine(config)
    engine.run(all_bars)

    summary = engine.summary()
    g = engine.guard
    print(f"\n[3/4] DONE", flush=True)
    print(f"      → bars processed: {summary['bar_count']}", flush=True)
    print(f"      → events emitted: {summary['total_events']}", flush=True)
    print(f"      → lookahead violations: {summary['violations']}", flush=True)
    print(f"      → active OBs: {summary['active_obs']}", flush=True)
    print(f"      → active FVGs: {summary['active_fvgs']}", flush=True)

    if g.violations:
        print(f"\n      ⚠ VIOLATIONS:", flush=True)
        for v in g.violations[:20]:
            print(f"        - {v}", flush=True)

    # ── 4. Event stats ──────────────────────────────────────────
    print("[4/4] Analyzing events...", flush=True)
    import csv
    event_counts = Counter()
    with open(config.logging.events_path) as f:
        for row in csv.DictReader(f):
            event_counts[row["event_type"]] += 1

    print(f"\n      Event breakdown:", flush=True)
    for ev_type, count in event_counts.most_common(25):
        print(f"        {ev_type}: {count}", flush=True)

    sweep = sum(v for k, v in event_counts.items() if "SWEEP" in k or "LIQUIDITY" in k)
    bos = sum(v for k, v in event_counts.items() if "BOS" in k)
    choch = sum(v for k, v in event_counts.items() if "CHOCH" in k)
    ob_total = sum(v for k, v in event_counts.items() if "OB" in k or "ORDER_BLOCK" in k)
    print(f"\n      SMC Summary:", flush=True)
    print(f"        Sweeps: {sweep} | BOS: {bos} | CHOCH: {choch} | OB: {ob_total}", flush=True)

    print(f"\n[✓] Layer 1 complete → {layer1_dir}", flush=True)
    print(f"      events.csv: {os.path.getsize(config.logging.events_path)/1e6:.1f} MB", flush=True)
    print(f"      snapshots.csv: {os.path.getsize(config.logging.snapshots_path)/1e6:.1f} MB", flush=True)
    print(f"      objects.csv: {os.path.getsize(config.logging.objects_path)/1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
