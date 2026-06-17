# SMC Research — Cấu trúc & Luồng xử lý (v3)

## Luồng chính

```
                         Layer 1
┌──────────────────────────────────────────────────────┐
│  01_run_layer1.py                                    │
│  smc_event_engine/  (17 modules, đã verify)          │
│      ↓                                               │
│  output/layer1/events.csv, objects.csv, snapshots.csv│
└──────────────────────────────────────────────────────┘
                            ↓
                         Layer 2 — Strategy
┌──────────────────────────────────────────────────────┐
│  02_run_strategy.py  (ORCHESTRATOR — mới)            │
│      │                                               │
│      ├─ đọc Layer 1 output                           │
│      ├─ xây OB cache (event-sourced)                 │
│      ├─ chạy strategy model (V8_Combined)            │
│      ├─ sinh OrderIntent[]                           │
│      └─ gọi execution_core.simulate_orders()         │
│           ↓                                          │
│  output/backtest/trades.csv, results.csv             │
└──────────────────────────────────────────────────────┘
                            ↓
                         Report
┌──────────────────────────────────────────────────────┐
│  03_run_report.py  (cập nhật)                        │
│      ├─ WR, R, equity curve                          │
│      └─ output/report/report.html                    │
│                                                      │
│  04_run_chart.py  (giữ nguyên)                       │
│      └─ output/chart/tradingview_chart.html          │
└──────────────────────────────────────────────────────┘
```

## File nào giữ, file nào bỏ

### Giữ lại (đã verify, đang dùng)

| File / Module | Lý do |
|---------------|-------|
| `01_run_layer1.py` | Layer 1 pipeline |
| `smc_event_engine/` | 17 modules SMC detection |
| `strategy_layer/entry_strategies.py` | M1/M5/M7 models (baseline reference) |
| `strategy_layer/tuned_strategies.py` | V8_Combined model (chiến thắng) |
| `execution_core.py` | Fill/SL/TP generic (mới, có test) |
| `test_execution_core.py` | Unit test execution (11 tests) |
| `03_run_chart.py` | Chart HTML |
| `04_run_report.py` | Report + equity curve |

### Cần tạo mới

| File | Chức năng |
|------|-----------|
| `02_run_strategy.py` | Orchestrator mới: OB cache → V8 model → execution_core |

### Xóa (code chết, không dùng)

| File / Module | Lý do |
|---------------|-------|
| `02_run_backtest.py` | Gộp signal + execution cũ, thay bởi 02_run_strategy.py |
| `strategy_layer/config.py` | Không dùng (V8 filter inline) |
| `strategy_layer/setup_engine.py` | Không dùng |
| `strategy_layer/setup_state_machine.py` | Không dùng |
| `strategy_layer/filter_engine.py` | Không dùng |
| `strategy_layer/entry_model.py` | Không dùng |
| `strategy_layer/sl_model.py` | Không dùng |
| `strategy_layer/tp_model.py` | Không dùng |
| `strategy_layer/strategy_runner.py` | Không dùng |
| `strategy_layer/order_intent_generator.py` | Không dùng |
| `strategy_layer/decision_logger.py` | Không dùng |
| `strategy_layer/models.py` | Không dùng (execution_core.OrderIntent thay thế) |

### Để sau (hỏi bố)

| File / Module | Câu hỏi |
|---------------|---------|
| `execution_layer/` (18 modules) | Legacy, không dùng. Xóa hay giữ? |
| `execution_config.yaml` | Chỉ execution_layer dùng |
| `symbol_specs.json` | Chỉ execution_layer dùng |

## V8 pipeline mới (02_run_strategy.py)

```python
def main():
    # 1. Load Layer 1
    prices, events, objects, snaps = load_layer1(...)

    # 2. Build OB cache (event-sourced, O(n))
    ob_cache = build_ob_cache(objects, events, snaps)

    # 3. Run strategy → OrderIntent[]
    model = V8_Combined()
    intents = []
    for bi in bar_indices:
        orders = model.on_bar(bi, events[bi], snaps[bi], ob_cache[bi])
        for o in orders:
            intents.append(OrderIntent(
                setup_id=..., direction=o.direction,
                order_type="limit", entry_price=o.entry_price,
                entry_zone_top=o.entry_zone_top,
                entry_zone_bottom=o.entry_zone_bottom,
                stop_loss=o.sl_price, take_profit=o.tp_price,
                signal_bar=o.bar_index, timestamp=o.timestamp,
                valid_until_bar=o.bar_index + 150,
                source=o.model,
            ))

    # 4. Execute → trades
    trades = simulate_orders(intents, prices)

    # 5. Report
    summary = summarize_trades(trades)
    save_results(summary, trades)
```

**Bố cho con hỏi:**
1. Xóa `02_run_backtest.py` hay giữ làm reference?
2. Xóa `execution_layer/` (18 modules) không?
3. Xóa các file strategy_layer không dùng không?
