# Hệ Thống Backtest SMC — Kiến Trúc Đa Tầng

> **Mục tiêu**: Xây dựng hệ thống Python để back test chỉ báo Smart Money Concept (Pine Editor v6) một cách nghiêm túc, không repaint, không nhìn trước tương lai.
>
> *"Tôi có một chỉ báo giao dịch dựa trên Smart Money Concept trên Pine Editor v6, tôi yêu cầu bạn nghiên cứu cách các chuyên gia giao dịch thuật toán xây dựng hệ thống sử dụng Python để back test chỉ báo đó. Bạn chỉ cần nghiên cứu quy tắc, còn logic của thuật toán chưa cần bàn đến. Sau khi có được các quy tắc nhất quán, chính xác cao, lúc đó tôi sẽ hỏi bạn tiếp."*

---

## Tổng Quan Kiến Trúc

Hệ thống gồm **3 tầng (layer)**, mỗi tầng có trách nhiệm riêng biệt, dữ liệu truyền theo một chiều (downstream), không có vòng lặp phụ thuộc:

```
┌────────────────────────────────────────────────────────────┐
│                   LAYER 1: SMC EVENT ENGINE                 │
│  OHLCV → Swing Engine → Structure Engine → Liquidity Engine │
│  → Order Block Engine → FVG Engine → Premium/Discount       │
│  → Zone Manager → Event Logger + Snapshot Logger            │
│  → Output: events.csv, snapshots.csv, objects.csv            │
├────────────────────────────────────────────────────────────┤
│                                                              │
│                          ↓                                   │
│                                                              │
├────────────────────────────────────────────────────────────┤
│                   LAYER 2: STRATEGY LAYER                    │
│  Đọc event stream → Setup Engine → Entry/SL/TP Model        │
│  → Filter Engine → Order Intent Generator                    │
│  → Output: setups.csv, orders_intent.csv, decisions.csv      │
├────────────────────────────────────────────────────────────┤
│                                                              │
│                          ↓                                   │
│                                                              │
├────────────────────────────────────────────────────────────┤
│                   LAYER 3: EXECUTION LAYER                   │
│  Đọc orders_intent.csv → Order Manager → Fill Model          │
│  → SL/TP Handler → Position Manager → Account Ledger         │
│  → Output: trades.csv, orders.csv, equity_curve.csv          │
└────────────────────────────────────────────────────────────┘
```

---

## Layer 1: SMC Event Engine ✅ *(Hoàn thành)*

### Vai trò

Biến chart OHLCV thành **event stream có timestamp rõ ràng** — mỗi sự kiện SMC được ghi nhận tại **đúng thời điểm nó được xác nhận**, không repaint, không gán ngược quá khứ.

Engine chạy bar-by-bar như Pine Script: **tại bar `t` chỉ biết dữ liệu ≤ `t`**.

### Input

| Dữ liệu | Định dạng | Nguồn |
|---|---|---|
| OHLCV CSV | timestamp, open, high, low, close, volume | Bất kỳ broker |
| OHLCV Parquet | timestamp_utc, open, high, low, close, volume | Dukascopy (có sẵn) |
| Synthetic | numpy random walk với trend phases | `generate_sample_bars()` |

### Các Module

| Module | Chức năng | Nguồn tham chiếu |
|---|---|---|
| `data_loader.py` | Load + validate OHLCV (timestamp, gap, OHLC ordering) | Spec |
| `config.py` | YAML config — swing left/right, break method, OB rules | Spec §16 |
| `models.py` | Data types: Bar, PivotPoint, OrderBlock, FVG, Zone, Event | Spec §3 |
| `state_store.py` | Market state: trend, swing levels, OB/FVG counts | Spec §3 |
| `swing_engine.py` | Phát hiện swing high / swing low theo phương pháp `leg()` | **LuxAlgo** |
| `structure_engine.py` | BOS/CHOCH — close crossover/crossunder, trend-relative tagging | **LuxAlgo** |
| `liquidity_engine.py` | Liquidity sweep, equal high/low, sweep classification | Spec §6 |
| `order_block_engine.py` | Tạo OB từ parsedHigh/parsedLow giữa pivot → hiện tại | **LuxAlgo + Spec §7** |
| `fvg_engine.py` | FVG 3-bar HTF với auto-threshold | **LuxAlgo** |
| `premium_discount_engine.py` | Premium/Discount/Equilibrium từ trailing extremes | **LuxAlgo + Spec §9** |
| `zone_manager.py` | Zone lifecycle — add/touch/mitigate/invalidate/expire | Spec §11 |
| `mtf_engine.py` | HTF resample, closed-candle strict, timing guard | Spec §10 |
| `output.py` | 3 file output: events.csv, snapshots.csv, objects.csv | Spec §12-13 |
| `no_lookahead_guard.py` | 5 rules chống repaint (event_time ≥ confirm_time, HTF < LTF, ...) | Spec §15 |
| `pine_parity.py` | So sánh Python vs Pine event output | Spec §14 |
| `main.py` | `SMCEngine` — bar-by-bar loop orchestrator | Spec §2 |
| `run.py` | CLI: `--csv` / `--demo` / `--config` | |

