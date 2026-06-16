"""
Layer 2: Strategy Layer — chuyển SMC event stream thành tín hiệu giao dịch.

Vai trò:
  - Đọc events.csv, snapshots.csv, objects.csv từ Layer 1
  - Áp dụng entry rule (ví dụ: Sweep + CHOCH + OB → setup)
  - Tính SL/TP dựa trên vùng SMC
  - Xuất setups.csv, orders_intent.csv, strategy_decisions.csv

Chưa bao gồm: position sizing, risk management, PnL (thuộc Layer 3).

Modules:
  - config.py: YAML config system
  - models.py: Setup, OrderIntent, StrategyDecision
  - setup_engine.py: Signal Rule Engine
  - setup_state_machine.py: Vòng đời setup
  - entry_model.py: Tính giá entry
  - sl_model.py: Tính stop loss
  - tp_model.py: Tính take profit
  - filter_engine.py: Bộ lọc setup
  - order_intent_generator.py: Sinh order intent
  - decision_logger.py: Ghi lý do quyết định
  - strategy_runner.py: Orchestrator chính
  - run.py: CLI

Author: SMC Backtest System
"""
