#!/usr/bin/env python3
"""
[Step 1/4] SMC Event Engine — Layer 1.
Chạy bar-by-bar trên 210k bars XAUUSD M15, phát hiện SMC events:
Swing → BOS/CHOCH → OB → Liquidity → PD Zones.

Output: output/layer1/{events, snapshots, objects}.csv
"""
import sys, os, csv
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(line_buffering=True)
csv.field_size_limit(10 * 1024 * 1024)

from smc_event_engine.data_loader import load_bars_from_parquet
from smc_event_engine.config import EngineConfig
from smc_event_engine.main import SMCEngine


DATA_PATH = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
OUTPUT_DIR = Path("output")


def ts_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main():
    layer1_dir = OUTPUT_DIR / "layer1"
    layer1_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load data ────────────────────────────────
    print("[1/4] Loading XAUUSD M15 parquet...", flush=True)
    all_bars = load_bars_from_parquet(DATA_PATH, symbol="XAUUSD", timeframe="15")
    print(f"      → {len(all_bars)} bars  |  {ts_str(all_bars[0].timestamp)} → {ts_str(all_bars[-1].timestamp)}")
    prices = [b.close for b in all_bars]
    print(f"      → price range: {min(prices):.2f} → {max(prices):.2f}")

    # ── 2. Config ───────────────────────────────────
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

    # ── 3. Run Engine ───────────────────────────────
    print("[3/4] Running SMC Event Engine (bar-by-bar, no lookahead)...", flush=True)
    engine = SMCEngine(config)
    engine.run(all_bars)
    summary = engine.summary()
    g = engine.guard

    print(f"\n[3/4] DONE", flush=True)
    print(f"      → bars: {summary['bar_count']:,}")
    print(f"      → events: {summary['total_events']:,}")
    print(f"      → lookahead violations: {summary['violations']}")
    print(f"      → active OBs: {summary['active_obs']}")
    print(f"      → active FVGs: {summary['active_fvgs']}")
    if g.violations:
        print(f"      ⚠ VIOLATIONS:", flush=True)
        for v in g.violations[:20]:
            print(f"        - {v}")

    # ── 4. Stats ────────────────────────────────────
    print("[4/4] Event breakdown...", flush=True)
    counts = Counter()
    with open(config.logging.events_path) as f:
        for row in csv.DictReader(f):
            counts[row["event_type"]] += 1

    for ev_type, count in counts.most_common(25):
        print(f"        {ev_type}: {count}")

    sweep = sum(v for k, v in counts.items() if "SWEEP" in k or "LIQUIDITY" in k)
    bos = sum(v for k, v in counts.items() if "BOS" in k)
    choch = sum(v for k, v in counts.items() if "CHOCH" in k)
    ob_total = sum(v for k, v in counts.items() if "OB" in k or "ORDER_BLOCK" in k)
    print(f"\n      Sweeps: {sweep}  |  BOS: {bos}  |  CHOCH: {choch}  |  OB: {ob_total}")

    # ── Sizes ──────────────────────────────────────
    for fname in ("events.csv", "snapshots.csv", "objects.csv"):
        fp = layer1_dir / fname
        print(f"      {fname}: {os.path.getsize(fp)/1e6:.1f} MB")

    print(f"\n[✓] Layer 1 → {layer1_dir}")


if __name__ == "__main__":
    main()
