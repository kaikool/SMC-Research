"""
Execution Engine — CLI Runner.

Usage:
    python -m execution_layer.run --bar-data bars.csv --order-intents orders_intent.csv
    python -m execution_layer.run --bar-data data/XAUUSD_15m.parquet --order-intents strategy_layer/orders_intent.csv
    python -m execution_layer.run --demo

Đọc bars từ CSV/parquet, order intents từ CSV, chạy backtest, xuất kết quả.
"""

import argparse
import sys
import os
import json
import pandas as pd

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution_layer.execution_config import ExecutionConfig, DEFAULT_EXECUTION_YAML
from execution_layer.execution_engine import ExecutionEngine
# ORDER_INTENT_FIELDS imported locally where needed


def load_bars_from_csv(path: str, symbol: str = "XAUUSD", timeframe: str = "15") -> list[dict]:
    """Load CSV → list of bar dicts."""
    df = pd.read_csv(path)
    return _df_to_bars(df, symbol, timeframe)


def load_bars_from_parquet(path: str, symbol: str = "XAUUSD",
                            timeframe: str = "15") -> list[dict]:
    """Load parquet → list of bar dicts."""
    df = pd.read_parquet(path)
    return _df_to_bars(df, symbol, timeframe)


def _df_to_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    """Convert DataFrame to bar dicts."""
    bars = []

    # Map columns
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if "timestamp" in cl or "time" in cl:
            col_map[c] = "timestamp"
        elif cl == "open" or cl == "o":
            col_map[c] = "open"
        elif cl == "high" or cl == "h":
            col_map[c] = "high"
        elif cl == "low" or cl == "l":
            col_map[c] = "low"
        elif cl == "close" or cl == "c":
            col_map[c] = "close"
        elif "volume" in cl or cl == "vol" or cl == "v":
            col_map[c] = "volume"
        elif "spread" in cl:
            col_map[c] = "spread_points"

    df = df.rename(columns=col_map)

    for i, (_, row) in enumerate(df.iterrows()):
        ts = row.get("timestamp", 0)
        if hasattr(ts, 'timestamp'):
            ts_ms = int(ts.timestamp() * 1000)
        elif hasattr(ts, 'value'):  # pandas Timestamp
            ts_ms = int(ts.timestamp() * 1000)
        else:
            try:
                ts_ms = int(float(ts))
                if ts_ms > 1e12:  # nanosecond
                    ts_ms = int(ts_ms / 1_000_000)
                elif ts_ms > 1e9:
                    ts_ms = int(ts_ms / 1_000)
            except (ValueError, TypeError):
                ts_ms = i * 15 * 60 * 1000

        bar = {
            "timestamp": ts_ms,
            "bar_index": i,
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": float(row.get("volume", 0)),
            "spread_points": float(row.get("spread_points", 0)),
        }
        bars.append(bar)

    return bars