### Output

| File | Nội dung | Số dòng (mẫu 5000 bars) |
|---|---|---|
| `events.csv` | SMC event stream: timestamp, event_type, direction, price, object_id, ... | ~2.400 |
| `snapshots.csv` | Trạng thái thị trường từng bar: trend, swing levels, OB count, ... | 5.000 |
| `objects.csv` | Vòng đời object: Order Block, FVG với lifecycle | ~300 |

### Kết quả kiểm tra với dữ liệu thật

- **XAUUSD 15m**: 210.398 nến (2017 → 2025), validation 0 lỗi
- **5.000 bars test**: 2.391 events, **0 lookahead violations**
- Cấu trúc SMC phát hiện được: swing BOS (6), swing CHOCH (7), internal BOS/CHOCH (250+)
- OB lifecycle: 273 created → 116 mitigated → 96 invalidated → 56 expired

### Config mẫu

```yaml
swing:
  left: 5
  right: 5
  use_close_break: true

structure:
  bos_break_method: close
  choch_break_method: close

order_block:
  use_body_only: false
  mitigation_method: wick_touch
  invalidation_method: close_through
  max_age_bars: 500

fvg:
  min_size_atr: 0.0
  fill_method: full

mtf:
  strict_closed_htf: true
```

---

## Layer 2: Strategy Layer ✅ *(Hoàn thành V1)*

### Vai trò

Đọc event stream từ Layer 1, áp dụng entry rule, sinh setup giao dịch và order intent.

**Không chứa:** position sizing, risk management, equity calculation (thuộc Layer 3).

### Input

- `events.csv` từ Layer 1
- `snapshots.csv` từ Layer 1 (để filter bar state)
- `objects.csv` từ Layer 1 (để kiểm tra OB/FVG active)
- `strategy_config.yaml` — định nghĩa setup rule, entry/SL/TP logic

### Output

| File | Nội dung |
|---|---|
| `setups.csv` | Setup giao dịch (entry rule trigger, SL, TP, OB/FVG source) |
| `orders_intent.csv` | Order intent cho Execution Engine (timestamp, symbol, direction, order_type, price, SL, TP, risk%) |
| `strategy_decisions.csv` | Chi tiết lý do setup được tạo/cancel/expire/trigger |

### Các Module

| Module | Chức năng |
|---|---|
| `config.py` | YAML config — entry rules, filter thresholds, symbol map |
| `models.py` | Data types: Setup, OrderIntent, StrategyDecision, SetupState |
| `setup_engine.py` | Signal Rule Engine — đọc event → kiểm tra điều kiện entry → tạo setup |
| `setup_state_machine.py` | Vòng đời setup: created → pending → armed → triggered → entered → completed |
| `entry_model.py` | Tính giá entry dựa trên OB/FVG vùng giá |
| `sl_model.py` | Tính stop loss dựa trên cấu trúc SMC (dưới OB, trên đỉnh swing) |
| `tp_model.py` | Tính take profit theo risk-reward hoặc FVG đối xứng |
| `filter_engine.py` | Bộ lọc setup — trend filter, PD array filter, MTF confirmation, OB freshness |
| `order_intent_generator.py` | Sinh order_intent.csv từ setup đã trigger |
| `decision_logger.py` | Ghi lý do từng quyết định của strategy |
| `strategy_runner.py` | Orchestrator — chạy bar-by-bar qua event stream |
| `run.py` | CLI: `--events` / `--objects` / `--config` |

