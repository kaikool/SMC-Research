#!/usr/bin/env python3
"""Learn backtesting.py — chạy demo, hiểu API."""
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA

print("=== backtesting.py loaded OK ===")

# Load 5000 bars XAUUSD
df = pd.read_parquet("D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet")
df = df.tail(5000).copy()
df.rename(columns={
    "timestamp_utc": "Date",
    "open": "Open", "high": "High", "low": "Low", "close": "Close",
}, inplace=True)
# backtesting.py cần index là datetime
df["Date"] = pd.to_datetime(df["Date"])
df.set_index("Date", inplace=True)

print(f"Data: {len(df)} bars, {df.index[0]} → {df.index[-1]}")

class SmaCross(Strategy):
    n1 = 10
    n2 = 20

    def init(self):
        close = self.data.Close
        self.ma1 = self.I(SMA, close, self.n1, name="MA10")
        self.ma2 = self.I(SMA, close, self.n2, name="MA20")

    def next(self):
        if crossover(self.ma1, self.ma2):
            self.buy(size=0.1)
        elif crossover(self.ma2, self.ma1):
            self.sell(size=0.1)

bt = Backtest(df, SmaCross, cash=10000, commission=.002)
stats = bt.run()
print(stats)
print("\n=== Trade list ===")
print(stats._trades.head(10))

# Try plot — nếu chạy từ terminal ko có display, lưu HTML
try:
    bt.plot(filename="output/backtesting_demo.html")
    print("\n[✓] Chart saved to output/backtesting_demo.html")
except Exception as e:
    print(f"Plot error (expected in headless): {e}")