def load_symbol_specs(path: str) -> dict:
    """Load symbol_specs.json."""
    if not path or not os.path.exists(path):
        print("WARNING: symbol_specs.json not found, using defaults")
        return {
            "XAUUSD": {
                "quote_currency": "USD",
                "point_size": 0.01,
                "pip_size": 0.1,
                "contract_size": 100,
                "min_lot": 0.01,
                "lot_step": 0.01,
                "max_lot": 100.0,
                "commission_per_lot_round_turn": 7.0,
                "leverage": 100,
                "base_spread_points": 25,
            }
        }
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="SMC Execution Engine — Backtest Broker Simulator")
    parser.add_argument("--bar-data", type=str, default="",
                        help="Path to OHLCV data (CSV or parquet)")
    parser.add_argument("--order-intents", type=str, default="",
                        help="Path to orders_intent.csv from Strategy Layer")
    parser.add_argument("--config", type=str, default="",
                        help="Path to YAML config file")
    parser.add_argument("--symbol", type=str, default="XAUUSD",
                        help="Symbol name")
    parser.add_argument("--tf", type=str, default="15",
                        help="Timeframe in minutes")
    parser.add_argument("--output-dir", type=str, default=".",
                        help="Output directory for CSVs")
    parser.add_argument("--symbol-specs", type=str, default="symbol_specs.json",
                        help="Path to symbol_specs.json")
    parser.add_argument("--demo", action="store_true",
                        help="Run with synthetic demo data")
    parser.add_argument("--bars-limit", type=int, default=0,
                        help="Limit bars to process (0 = all)")
    parser.add_argument("--save-config", action="store_true",
                        help="Save default config to execution_config.yaml")
    args = parser.parse_args()

    # ── Save default config ──
    if args.save_config:
        path = "execution_config.yaml"
        with open(path, "w") as f:
            f.write(DEFAULT_EXECUTION_YAML)
        print(f"Default config saved to {path}")
        return

    # ── Load config ──
    config = ExecutionConfig()
    if args.config and os.path.exists(args.config):
        config = ExecutionConfig.from_yaml(args.config)
        print(f"Loaded config from {args.config}")
    else:
        print("Using default execution config")

    # ── Load symbol specs ──
    symbol_specs = load_symbol_specs(args.symbol_specs)
    print(f"Loaded specs for {len(symbol_specs)} symbols")

    # ── Load bar data ──
    bars = []
    if args.demo:
        print("Generating synthetic bars...")
        from smc_event_engine.data_loader import generate_sample_bars
        sample = generate_sample_bars(500, timeframe=args.tf)
        bars = []
        for i, b in enumerate(sample):
            bars.append({
                "timestamp": b.timestamp,
                "bar_index": i,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "spread_points": 0,
            })
        print(f"Generated {len(bars)} bars")
    elif args.bar_data:
        path = args.bar_data
        if path.endswith(".parquet"):
            bars = load_bars_from_parquet(path, args.symbol, args.tf)
        else:
            bars = load_bars_from_csv(path, args.symbol, args.tf)
        print(f"Loaded {len(bars)} bars from {path}")
    else:
        print("Error: provide --bar-data or --demo flag.")
        sys.exit(1)

    # ── Limit bars ──
    if args.bars_limit > 0 and len(bars) > args.bars_limit:
        bars = bars[:args.bars_limit]
        print(f"Limited to {len(bars)} bars")

    # ── Load order intents ──
    order_intents_by_bar = {}
    if args.order_intents and os.path.exists(args.order_intents):
        engine_stub = ExecutionEngine(config, symbol_specs)
        order_intents_by_bar = engine_stub.load_order_intents(args.order_intents)
        print(f"Loaded order intents from {args.order_intents}")

    # ── Run engine ──
    print(f"\nRunning Execution Engine on {len(bars)} bars...")
    engine = ExecutionEngine(config, symbol_specs)

    # Process bar by bar with intents
    for i, bar_dict in enumerate(bars):
        bi = bar_dict["bar_index"]
        intents = order_intents_by_bar.get(bi, [])

        # Create BarOHLC (engine.load_bars will be called internally via process_bar)
        # Actually let's just process directly
        from execution_layer.models import BarOHLC
        bar = BarOHLC(
            timestamp=bar_dict["timestamp"],
            bar_index=bi,
            open=bar_dict["open"],
            high=bar_dict["high"],
            low=bar_dict["low"],
            close=bar_dict["close"],
            volume=bar_dict.get("volume", 0),
            spread_points=bar_dict.get("spread_points", 0),
        )
        # Compute bid/ask
        engine.spread_model.compute_bid_ask_for_bar(bar)
        engine._bars.append(bar)
        engine._bar_map[bi] = bar

        if i % 10000 == 0 and i > 0:
            print(f"  Processing bar {i}/{len(bars)}...")

        engine.process_bar(bar, intents)

    # ── Export ──
    paths = engine.export_csv(args.output_dir)

    # ── Report ──
    summary = engine.summarize()
    print(f"\n{'='*60}")
    print(f"EXECUTION ENGINE — COMPLETE")
    print(f"{'='*60}")
    print(f"  Bars processed: {len(bars)}")
    print(f"  Total orders:   {summary['total_orders']}")
    print(f"  Filled:         {summary['filled_orders']}")
    print(f"  Rejected:       {summary['rejected']}")
    print(f"  Cancelled:      {summary['cancelled']}")
    print(f"  Expired:        {summary['expired']}")
    print(f"  Positions:      {summary['closed_positions']} closed / {summary['total_positions']} total")
    print(f"  Win rate:       {summary['win_rate']:.1f}%")
    print(f"  Gross PnL:      ${summary['total_gross_pnl']:.2f}")
    print(f"  Commission:     ${summary['total_commission']:.2f}")
    print(f"  Spread cost:    ${summary['total_spread_cost']:.2f}")
    print(f"  Net PnL:        ${summary['total_net_pnl']:.2f}")
    print(f"  Final balance:  ${summary['account_balance']:.2f}")
    print(f"  Final equity:   ${summary['account_equity']:.2f}")
    print(f"\n  Output files:")
    for name, path in sorted(paths.items()):
        print(f"    {name} → {os.path.abspath(path)}")
    print(f"{'='*60}")

    # Show sample trades
    closed = [p for p in engine.position_manager.positions if p.status == "closed"]
    if closed:
        print(f"\nSample trades (first 5):")
        for p in closed[:5]:
            print(f"  {p.position_id} | {p.symbol} {p.direction:+d} | "
                  f"entry={p.entry_price:.2f} exit={p.exit_price:.2f} | "
                  f"PnL={p.net_pnl:.2f} R={p.r_multiple:.2f} | {p.exit_reason}")


if __name__ == "__main__":
    main()
