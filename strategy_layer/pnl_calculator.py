"""
PnL Calculator — mô phỏng forward cho từng order, kiểm tra SL/TP.
Đọc orders từ entry_strategies + dữ liệu Layer 1 để tính win/loss.
"""
import csv, sys
from collections import defaultdict, Counter
from pathlib import Path


def load_ohlc(snapshots_path: str) -> dict:
    """
    Load OHLC từ snapshots.csv.
    Trả về dict: bar_index -> {open, high, low, close, timestamp}
    """
    data = {}
    with open(snapshots_path) as f:
        for row in csv.DictReader(f):
            bi = int(row["bar_index"])
            data[bi] = {
                "timestamp": int(row["timestamp"]),
                "high": float(row.get("last_swing_high", 0)) or 0,
                "low": float(row.get("last_swing_low", 0)) or 0,
                # Snapshot không có OHLC thật → cần events
            }
    return data


def load_bar_prices(events_path: str, snapshots_path: str) -> dict:
    """
    Xây dựng OHLC từ snapshots + events.
    Trả về dict bar_index -> {open, high, low, close}
    
    Note: snapshots không chứa OHLC trực tiếp.
    Cần lấy từ events có price field hoặc từ parquet gốc.
    
    Solution: dùng parquet gốc để có OHLC chính xác.
    """
    import pandas as pd
    df = pd.read_parquet("D:/PHUCTD/SMC Research/data/XAUUSD_15m.parquet")
    
    # Map từ timestamp_utc → bar_index
    # Load snapshots to get timestamp→bar_index mapping
    ts_to_bar = {}
    with open(snapshots_path) as f:
        for row in csv.DictReader(f):
            try:
                ts_to_bar[int(row["timestamp"])] = int(row["bar_index"])
            except:
                pass
    
    # Convert parquet timestamps to ms epoch
    prices = {}
    for _, row in df.iterrows():
        ts = row["timestamp_utc"]
        ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, 'timestamp') else 0
        bi = ts_to_bar.get(ts_ms, -1)
        if bi >= 0:
            prices[bi] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
            }
    
    return prices


def simulate_order(order, prices: dict, max_bars: int = 200) -> dict:
    """
    Mô phỏng 1 order forward.
    
    Trả về:
    {
        "setup_id": str,
        "model": str,
        "direction": int,
        "entry": float,
        "sl": float,
        "tp": float,
        "result": "win" | "loss" | "open" | "unknown",
        "exit_bar": int,
        "exit_price": float,
        "bars_held": int,
        "r_multiple": float,
        "reason": str,
    }
    """
    entry_bar = order.bar_index
    direction = order.direction
    entry = order.entry_price
    sl = order.sl_price
    tp = order.tp_price
    
    result = {
        "setup_id": order.setup_id,
        "model": order.model,
        "direction": "LONG" if direction == 1 else "SHORT",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "result": "unknown",
        "exit_bar": entry_bar,
        "exit_price": entry,
        "bars_held": 0,
        "r_multiple": 0.0,
        "reason": "",
        "entry_bar": entry_bar,
    }
    
    if direction == 1:  # LONG
        risk = entry - sl
        reward = tp - entry
    else:  # SHORT
        risk = sl - entry
        reward = entry - tp
    
    r_multiple_sl = risk if risk > 0 else entry * 0.001
    if risk <= 0:
        result["result"] = "unknown"
        result["reason"] = "invalid_sl"
        return result
    
    # Scan forward
    for bar_offset in range(1, max_bars + 1):
        bi = entry_bar + bar_offset
        bar = prices.get(bi)
        if not bar:
            # Hết dữ liệu
            result["result"] = "open"
            result["reason"] = "no_more_data"
            result["bars_held"] = bar_offset - 1
            return result
        
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        
        if direction == 1:  # LONG
            if l <= sl:
                result["result"] = "loss"
                result["exit_bar"] = bi
                result["exit_price"] = sl
                result["bars_held"] = bar_offset
                result["r_multiple"] = -1.0
                result["reason"] = "sl_hit"
                return result
            if h >= tp:
                result["result"] = "win"
                result["exit_bar"] = bi
                result["exit_price"] = tp
                result["bars_held"] = bar_offset
                result["r_multiple"] = reward / r_multiple_sl
                result["reason"] = "tp_hit"
                return result
        else:  # SHORT
            if h >= sl:
                result["result"] = "loss"
                result["exit_bar"] = bi
                result["exit_price"] = sl
                result["bars_held"] = bar_offset
                result["r_multiple"] = -1.0
                result["reason"] = "sl_hit"
                return result
            if l <= tp:
                result["result"] = "win"
                result["exit_bar"] = bi
                result["exit_price"] = tp
                result["bars_held"] = bar_offset
                result["r_multiple"] = reward / r_multiple_sl
                result["reason"] = "tp_hit"
                return result
    
    # Max bars exceeded
    last_bar = prices.get(entry_bar + max_bars, {})
    last_close = last_bar.get("close", entry) if last_bar else entry
    
    result["result"] = "open"
    result["reason"] = "max_bars_exceeded"
    result["bars_held"] = max_bars
    
    # Estimate PnL
    if direction == 1:
        result["r_multiple"] = (last_close - entry) / r_multiple_sl
    else:
        result["r_multiple"] = (entry - last_close) / r_multiple_sl
    
    return result


