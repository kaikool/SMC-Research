# SMC Research — Kiến trúc & Luồng xử lý (v3)

## Luồng chính

```
                          Layer 1 — SMC Event Engine
┌─────────────────────────────────────────────────────────────────┐
│  01_run_layer1.py                                               │
│  smc_event_engine/ (17 modules, đã verify)                     │
│      → phát hiện swing, BOS/CHOCH, OB, FVG, liquidity, PD      │
│      ↓                                                          │
│  output/layer1/events.csv, objects.csv, snapshots.csv           │
└─────────────────────────────────────────────────────────────────┘
                               ↓
                          Layer 2 — Strategy + Execution
┌─────────────────────────────────────────────────────────────────┐
│  02_run_strategy.py  (orchestrator)                             │
│      ├─ đọc Layer 1 output                                      │
│      ├─ xây OB cache (event-sourced, O(n))                     │
│      ├─ chạy V8_Combined model → OrderIntent[]                  │
│      ├─ execution_core.simulate_orders() → TradeRecord[]        │
│      └─ output/backtest/results.csv, trades.csv                 │
│                                                                 │
│  strategy_layer/                                                │
│    entry_strategies.py     M1/M5/M7 baseline                    │
│    tuned_strategies.py     V8_Combined (chiến thắng)            │
│                                                                 │
│  execution_core.py  (generic fill/SL/TP/cost, 11 unit tests)    │
└─────────────────────────────────────────────────────────────────┘
                               ↓
                          Report
┌─────────────────────────────────────────────────────────────────┐
│  03_run_report.py                                               │
│      → WR, total R, equity curve, drawdown                      │
│      → output/report/report.html, equity_curve.png              │
│                                                                 │
│  04_run_chart.py                                                │
│      → TradingView-style HTML chart với trade markers           │
│      → output/chart/tradingview_chart.html                      │
└─────────────────────────────────────────────────────────────────┘
```

## 3 Layer — Trách nhiệm rõ ràng

| Layer | Module | Đầu vào | Đầu ra | Biết SMC? |
|-------|--------|---------|--------|-----------|
| 1 — Event Engine | `smc_event_engine/` | OHLCV | events, objects, snapshots | ✅ Cốt lõi SMC |
| 2 — Strategy | `02_run_strategy.py` + `strategy_layer/` | Layer 1 output | OrderIntent[] | ✅ Dùng OB cache |
| 3 — Execution | `execution_core.py` | OrderIntent[] + OHLC | TradeRecord[] | ❌ Chỉ biết order/price/bar |

## File map

```
SM C Research/
├── 01_run_layer1.py           Layer 1 — SMC event detection
├── 02_run_strategy.py         Layer 2+3 — Strategy + Execution (orchestrator)
├── 03_run_report.py           Report — WR, R, equity
├── 04_run_chart.py            Chart — TradingView HTML
│
├── smc_event_engine/          Layer 1 — 17 modules SMC detection
│   ├── main.py                Orchestrator bar-by-bar
│   ├── swing_engine.py        Swing H/L, EQH/EQL
│   ├── structure_engine.py    BOS/CHOCH
│   ├── ob_engine.py           Order Block creation + lifecycle
│   ├── zone_manager.py        Zone lifecycle, OB touch events
│   ├── no_lookahead_guard.py  Event ordering check
│   ├── data_loader.py         Load parquet bars
│   └── ... (10 modules nữa)
│
├── strategy_layer/            Layer 2 — Entry models
│   ├── entry_strategies.py    M1/M5/M7 (baseline reference)
│   └── tuned_strategies.py    V8_Combined (chiến thắng)
│
├── execution_core.py          Layer 3 — Fill/SL/TP/Cost (generic)
├── test_execution_core.py     11 unit tests (fill, SL/TP, cost, expired, market)
│
├── README.md                  Tổng quan project
├── ARCHITECTURE.md            Kiến trúc chi tiết (file này)
├── GOALS.md                   Research loop protocol & targets
│
└── requirements.txt           Dependencies
```

## Tách biệt Execution khỏi SMC

`execution_core.py` **không biết** các khái niệm SMC:
- OB, FVG, CHOCH, BOS, liquidity sweep, premium/discount
- Chỉ biết: `order_type`, `direction`, `entry_price`, `stop_loss`, `take_profit`, `OHLC bar`

`OrderIntent` là hợp đồng duy nhất giữa Strategy Layer và Execution:

```python
@dataclass
class OrderIntent:
    setup_id: str
    direction: int           # 1 = long, -1 = short
    order_type: str          # "market" / "limit"
    entry_price: float
    entry_zone_top: float
    entry_zone_bottom: float
    stop_loss: float
    take_profit: float
    signal_bar: int
    valid_until_bar: int
```

Strategy Layer chịu trách nhiệm chuyển OB/CHOCH thành OrderIntent. Execution chỉ fill.

## Unit test execution_core

11 tests verify: fill long/short, TP hit, SL hit, SL > TP cùng bar, expired, cost, market order, summary.
Chạy: `python test_execution_core.py`
