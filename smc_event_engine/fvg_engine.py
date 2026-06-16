"""
FVG Engine — Fair Value Gap detection (LuxAlgo HTF 3-bar method).

LuxAlgo logic:
  - Uses request.security() to get HTF data
  - Bullish FVG: currentLow > last2High (when current TF candle opens, gap between last's high and 2nd last's high)
  - Bearish FVG: currentHigh < last2Low
  - Auto threshold: cumulative delta / bar_index * 2
  - Each FVG drawn as two boxes (top half, bottom half)
  - Deletion: price fills the gap

Python implementation:
  - Simplified for bar-by-bar processing
  - Supports both HTF (LuxAlgo) and same-TF detection
"""

from typing import Optional
from .models import FVG, Bar, Event, Snapshot
from .config import EngineConfig, BULLISH, BEARISH, FVG_ACTIVE, FVG_PARTIAL, FVG_FILLED, FVG_INVALIDATED
from .no_lookahead_guard import NoLookaheadGuard


class FVGEngine:
    """Detect, manage, and expire Fair Value Gaps."""

    def __init__(self, config: EngineConfig, guard: NoLookaheadGuard):
        self.cfg = config
        self.guard = guard
        self.fair_value_gaps: list[FVG] = []
        self._fvg_counter = 0

        # HTF resampling state
        self.htf_bars: list[Bar] = []

    def on_bar(self, bar: Bar, bar_index: int,
               all_bars: list[Bar], atr_value: float) -> list[Event]:
        """Process one bar for FVG detection and management."""
        events: list[Event] = []

        # Delete filled/invalidated FVGs first (LuxAlgo order)
        del_events = self._check_fvg_fill(bar, bar_index)
        events.extend(del_events)

        # Detect new FVGs (LuxAlgo: drawFairValueGaps)
        if self.cfg.fvg.use_htf:
            new_events = self._detect_htf_fvg(bar, bar_index, all_bars, atr_value)
        else:
            new_events = self._detect_same_tf_fvg(bar, bar_index, all_bars, atr_value)
        events.extend(new_events)

        return events

    def _detect_htf_fvg(self, bar: Bar, bar_index: int,
                         all_bars: list[Bar], atr_value: float) -> list[Event]:
        """LuxAlgo-style HTF FVG detection on timeframe change."""
        events: list[Event] = []
        htf_tf = self.cfg.fvg.htf_timeframe
        if not htf_tf or not all_bars:
            return events

        # Detect timeframe change
        if bar_index < 3:
            return events

        # Get the HTF bar boundaries (simplified: detect bar time grouping)
        # In practice: compare bar timestamps against HTF period
        is_new_htf_bar = self._is_new_htf_bar(bar, bar_index, all_bars)

        if not is_new_htf_bar:
            return events

        # We need 3 closed bars of the HTF
        # Find the last 3 HTF bars ending just before this bar
        htf_bars = self._get_closed_htf_bars(bar_index, all_bars, 3)
        if len(htf_bars) < 3:
            return events

        b3, b2, b1 = htf_bars[-3], htf_bars[-2], htf_bars[-1]  # oldest → newest

        # Bar delta for threshold (LuxAlgo)
        bar_delta_pct = (b1.close - b1.open) / (b1.open * 100) if b1.open != 0 else 0

        # Auto threshold (LuxAlgo: cumulative mean of |bar_delta| at HTF bar transitions)
        threshold = 0.0
        if self.cfg.fvg.auto_threshold:
            # Simplified: use a basic threshold based on ATR
            threshold = 0.0  # LuxAlgo thresholding is complex; default to no filter

        # ── Bullish FVG: current bar's low > 2nd last high ──
        # In LuxAlgo: currentLow > last2High (where current = b1[open], last2 = b3)
        bullish_fvg = b1.low > b3.high and b1.close > b3.high and bar_delta_pct > threshold

        # ── Bearish FVG: current bar's high < 2nd last low ──
        bearish_fvg = b1.high < b3.low and b1.close < b3.low and -bar_delta_pct > threshold

        if bullish_fvg:
            self._fvg_counter += 1
            fvg = FVG(
                id=f"FVG_{self._fvg_counter}",
                direction=BULLISH,
                top=b1.low,
                bottom=b3.high,
                mid=(b1.low + b3.high) / 2,
                left_bar=b3.bar_index if hasattr(b3, 'bar_index') else 0,
                middle_bar=b2.bar_index if hasattr(b2, 'bar_index') else 0,
                right_bar=b1.bar_index if hasattr(b1, 'bar_index') else 0,
                created_at=bar.timestamp,
                status=FVG_ACTIVE,
            )
            self.fair_value_gaps.insert(0, fvg)
            events.append(Event(
                timestamp=bar.timestamp, bar_index=bar_index,
                symbol=bar.symbol, timeframe=bar.timeframe,
                event_type="FVG_CREATED", direction=BULLISH,
                price=bar.close, level_top=fvg.top, level_bottom=fvg.bottom,
                object_id=fvg.id, status=FVG_ACTIVE, confirmed=True,
            ))

        if bearish_fvg:
            self._fvg_counter += 1
            fvg = FVG(
                id=f"FVG_{self._fvg_counter}",
                direction=BEARISH,
                top=b1.high,
                bottom=b3.low,
                mid=(b1.high + b3.low) / 2,
                left_bar=b3.bar_index if hasattr(b3, 'bar_index') else 0,
                middle_bar=b2.bar_index if hasattr(b2, 'bar_index') else 0,
                right_bar=b1.bar_index if hasattr(b1, 'bar_index') else 0,
                created_at=bar.timestamp,
                status=FVG_ACTIVE,
            )
            self.fair_value_gaps.insert(0, fvg)
            events.append(Event(
                timestamp=bar.timestamp, bar_index=bar_index,
                symbol=bar.symbol, timeframe=bar.timeframe,
                event_type="FVG_CREATED", direction=BEARISH,
                price=bar.close, level_top=fvg.top, level_bottom=fvg.bottom,
                object_id=fvg.id, status=FVG_ACTIVE, confirmed=True,
            ))

        return events

    def _detect_same_tf_fvg(self, bar: Bar, bar_index: int,
                             all_bars: list[Bar], atr_value: float) -> list[Event]:
        """Same-timeframe FVG using 3 consecutive bars — LuxAlgo logic.
        
        Bullish FVG: bar[0].low > bar[2].high (gap up)
        Bearish FVG: bar[0].high < bar[2].low (gap down)
        """
        events: list[Event] = []
        if bar_index < 2:
            return events

        b2 = all_bars[bar_index - 2]  # 2 bars ago
        
        # Bullish FVG: current low > 2nd last high
        if bar.low > b2.high:
            self._fvg_counter += 1
            top, bot = bar.low, b2.high
            fvg = FVG(
                id=f"FVG_{self._fvg_counter}", direction=BULLISH,
                top=top, bottom=bot, mid=(top + bot) / 2,
                left_bar=bar_index - 2, middle_bar=bar_index - 1, right_bar=bar_index,
                created_at=bar.timestamp, status=FVG_ACTIVE,
            )
            self.fair_value_gaps.insert(0, fvg)
            events.append(Event(
                timestamp=bar.timestamp, bar_index=bar_index,
                symbol=bar.symbol, timeframe=bar.timeframe,
                event_type="FVG_CREATED", direction=BULLISH,
                price=bar.close, level_top=top, level_bottom=bot,
                object_id=fvg.id, status=FVG_ACTIVE, confirmed=True,
            ))

        # Bearish FVG: current high < 2nd last low
        if bar.high < b2.low:
            self._fvg_counter += 1
            top, bot = b2.low, bar.high
            fvg = FVG(
                id=f"FVG_{self._fvg_counter}", direction=BEARISH,
                top=top, bottom=bot, mid=(top + bot) / 2,
                left_bar=bar_index - 2, middle_bar=bar_index - 1, right_bar=bar_index,
                created_at=bar.timestamp, status=FVG_ACTIVE,
            )
            self.fair_value_gaps.insert(0, fvg)
            events.append(Event(
                timestamp=bar.timestamp, bar_index=bar_index,
                symbol=bar.symbol, timeframe=bar.timeframe,
                event_type="FVG_CREATED", direction=BEARISH,
                price=bar.close, level_top=top, level_bottom=bot,
                object_id=fvg.id, status=FVG_ACTIVE, confirmed=True,
            ))

        return events

    def _check_fvg_fill(self, bar: Bar, bar_index: int) -> list[Event]:
        """Check if any active FVG has been filled.

        LuxAlgo: delete FVG if (low < bottom for bullish) or (high > top for bearish).
        Spec: partial/fill tracking.
        """
        events: list[Event] = []
        to_remove: list[int] = []

        for idx, fvg in enumerate(self.fair_value_gaps):
            if fvg.status not in (FVG_ACTIVE, FVG_PARTIAL):
                continue

            if fvg.direction == BULLISH:
                # Bullish FVG filled when low goes below bottom
                if bar.low < fvg.bottom:
                    fvg.status = FVG_FILLED
                    fvg.filled_at = bar.timestamp
                    fvg.filled_ratio = 1.0
                    events.append(Event(
                        timestamp=bar.timestamp, bar_index=bar_index,
                        symbol=bar.symbol, timeframe=bar.timeframe,
                        event_type="FVG_FILLED", direction=BULLISH,
                        price=bar.close, level_top=fvg.top, level_bottom=fvg.bottom,
                        object_id=fvg.id, status=FVG_FILLED, confirmed=True,
                    ))
                    to_remove.append(idx)
                elif bar.high < fvg.top and bar.low > fvg.bottom:
                    # Price is inside the gap → partial fill
                    fill = (fvg.top - bar.high) / (fvg.top - fvg.bottom) if fvg.top != fvg.bottom else 0
                    if fill > fvg.filled_ratio:
                        fvg.filled_ratio = fill
                        if fvg.status == FVG_ACTIVE:
                            fvg.status = FVG_PARTIAL

            else:  # BEARISH
                if bar.high > fvg.top:
                    fvg.status = FVG_FILLED
                    fvg.filled_at = bar.timestamp
                    fvg.filled_ratio = 1.0
                    events.append(Event(
                        timestamp=bar.timestamp, bar_index=bar_index,
                        symbol=bar.symbol, timeframe=bar.timeframe,
                        event_type="FVG_FILLED", direction=BEARISH,
                        price=bar.close, level_top=fvg.top, level_bottom=fvg.bottom,
                        object_id=fvg.id, status=FVG_FILLED, confirmed=True,
                    ))
                    to_remove.append(idx)
                elif bar.high < fvg.top and bar.low > fvg.bottom:
                    fill = (fvg.top - bar.high) / (fvg.top - fvg.bottom) if fvg.top != fvg.bottom else 0
                    if fill > fvg.filled_ratio:
                        fvg.filled_ratio = fill
                        if fvg.status == FVG_ACTIVE:
                            fvg.status = FVG_PARTIAL

        for idx in sorted(to_remove, reverse=True):
            self.fair_value_gaps.pop(idx)

        return events

    def _is_new_htf_bar(self, bar: Bar, bar_index: int, all_bars: list[Bar]) -> bool:
        """Detect if this bar starts a new HTF period."""
        import pandas as pd
        htf_tf = self.cfg.fvg.htf_timeframe
        if not htf_tf or bar_index < 1:
            return False

        # Convert HTF timeframe string to minutes
        try:
            htf_minutes = int(htf_tf)
        except ValueError:
            return False

        # Check if previous bar is in a different HTF period
        prev_dt = pd.Timestamp(all_bars[bar_index - 1].timestamp, unit='ms')
        curr_dt = pd.Timestamp(bar.timestamp, unit='ms')

        # Round down to HTF boundary
        prev_rounded = prev_dt.floor(f'{htf_minutes}min')
        curr_rounded = curr_dt.floor(f'{htf_minutes}min')

        return curr_rounded != prev_rounded

    def _get_closed_htf_bars(self, bar_index: int, all_bars: list[Bar],
                              count: int) -> list[Bar]:
        """
        Get the last `count` fully-closed HTF bars.
        This ensures no lookahead (a HTF bar is only used after it closes).
        """
        if bar_index < 1:
            return []

        htf_tf = self.cfg.fvg.htf_timeframe
        if not htf_tf:
            return []

        import pandas as pd
        try:
            htf_minutes = int(htf_tf)
        except ValueError:
            return []

        # Current bar starts a new HTF candle
        # So the last complete HTF candle ended at the previous bar
        curr_ts = all_bars[bar_index].timestamp

        # Walk backwards collecting bars grouped by HTF period
        groups: list[list[Bar]] = []
        current_group: list[Bar] = []

        for i in range(bar_index - 1, -1, -1):
            b = all_bars[i]
            dt = pd.Timestamp(b.timestamp, unit='ms')
            period_start = dt.floor(f'{htf_minutes}min')
            period_key = period_start.timestamp() * 1000

            if not current_group:
                current_group.append(b)
            else:
                prev_b = current_group[0]
                prev_dt = pd.Timestamp(prev_b.timestamp, unit='ms')
                prev_period = prev_dt.floor(f'{htf_minutes}min').timestamp() * 1000
                if period_key == prev_period:
                    current_group.append(b)
                else:
                    groups.append(list(reversed(current_group)))
                    current_group = [b]
                    if len(groups) >= count:
                        break

        if current_group and len(groups) < count:
            groups.append(list(reversed(current_group)))

        # Groups are oldest-first by construction
        groups.reverse()

        # Build aggregate bars for each group
        result = []
        for g in groups:
            o = g[0].open
            h = max(b.high for b in g)
            l = min(b.low for b in g)
            c = g[-1].close
            agg = Bar(
                timestamp=g[0].timestamp,
                open=o, high=h, low=l, close=c,
                volume=sum(b.volume for b in g),
                symbol=g[0].symbol,
                timeframe=htf_tf,
            )
            agg.bar_index = g[0].bar_index  # type: ignore
            result.append(agg)

        return result

    @property
    def active_count(self) -> int:
        return sum(1 for fvg in self.fair_value_gaps if fvg.status == FVG_ACTIVE)