### Kết quả kiểm tra

- 500 bars test: tạo 70+ setups từ SMC event stream
- Setup state machine: created → pending → armed → triggered → entered / expired
- Entry model: kiểm tra OB/FVG validity trước khi tính entry price
- Filter engine: trend alignment, PD array check, fresh OB check
- Output: `orders_intent.csv` chuẩn cho Execution Engine

---

## Layer 3: Execution Layer ✅ *(Hoàn thành V1)*

### Vai trò

**Execution Engine** là lớp giả lập "sàn/broker" trong backtest. Nó không tự nghĩ tín hiệu. Nó chỉ nhận `order_intent` từ Strategy Layer rồi trả lời:

- Lệnh có được đặt không?
- Có khớp không? Khớp ở giá nào?
- Spread/slippage/commission tính thế nào?
- SL/TP có bị chạm không?
- Margin có đủ không?
- PnL cuối cùng là bao nhiêu?

### Input

| Dữ liệu | Định dạng | Nguồn |
|---|---|---|
| OHLCV bars | list[dict] | `data_loader.py` (Layer 1) |
| `orders_intent.csv` | CSV với timestamp, symbol, direction, order_type, entry_price, SL, TP, risk% | Layer 2 |
| `symbol_specs.json` | JSON: contract_size, point_size, pip_size, leverage, commission, min_lot | File cấu hình |
| `execution_config.yaml` | YAML: spread mode, slippage, commission, account, margin, position rules | File cấu hình |

### Các Module

| Module | Chức năng |
|---|---|
| `models.py` | Data types: Order, Position, AccountState, BarOHLC (bid/ask) |
| `execution_config.py` | ExecutionConfig dataclass + YAML default |
| `spread_model.py` | Bid/Ask từ spread (fixed / from_data / session-based) |
| `slippage_model.py` | Fixed slippage theo points (hoặc ATR-ratio) |
| `commission_model.py` | Per-lot commission (half entry, half exit) |
| `position_sizing.py` | Risk% × equity / stop_distance → lot (chuẩn hóa min_lot, lot_step) |
| `margin_model.py` | Required margin, used margin, margin level, stop out |
| `fill_model.py` | Conservative OHLC fill rules: market/limit/stop với spread & slippage |
| `order_manager.py` | Order lifecycle: created → accepted → rejected → pending → filled / cancelled / expired |
| `position_manager.py` | Open/close position, PnL (gross, net, R-multiple), MAE/MFE |
| `sl_tp_handler.py` | SL/TP check: long exit = Bid, short exit = Ask. Adversarial khi SL+TP cùng bar |
| `pending_order_handler.py` | Check limit/stop order expiry |
| `account_ledger.py` | Balance, equity, used/free margin, realized/unrealized PnL, daily PnL |
| `trade_recorder.py` | CSV export: orders.csv, trades.csv, positions.csv, equity_curve.csv, account_ledger.csv, execution_decisions.csv |
| `execution_engine.py` | **Orchestrator chính** — process_bar() gồm: SL/TP → expiry → cancel → fill → new intents → MAE/MFE → equity → margin call |
| `run.py` | CLI: `--bar-data` / `--order-intents` / `--demo` / `--config` |

### Output

| File | Nội dung |
|---|---|
| `orders.csv` | Tất cả orders với status (created/filled/rejected/cancelled/expired) |
| `trades.csv` | Closed trades: entry/exit, PnL breakdown, R-multiple, MAE, MFE, holding bars |
| `positions.csv` | All positions (open + closed) với SL/TP tracking |
| `account_ledger.csv` | Event log (OPEN, CLOSE, COMMISSION) với balance before/after |
| `equity_curve.csv` | Bar-by-bar equity, drawdown, open positions count |
| `execution_decisions.csv` | Audit log — lý do từng quyết định của engine |

### Thiết kế V1

| Decision | Choice |
|---|---|
| Hedging | ❌ Không cho phép — một symbol một position |
| Fill model | Conservative OHLC (adversarial khi SL & TP cùng bar) |
| Intrabar | Conservative (worst case) — không tick replay |
| Spread | `from_data` mode, fallback fixed points |
| Slippage | Fixed points per symbol |
| Commission | Per-lot round-turn ÷ 2 |
| Position sizing | `risk_pct × equity / stop_distance` |
| Margin | `notional / leverage` |
| Quote currency | USD (V1) |
| Daily loss limit | 3% → dừng lệnh mới đến ngày hôm sau |

