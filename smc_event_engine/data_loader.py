"""
Data Loader — OHLCV validation & loading.
LuxAlgo-compatible data format with strict validation.
"""

import pandas as pd
import numpy as np
from typing import Optional
from .models import Bar


# ── Required columns ──────────────────────────────────────────────────
REQUIRED_COLS = {"timestamp", "open", "high", "low", "close"}
OPTIONAL_COLS = {"volume", "tick_volume", "spread", "symbol", "timeframe"}


def validate_bars(bars: list[Bar]) -> list[str]:
    """Return all validation errors across the bar list."""
    errors = []
    seen_ts: set = set()

    for i, bar in enumerate(bars):
        # Individual bar validation
        bar_errors = bar.validate()
        for e in bar_errors:
            errors.append(f"bar[{i}] @ {bar.timestamp}: {e}")

        # Duplicate timestamp
        if bar.timestamp in seen_ts:
            errors.append(f"bar[{i}]: duplicate timestamp {bar.timestamp}")
        seen_ts.add(bar.timestamp)

        # Timestamp order
        if i > 0 and bar.timestamp <= bars[i - 1].timestamp:
            errors.append(f"bar[{i}]: timestamp {bar.timestamp} ≤ previous {bars[i-1].timestamp}")

    return errors


def load_bars_from_csv(path: str, symbol: str = "", timeframe: str = "",
                        timestamp_col: str = "timestamp") -> list[Bar]:
    """
    Load OHLCV from CSV. Flexible column naming.
    Returns validated Bar list.
    """
    df = pd.read_csv(path)

    # Normalise column names
    col_map = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl in ("timestamp", "time", "date", "datetime", "t"):
            col_map[c] = "timestamp"
        elif cl in ("open", "o"):
            col_map[c] = "open"
        elif cl in ("high", "h"):
            col_map[c] = "high"
        elif cl in ("low", "l"):
            col_map[c] = "low"
        elif cl in ("close", "c"):
            col_map[c] = "close"
        elif cl in ("volume", "vol", "v", "tick_volume", "tickvol", "tv"):
            col_map[c] = "volume" if "tick" not in cl else "tick_volume"
        elif cl in ("spread", "s"):
            col_map[c] = "spread"
        elif cl in ("symbol", "pair", "ticker"):
            col_map[c] = "symbol"
        elif cl in ("timeframe", "tf", "resolution"):
            col_map[c] = "timeframe"

    df = df.rename(columns=col_map)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

    bars = []
    for _, row in df.iterrows():
        ts = _parse_timestamp(row["timestamp"])
        bar = Bar(
            timestamp=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            tick_volume=float(row.get("tick_volume", 0)),
            spread=float(row.get("spread", 0)),
            symbol=str(row.get("symbol", symbol)),
            timeframe=str(row.get("timeframe", timeframe)),
        )
        bars.append(bar)

    errors = validate_bars(bars)
    if errors:
        from warnings import warn
        for e in errors[:20]:
            warn(f"Data validation: {e}")
        if len(errors) > 20:
            warn(f"... and {len(errors) - 20} more errors")

    return bars


def _parse_timestamp(val) -> int:
    """Parse a timestamp value to millisecond epoch int."""
    if isinstance(val, (int, float)):
        # Could be seconds / milliseconds / microseconds / nanoseconds.
        # Modern millisecond epoch values are ~1.7e12, so do NOT classify
        # them as nanoseconds.
        if val > 1e17:  # nanosecond → millis
            return int(val / 1_000_000)
        elif val > 1e14:  # microsecond → millis
            return int(val / 1_000)
        elif val > 1e11:  # millisecond
            return int(val)
        else:  # second
            return int(val * 1000)
    if isinstance(val, str):
        dt = pd.Timestamp(val)
        return int(dt.timestamp() * 1000)
    raise ValueError(f"Cannot parse timestamp: {val}")


def bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    """Convert bars back to a DataFrame for analysis."""
    records = []
    for b in bars:
        records.append({
            "timestamp": b.timestamp,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "symbol": b.symbol,
            "timeframe": b.timeframe,
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def load_bars_from_parquet(path: str, symbol: str = "XAUUSD",
                             timeframe: str = "15") -> list[Bar]:
    """
    Load bars from a parquet file (Dukascopy format).

    Expected columns: symbol, timestamp_utc, open, high, low, close, volume
    """
    import pandas as pd
    df = pd.read_parquet(path)

    # Auto-detect timestamp column
    ts_col = None
    for c in df.columns:
        cl = c.lower()
        if "timestamp" in cl or "time" in cl:
            ts_col = c
            break
    if ts_col is None:
        ts_col = df.columns[0]

    bars = []
    for _, row in df.iterrows():
        ts = row[ts_col]
        if hasattr(ts, 'timestamp'):
            ts_ms = int(ts.timestamp() * 1000)
        else:
            ts_ms = int(pd.Timestamp(ts).timestamp() * 1000)

        col_map = {c.lower(): c for c in df.columns}
        bar = Bar(
            timestamp=ts_ms,
            open=float(row.get(col_map.get("open", "open"), row.iloc[1])),
            high=float(row.get(col_map.get("high", "high"), row.iloc[2])),
            low=float(row.get(col_map.get("low", "low"), row.iloc[3])),
            close=float(row.get(col_map.get("close", "close"), row.iloc[4])),
            volume=float(row.get(col_map.get("volume", "volume"), 0)),
            symbol=symbol,
            timeframe=timeframe,
        )
        bars.append(bar)

    errors = validate_bars(bars)
    if errors:
        from warnings import warn
        for e in errors[:20]:
            warn(f"Data validation: {e}")
        if len(errors) > 20:
            warn(f"... and {len(errors) - 20} more errors")

    return bars


def generate_sample_bars(n: int = 500, timeframe: str = "15",
                         seed: int = 42) -> list[Bar]:
    """Generate synthetic OHLCV data with realistic SMC structure.

    Creates trending phases, range-bound phases, and breakouts
    so the SMC engine can demonstrate BOS/CHOCH patterns clearly.
    """
    rng = np.random.default_rng(seed)
    bars = []
    ts = int(pd.Timestamp("2024-01-01").timestamp() * 1000)
    step_ms = int(pd.Timedelta(minutes=int(timeframe)).total_seconds() * 1000)

    price = 1.1000
    trend = 0  # -1 downtrend, 0 range, +1 uptrend
    trend_duration = 0
    volatility = 0.0003

    for i in range(n):
        # Change trend periodically
        if trend_duration <= 0:
            trend = rng.choice([-1, 0, 0, 1, 1, 1])  # bias toward up/ranging
            trend_duration = rng.integers(20, 80)
        trend_duration -= 1

        # Price change based on trend
        if trend == 0:
            change = rng.normal(0, volatility)
        elif trend == 1:
            change = abs(rng.normal(0.0003, volatility))
        else:
            change = -abs(rng.normal(0.0003, volatility))

        o = price
        c = price + change
        vol = abs(change) + volatility
        wick_top = rng.uniform(0, vol * 0.4)
        wick_bot = rng.uniform(0, vol * 0.4)
        h = max(o, c) + wick_top
        l = min(o, c) - wick_bot

        bar = Bar(
            timestamp=ts + i * step_ms,
            open=round(o, 5),
            high=round(h, 5),
            low=round(l, 5),
            close=round(c, 5),
            volume=rng.uniform(100, 10000),
            symbol="EURUSD",
            timeframe=timeframe,
        )
        bars.append(bar)
        price = c

    return bars
