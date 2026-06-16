"""
Multi-Timeframe Engine — coordinate HTF state with LTF execution.

LuxAlgo reference:
  - HTF levels: request.security(syminfo.tickerid, timeframe, [high[1], low[1], time[1], time])
  - FVG: request.security(..., lookahead=barmerge.lookahead_on)
  
Python implementation:
  - Resample OHLCV to HTF candles
  - Only use CLOSED HTF candles (strict_closed_htf)
  - Map HTF state to each LTF bar
  - Track which HTF candle is "active" for each LTF bar
"""

from typing import Optional, Callable
from .models import Bar, Event
from .config import EngineConfig
from .no_lookahead_guard import NoLookaheadGuard
from .state_store import HTFState


class MTFEngine:
    """
    Multi-timeframe coordination.

    For each LTF bar, provides:
      - Closed HTF bar data (high, low, close, time)
      - HTF state (trend, last pivot, etc.)
      - Safety check: no HTF candle still open at LTF bar time
    """

    def __init__(self, config: EngineConfig, guard: NoLookaheadGuard):
        self.cfg = config.mtf
        self.guard = guard
        self.htf_states: dict[str, HTFState] = {}
        self.htf_bars: dict[str, list[Bar]] = {}

        # Store all bars for resampling
        self.all_bars: list[Bar] = []

    def on_bar(self, bar: Bar, bar_index: int) -> dict[str, HTFState]:
        """
        For each configured HTF timeframe, check if a new HTF candle has closed.
        Returns dict of {timeframe: HTFState}.
        """
        result: dict[str, HTFState] = {}

        for htf_tf in self.cfg.htf_timeframes:
            state = self._update_htf(htf_tf, bar, bar_index)
            if state:
                result[htf_tf] = state

        return result

    def _update_htf(self, htf_tf: str, bar: Bar, bar_index: int) -> Optional[HTFState]:
        """Update and return state for one HTF timeframe."""
        import pandas as pd

        try:
            htf_min = int(htf_tf)
        except ValueError:
            return None

        # Current bar's HTF period
        curr_dt = pd.Timestamp(bar.timestamp, unit='ms')
        curr_period = curr_dt.floor(f'{htf_min}min').timestamp() * 1000

        # Get or create state
        state = self.htf_states.get(htf_tf)
        if state is None:
            state = HTFState(timeframe=htf_tf, current_period_start=curr_period)
            self.htf_states[htf_tf] = state
            self.htf_bars[htf_tf] = []

        # Check if we've moved to a new HTF period
        if curr_period > state.current_period_start:
            # The previous HTF candle just closed
            # Build the closed HTF bar from stored bars
            closed_htf = self._build_htf_bar(state, htf_tf)
            if closed_htf:
                self.htf_bars[htf_tf].append(closed_htf)

                # Guard: HTF timestamp < LTF timestamp
                self.guard.check_htf_timing(
                    closed_htf.timestamp, bar.timestamp, bar_index
                )

            state.current_period_start = curr_period
            state.pending_bars = []

        # Track this bar for the current (open) HTF candle
        state.pending_bars.append(bar)

        # Provide last closed HTF bar if available
        if self.htf_bars[htf_tf]:
            last = self.htf_bars[htf_tf][-1]
            state.last_closed = last
            state.last_high = last.high
            state.last_low = last.low
            state.last_close = last.close

        return state

    def _build_htf_bar(self, state: HTFState, htf_tf: str) -> Optional[Bar]:
        """Aggregate pending LTF bars into one HTF candle."""
        if not state.pending_bars:
            return None
        bars = state.pending_bars
        return Bar(
            timestamp=bars[0].timestamp,
            open=bars[0].open,
            high=max(b.high for b in bars),
            low=min(b.low for b in bars),
            close=bars[-1].close,
            volume=sum(b.volume for b in bars),
            symbol=bars[0].symbol,
            timeframe=htf_tf,
        )

    def get_closed_htf_bars(self, timeframe: str, count: int = 3) -> list[Bar]:
        """Get last N closed HTF bars for a timeframe."""
        bars = self.htf_bars.get(timeframe, [])
        return bars[-count:] if len(bars) >= count else bars[:]

    def validate_timing(self, ltf_bar: Bar) -> list[str]:
        """Check that all HTF references are valid (no lookahead)."""
        errors = []
        for htf_tf, bars in self.htf_bars.items():
            if bars:
                last_htf = bars[-1]
                if last_htf.timestamp >= ltf_bar.timestamp:
                    errors.append(
                        f"HTF {htf_tf} bar at {last_htf.timestamp} "
                        f">= LTF bar at {ltf_bar.timestamp}"
                    )
        return errors