### Kết quả kiểm tra với XAUUSD 15m thật

- **500 bars**, 16 order intents, 8 long + 8 short market orders
- **3 orders filled**, 2 TP hit, 1 còn mở
- **Win rate**: 2/2 (100%)
- **Net PnL**: +$195.06 (gross $197.04, commission -$1.05, spread -$0.93)
- **MAE/MFE recorded** cho mỗi trade
- **Margin an toàn**: $58.91 used / $10,163.73 free
- **CSV output**: 7 files đầy đủ

### Config mẫu

```yaml
execution:
  fill_model: conservative_ohlc
  trade_on_close: false

  spread:
    mode: from_data
    fallback_points:
      XAUUSD: 25
      GBPUSD: 12
      EURUSD: 10

  slippage:
    mode: fixed
    points:
      XAUUSD: 5

  commission:
    mode: per_lot
    per_lot_round_turn:
      XAUUSD: 7.0

  account:
    initial_balance: 10000
    currency: USD
    leverage: 100

  margin:
    enabled: true
    stop_out_level: 0.5

  position:
    allow_hedging: false
    max_positions_per_symbol: 1
    max_total_positions: 3

  risk_limits:
    max_daily_loss_pct: 3.0
    max_open_risk_pct: 2.0
```

### Symbol specs mẫu (`symbol_specs.json`)

```json
{
  "XAUUSD": {
    "quote_currency": "USD",
    "point_size": 0.01,
    "pip_size": 0.1,
    "contract_size": 100,
    "min_lot": 0.01,
    "lot_step": 0.01,
    "commission_per_lot_round_turn": 7.0,
    "leverage": 100
  }
}
```

---

## Nguyên Tắc Xuyên Suốt

| Nguyên tắc | Áp dụng |
|---|---|
| **Không repaint** | Event chỉ được emit tại bar xác nhận, không gán ngược quá khứ |
| **Không nhìn trước tương lai** | Tại bar `t` chỉ biết dữ liệu ≤ `t` |
| **Dữ liệu truyền một chiều** | Layer 1 → Layer 2 → Layer 3, không vòng ngược |
| **Tách biệt trách nhiệm** | SMC Engine không biết strategy; strategy không biết position sizing; execution không tự nghĩ tín hiệu |
| **Có thể kiểm tra độc lập** | Mỗi layer có input/output rõ ràng, có thể test riêng |
| **Pine parity** | Layer 1 phải cho kết quả khớp với Pine indicator |
| **Dữ liệu thật** | 210k+ bars XAUUSD Dukascopy (2017-2025) cho mọi validation |

---

## Flow dữ liệu đầy đủ

```
OHLCV Parquet/CSV
    ↓
┌─────────────────────────────────────────┐
│  SMC EVENT ENGINE (Layer 1)              │
│  Swing → Structure → Liquidity           │
│  → Order Block → FVG → Premium/Discount  │
│  → Zone Management                       │
└─────────────┬───────────────────────────┘
              ↓
    events.csv, snapshots.csv, objects.csv
              ↓
┌─────────────────────────────────────────┐
│  STRATEGY LAYER (Layer 2)                │
│  Setup Engine → Entry/SL/TP Models       │
│  → Filter Engine → Order Intent Gen.     │
└─────────────┬───────────────────────────┘
              ↓
            orders_intent.csv
              ↓
┌─────────────────────────────────────────┐
│  EXECUTION ENGINE (Layer 3)              │
│  Order Manager → Fill Model              │
│  → Spread/Slippage/Commission Models     │
│  → Position Sizing → Margin              │
│  → Position Manager → SL/TP Handler      │
│  → Account Ledger → Trade Recorder       │
└─────────────┬───────────────────────────┘
              ↓
    orders.csv  trades.csv  equity_curve.csv
    account_ledger.csv  execution_decisions.csv
```

---

## Timeline Phát Triển