def calculate_pnl(all_orders: list, prices: dict, max_bars: int = 200) -> dict:
    """
    Tính PnL cho tất cả orders.
    
    Trả về:
    {
        "total_orders": int,
        "wins": int,
        "losses": int,
        "open": int,
        "win_rate": float,
        "total_r": float,
        "avg_r": float,
        "profit_factor": float,
        "model_stats": { model_name: {...}, ... },
        "results": [ {...}, ... ],
    }
    """
    results = [simulate_order(o, prices, max_bars) for o in all_orders]
    
    wins = [r for r in results if r["result"] == "win"]
    losses = [r for r in results if r["result"] == "loss"]
    opens = [r for r in results if r["result"] == "open"]
    
    total_r = sum(r["r_multiple"] for r in results if r["result"] in ("win", "loss"))
    win_r = sum(r["r_multiple"] for r in wins)
    loss_r = sum(abs(r["r_multiple"]) for r in losses)
    
    total_closed = len(wins) + len(losses)
    
    # Model stats
    models = defaultdict(lambda: {"wins": 0, "losses": 0, "open": 0, "total_r": 0.0})
    for r in results:
        m = r["model"]
        if r["result"] == "win":
            models[m]["wins"] += 1
        elif r["result"] == "loss":
            models[m]["losses"] += 1
        else:
            models[m]["open"] += 1
        models[m]["total_r"] += r["r_multiple"]
    
    model_stats = {}
    for m, s in sorted(models.items()):
        total = s["wins"] + s["losses"] + s["open"]
        wr = s["wins"] / (s["wins"] + s["losses"]) * 100 if (s["wins"] + s["losses"]) > 0 else 0
        model_stats[m] = {
            "total": total,
            "wins": s["wins"],
            "losses": s["losses"],
            "open": s["open"],
            "win_rate": round(wr, 1),
            "total_r": round(s["total_r"], 2),
        }
    
    return {
        "total_orders": len(results),
        "wins": len(wins),
        "losses": len(losses),
        "open": len(opens),
        "closed": total_closed,
        "win_rate": round(len(wins) / total_closed * 100, 1) if total_closed > 0 else 0,
        "total_r": round(total_r, 2),
        "avg_r": round(total_r / total_closed, 2) if total_closed > 0 else 0,
        "profit_factor": round(win_r / loss_r, 2) if loss_r > 0 else float('inf'),
        "avg_bars_held": round(sum(r["bars_held"] for r in results if r["result"] in ("win", "loss")) / total_closed, 1) if total_closed > 0 else 0,
        "model_stats": model_stats,
        "results": results,
    }
