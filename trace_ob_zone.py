#!/usr/bin/env python3
"""Deep trace: verify OB zone không dùng bar hiện tại."""
import sys, os, csv
sys.path.insert(0, "D:/Antigravity/SMC Research")
sys.stdout.reconfigure(line_buffering=True)
from pathlib import Path
from collections import defaultdict

LAYER1_DIR = Path("output") / "layer1"

with open(LAYER1_DIR / "events.csv") as f: events = list(csv.DictReader(f))
with open(LAYER1_DIR / "objects.csv") as f: objects = list(csv.DictReader(f))
with open(LAYER1_DIR / "snapshots.csv") as f: snaps = list(csv.DictReader(f))

ts_to_bi = {}
for s in snaps:
    try: ts_to_bi[int(s["timestamp"])] = int(s["bar_index"])
    except: pass

# Trace trade đầu tiên: bar=132, LONG, OB_9 (BOS_BULLISH)
print("=== TRADE 1: bar 132, LONG, OB_9 (BOS_BULLISH) ===")

ob9 = [o for o in objects if o["object_id"] == "OB_9"][0]
print(f"OB_9:")
print(f"  created_at={ob9['created_at']} → bar_index={ts_to_bi.get(int(ob9['created_at']),'?')}")
print(f"  active_from={ob9['active_from']} → bar_index={ts_to_bi.get(int(ob9['active_from']),'?')}")
print(f"  source_event={ob9['source_event']}")
print(f"  top={ob9['top']} bottom={ob9['bottom']}")
print(f"  type={ob9['type']}")

# Kiểm tra: origin bar index từ created_at
origin_bi = ts_to_bi.get(int(ob9['created_at']), -1)
active_bi = ts_to_bi.get(int(ob9['active_from']), -1)
print(f"\n  origin_bar (created_at) = {origin_bi}")
print(f"  active_from_bar = {active_bi}")
print(f"  OB zone dùng data từ bar {origin_bi}, KHÔNG phải bar active {active_bi}")
print(f"  => ✅ OB zone hoàn toàn từ historical data, không lookahead!" if origin_bi < active_bi else "  => ⚠️ origin_bar >= active_bar")

# Kiểm tra tất cả OB
print("\n=== CHECK ALL OB: created_at_bi >= active_from_bi ===")
bad = 0
for ob in objects:
    try:
        ca = int(ob['created_at'])
        af = int(ob['active_from'])
        ca_bi = ts_to_bi.get(ca, -1)
        af_bi = ts_to_bi.get(af, -1)
        if ca_bi >= 0 and af_bi >= 0 and ca_bi >= af_bi:
            bad += 1
            if bad <= 5:
                print(f"  ⚠️ {ob['object_id']}: origin_bi={ca_bi} >= active_bi={af_bi}")
    except: pass
print(f"  Total problematic OBs: {bad}")
print(f"  (Có nghĩa là OB zone từ bar {origin_bi} và active từ bar {active_bi})")

# Verify: executed trades count
print("\n=== RESULTS VERIFICATION ===")
# Read trades from execution_core output
import pandas as pd
try:
    trades = pd.read_csv(Path("output") / "backtest" / "trades.csv")
    wins = len(trades[trades['net_r'] > 0])
    losses = len(trades[trades['net_r'] <= 0])
    total = len(trades)
    print(f"  Total trades: {total}")
    print(f"  Wins: {wins} Losses: {losses}")
    print(f"  WR: {wins/total*100:.1f}%" if total > 0 else "  No trades")
except:
    print("  No backtest output found")
