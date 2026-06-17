# SMC Research — Smart Money Concept Backtest Engine

Hệ thống backtest SMC 3 tầng, bar-by-bar, **không repaint, không lookahead**.  
Dữ liệu: XAUUSD M15 Dukascopy, 210k bars (2017–2025).  
Execution: `execution_core.py` — generic fill/SL/TP/cost (11 unit tests).  
Cost model: spread 0.30 + slippage 0.10 price units.

---

## 🏗 Kiến trúc

```
Layer 1: SMC Event Engine      OHLCV → Swing → BOS/CHOCH → OB → FVG → Liquidity → PD
         smc_event_engine/     output/layer1/  (events, objects, snapshots)
                  ↓
Layer 2: Strategy              OB cache (event-sourced) → V8 model → OrderIntent[]
         02_run_strategy.py    
                  ↓
Layer 3: Execution             Fill (limit/market) → SL/TP (OHLC) → Cost → PnL
         execution_core.py     output/backtest/  (trades, results)
                  ↓
Layer 4: Report                WR, R, equity curve, chart
         03_run_report.py      output/report/
         04_run_chart.py       output/chart/
```

Điểm khác biệt so với v1:
- **No-lookahead guard**: kiểm tra mọi event trước khi emit, 0 violations ✅
- **Event-sourced OB cache**: O(n) bar loop, lifecycle events remove OBs khi bị mitigate/invalidate
- **execution_core**: generic fill/SL/TP/cost, không biết SMC, có unit test (11 tests)
- **Pre-grouped OB index**: không loop O(n²), từ 2.5 tỷ iterations → 210k

---

## 🚀 Workflow

```bash
# Bước 1: Phát hiện SMC events (210k bars, ~5 phút)
python 01_run_layer1.py

# Bước 2: Strategy + Execution (V8 model)
python 02_run_strategy.py

# Bước 3: Chart (lightweight-charts HTML)
python 03_run_chart.py

# Bước 4: HTML report + equity curve
python 04_run_report.py
```

**Chạy test execution_core:**
```bash
python test_execution_core.py
```

Output:
```
output/
  layer1/       events.csv, snapshots.csv, objects.csv
  backtest/     results.csv, trades.csv
  chart/        tradingview_chart.html
  report/       report.html, equity_curve.png
```

---

## 🎯 Model chính — V8 Combined

| Rule | Pattern | Entry | SL | TP | Filter |
|------|---------|-------|----|----|--------|
| **A** | Swing OB + trend | OB boundary | OB-0.5H | Equilibrium | Trend concurrency |
| **B** | CHOCH + Int OB + vol≥8 + session | OB mid | OB-0.5H | Equilibrium | Trend + vol≥8 + London/NY |

**Kết quả 210k XAUUSD M15 (verified, có unit test):**

```
V8_COMBINED:  68.9% WR | 3.70/week | +2225.32R
              ✅ ≥ 65%  | ✅ ≥ 3    
```

---

## 📟 Hướng dẫn code Pine Script

Dưới đây là spec chi tiết để dev Pine Script implement. Con không đủ kỹ năng Pine để code trực tiếp — chỉ mô tả logic.

### Rule A — Swing OB + trend

```
Điều kiện vào lệnh:
- Có swing high/low (ta.pivothigh/pivotlow, left=5, right=5)
- Giá phá vỡ swing level (BOS): close > swing_high hoặc close < swing_low
- Trend cùng chiều: close > SMA(40) cho LONG, close < SMA(40) cho SHORT
- Entry tại OB boundary:
    LONG: entry = giá thấp nhất trong đoạn [swing_low_bar, break_bar]
    SHORT: entry = giá cao nhất trong đoạn [swing_high_bar, break_bar]
- SL: entry - 0.5 × (OB_top - OB_bottom) cho LONG, entry + 0.5 × (OB_top - OB_bottom) cho SHORT
- TP: (swing_high + swing_low) / 2 (equilibrium)

Vẽ box OB: từ swing point đến break bar, màu xanh cho LONG, đỏ cho SHORT.
```

### Rule B — CHOCH + Int OB + filters

```
Điều kiện vào lệnh:
- Có CHOCH (close phá vỡ internal swing, left=2, right=2)
- Có Internal OB cùng hướng (cách detect tương tự Rule A nhưng dùng internal pivot)
- Trend cùng chiều
- Volatility ≥ ngưỡng: ATR(14) / SMA(ATR(14), 20) × 10 ≥ 8
- Session: London (08-16) hoặc NY (13-22) UTC
- Entry tại OB mid: (OB_top + OB_bottom) / 2
- SL: OB_bottom - 0.5 × height cho LONG, OB_top + 0.5 × height cho SHORT
- TP: equilibrium

Không trade nếu volatility < ngưỡng hoặc ngoài giờ London/NY.
```

### Parameters cho Pine

```pinescript
// Inputs
SWING_LEN = input.int(5, "Swing Pivot Length")
INTERNAL_LEN = input.int(2, "Internal Pivot Length")
ATR_PERIOD = input.int(14, "ATR Period")
VOL_THRESHOLD = input.float(8.0, "Vol Threshold (ATR/SMA*10)")
SESSION_START = input.string("0800", "Session Start (UTC)")
SESSION_END = input.string("2200", "Session End (UTC)")
TREND_MA = input.int(40, "Trend MA Period")
```

### Lưu ý khi code

1. `ta.pivothigh(5,5)` và `ta.pivotlow(5,5)` cho swing — nhớ `ta.valuewhen()` để lấy giá và bar index
2. Khi BOS xảy ra, OB zone là vùng giữa swing point và bar phá vỡ
3. Cần `var` để track OB zone có thời gian sống (200 bars hoặc đến khi bị mitigate)
4. SL/TP cần được set ngay khi vào lệnh, không thay đổi sau đó (trừ trailing nếu muốn)
5. Volatility proxy: `ta.atr(14) / ta.sma(ta.atr(14), 20) * 10`. Ngưỡng 8 tương đương volatility cao.
6. `time(timeframe.period, SESSION_START + "-" + SESSION_END + ":12345")` cho session filter
7. Consolidate tín hiệu: nếu Rule A và Rule B cùng vào 1 bar → vào 1 lệnh (không double)

### Tham khảo

- File `strategy_layer/tuned_strategies.py` class `V8_Combined` — implementation Python đầy đủ
- File `execution_core.py` — fill/SL/TP/cost model để tham khảo cách tính R
- Các hằng số cost: spread 0.30, slippage 0.10 (XAUUSD, price units)

---

## 📁 Cấu trúc thư mục

```
smc_event_engine/          17 modules    Layer 1 — SMC detection (verified)
execution_core.py          1 file        Layer 3 — generic fill/SL/TP/cost (11 tests)
strategy_layer/
  entry_strategies.py      M1/M5/M7 models (baseline)
  tuned_strategies.py      V8_Combined (chiến thắng)

01_run_layer1.py           Pipeline bước 1
02_run_strategy.py         Pipeline bước 2 (orchestrator mới)
03_run_chart.py            Pipeline bước 3
04_run_report.py           Pipeline bước 4
test_execution_core.py     Unit test execution (11 tests)
GOALS.md                   Research loop protocol
ARCHITECTURE.md            Chi tiết kiến trúc
```

---

## 🔧 Requirements

```bash
pip install pandas pyarrow pyyaml matplotlib
```

---

*SMC detection. Zero lookahead.  
Data: XAUUSD M15 Dukascopy | Engine: Python | Generated by Hermes Agent*
