#!/usr/bin/env python3
"""Compute V8 metrics from backtest results."""
import csv, sys
from pathlib import Path
from collections import Counter

path = Path("output") / "backtest" / "trades.csv"
if not path.exists():
    print("No trades.csv found")
    sys.exit(1)

trades = list(csv.DictReader(open(path)))
if not trades:
    print("Empty trades")
    sys.exit(1)

wins = [t for t in trades if float(t['net_r']) > 0]
losses = [t for t in trades if float(t['net_r']) <= 0]
total = len(trades)
n_wins = len(wins)
n_losses = len(losses)

avg_win_r = sum(float(t['net_r']) for t in wins) / n_wins if n_wins else 0
avg_loss_r = abs(sum(float(t['net_r']) for t in losses)) / n_losses if n_losses else 0
rrr = avg_win_r / avg_loss_r if avg_loss_r else 0
total_r = sum(float(t['net_r']) for t in trades)
avg_bars = sum(int(t['holding_bars']) for t in trades) / total if total else 0

n_weeks = 210398 / (96 * 5)
trades_per_week = total / n_weeks

print(f"V8_COMBINED — 210k bars XAUUSD M15")
print(f"{'='*50}")
print(f"  Trades:          {total}")
print(f"  Wins:            {n_wins}")
print(f"  Losses:          {n_losses}")
print(f"  Win Rate:        {n_wins/total*100:.1f}%")
print(f"  Total R:         {total_r:+.2f}")
print(f"  Avg Win R:       {avg_win_r:.2f}")
print(f"  Avg Loss R:      -{avg_loss_r:.2f}")
print(f"  RRR:             {rrr:.2f}")
print(f"  Trades/Week:     {trades_per_week:.1f}")
print(f"  Avg Held (bars): {avg_bars:.0f}")
print()
print("Exit reasons (wins):")
wr = Counter(t['exit_reason'] for t in wins)
for k, v in wr.most_common():
    print(f"  {k}: {v}")
print("Exit reasons (losses):")
lr = Counter(t['exit_reason'] for t in losses)
for k, v in lr.most_common():
    print(f"  {k}: {v}")

# Check signal vs fill bar
print()
early_fills = sum(1 for t in trades if int(t['fill_bar']) <= int(t['signal_bar']))
print(f"Fill <= Signal bar: {early_fills} (should be 0)")
late_fills = sum(1 for t in trades if int(t['fill_bar']) > int(t['signal_bar']) + 1)
print(f"Fill > Signal+1 bar: {late_fills}")