```
Phase 1: Layer 1 (SMC Event Engine)       ✅ 2026 — Hoàn thành
    - 15 modules, 210k bars validated
    - 0 lookahead violations

Phase 2: Layer 2 (Strategy Layer)          ✅ 2026 — Hoàn thành V1
    - 13 modules, setup state machine
    - Order intent generation

Phase 3: Layer 3 (Execution Layer)         ✅ 2026 — Hoàn thành V1
    - 18 modules, real XAUUSD data verified
    - Conservative OHLC fill, spread,
      slippage, commission, MAE/MFE

Phase 4: End-to-End Integration           ⏳ *Kế tiếp*
    - Pipe Layer 1 → Layer 2 → Layer 3
    - Full backtest pipeline

Phase 5: Pine Parity Test                 🔄 *Chờ dữ liệu Pine thật*
    - So sánh event output Pine vs Python

Phase 6: Walk-Forward Optimization        🔮 *Kế hoạch*
Phase 7: Production Pipeline              🔮 *Kế hoạch*
```

---

## Thư mục dự án

```
D:\PHUCTD\SMC Research\
│
├── smc_event_engine/          # Layer 1 (15 modules)
│   ├── main.py                # SMCEngine orchestrator
│   ├── config.py              # YAML config
│   ├── models.py              # Data types
│   ├── data_loader.py         # Load/validate OHLCV
│   ├── swing_engine.py        # Swing detection
│   ├── structure_engine.py    # BOS/CHOCH
│   ├── order_block_engine.py  # Order blocks
│   ├── fvg_engine.py          # Fair value gaps
│   ├── liquidity_engine.py    # Liquidity sweeps
│   ├── premium_discount_engine.py  # PD zones
│   ├── zone_manager.py        # Zone lifecycle
│   ├── state_store.py         # Market state
│   ├── mtf_engine.py          # Multi-timeframe
│   ├── no_lookahead_guard.py  # Anti-repaint
│   ├── pine_parity.py         # Pine comparison
│   ├── output.py              # CSV export
│   └── run.py                 # CLI
│
├── strategy_layer/            # Layer 2 (13 modules)
│   ├── __init__.py
│   ├── config.py
│   ├── models.py              # Setup, OrderIntent
│   ├── setup_engine.py        # Signal Rule Engine
│   ├── setup_state_machine.py # Vòng đời setup
│   ├── entry_model.py         # Tính entry price
│   ├── sl_model.py            # Tính stop loss
│   ├── tp_model.py            # Tính take profit
│   ├── filter_engine.py       # Bộ lọc
│   ├── order_intent_generator.py
│   ├── decision_logger.py
│   ├── strategy_runner.py     # Orchestrator
│   └── run.py                 # CLI
│
├── execution_layer/           # Layer 3 (18 modules)
│   ├── __init__.py
│   ├── models.py              # Order, Position, AccountState, BarOHLC
│   ├── execution_config.py    # Config dataclass + YAML
│   ├── spread_model.py        # Bid/Ask
│   ├── slippage_model.py      # Fixed slippage
│   ├── commission_model.py    # Per-lot commission
│   ├── position_sizing.py     # Risk → lot
│   ├── margin_model.py        # Margin calculation
│   ├── fill_model.py          # Conservative OHLC fill
│   ├── order_manager.py       # Order lifecycle
│   ├── position_manager.py    # Open/close/MAE/MFE
│   ├── sl_tp_handler.py       # SL/TP checker
│   ├── pending_order_handler.py  # Expiry
│   ├── account_ledger.py      # Balance/equity
│   ├── trade_recorder.py      # CSV export
│   ├── execution_engine.py    # Orchestrator
│   └── run.py                 # CLI
│
├── data/                      # OHLCV data
│   ├── XAUUSD_15m.parquet
│   ├── XAUUSD_1h.parquet
│   └── XAUUSD_4h.parquet
│
├── output/                    # Output mẫu (Execution Engine)
│   ├── orders.csv
│   ├── trades.csv
│   ├── positions.csv
│   ├── equity_curve.csv
│   ├── account_ledger.csv
│   └── execution_decisions.csv
│
├── symbol_specs.json           # Symbol configuration
├── execution_config.yaml       # Execution Engine config
└── SMC_BACKTEST_SYSTEM.md      # File này
```

---

*Cập nhật lần cuối: 16/06/2026*
