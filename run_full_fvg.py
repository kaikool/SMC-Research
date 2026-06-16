"""Run Layer 1 on full 210k bars WITH FVG enabled."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["PYTHONUNBUFFERED"] = "1"

from smc_event_engine.data_loader import load_bars_from_parquet
from smc_event_engine.config import EngineConfig
from smc_event_engine.main import SMCEngine

print("Loading 210k bars...")
bars = load_bars_from_parquet(
    "D:/PHUCTD/SMC Research/data/XAUUSD_15m.parquet",
    symbol="XAUUSD", timeframe="15"
)
print(f"Loaded {len(bars)} bars: {bars[0].close} → {bars[-1].close}")

cfg = EngineConfig()
cfg.symbol = "XAUUSD"
cfg.timeframe = "15"
cfg.logging.events_path = "output_full_fvg/layer1/events.csv"
cfg.logging.snapshots_path = "output_full_fvg/layer1/snapshots.csv"
cfg.logging.objects_path = "output_full_fvg/layer1/objects.csv"
cfg.logging.snapshot_every_bar = True
cfg.swing_length = 50
cfg.internal_length = 5
cfg.show_internals = True
cfg.show_swing_structure = True
cfg.show_high_low_swings = True
cfg.show_swing_points = True
cfg.show_equal_highs_lows = True
cfg.show_premium_discount_zones = True

# BẬT FVG
cfg.show_fair_value_gaps = True
cfg.fvg.use_htf = False     # Dùng same-TF detection
cfg.fvg.auto_threshold = True
cfg.fvg.extend_bars = 1

print("Running engine with FVG enabled...")
engine = SMCEngine(cfg)
engine.run(bars)
print(f"Done. Events: {engine.output.event_logger.row_count}, Violations: {len(engine.guard.violations)}")
