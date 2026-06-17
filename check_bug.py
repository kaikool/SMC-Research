#!/usr/bin/env python3
"""Check bug: TP_HIT trade with net_r <= 0"""
import csv
trades = list(csv.DictReader(open("output/backtest/trades.csv")))
bad = [t for t in trades if t["exit_reason"] == "TP_HIT" and float(t["net_r"]) <= 0]
print(f"Bug trades: {len(bad)}")
for t in bad[:5]:
    print(f"  dir={t['direction']} entry={t['fill_price']} exit={t['exit_price']} net_r={t['net_r']} held={t['holding_bars']}")
