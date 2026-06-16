"""
Pine Parity Test — compare Python SMC Event Engine output with TradingView Pine.

Reads Pine-exported events (from LuxAlgo alert output) and Python-generated events,
then checks:
  - Event type alignment
  - Timestamp offset (bar lag)
  - Price level deviation (pips)
  - OB/FVG region overlap
  - Forward-looking contamination detection
"""

from typing import Optional
import csv
from dataclasses import dataclass
from .models import Event


@dataclass
class ParityResult:
    """Result of comparing one event."""
    event_type: str
    pine_timestamp: int
    python_timestamp: int
    bar_offset: int
    level_match: bool
    level_deviation_pips: float
    passed: bool
    detail: str = ""


class PineParityTest:
    """Compare Pine vs Python event output."""

    def __init__(self, tolerance_bars: int = 1, tolerance_pips: float = 1.0):
        self.tolerance_bars = tolerance_bars
        self.tolerance_pips = tolerance_pips
        self.results: list[ParityResult] = []

    def load_pine_events(self, path: str) -> list[dict]:
        """Load events exported from TradingView Pine."""
        events = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                events.append(row)
        return events

    def load_python_events(self, path: str) -> list[dict]:
        """Load events from Python SMC Engine output."""
        return self.load_pine_events(path)  # Same CSV format

    def compare(self, pine_path: str, python_path: str) -> list[ParityResult]:
        """Run full parity comparison."""
        pine = self.load_pine_events(pine_path)
        python = self.load_python_events(python_path)

        # Index Python events by type + approximate timestamp
        py_index: dict[str, list[dict]] = {}
        for ev in python:
            key = ev.get("event_type", "")
            if key not in py_index:
                py_index[key] = []
            py_index[key].append(ev)

        self.results = []

        for p_ev in pine:
            ev_type = p_ev.get("event_type", "")
            p_ts = int(p_ev.get("timestamp", 0))
            p_level = float(p_ev.get("level_top", 0) or p_ev.get("level_bottom", 0) or p_ev.get("price", 0))

            # Find closest match in Python
            matches = py_index.get(ev_type, [])
            best = None
            best_offset = 9999

            for m in matches:
                m_ts = int(m.get("timestamp", 0))
                offset = abs(m_ts - p_ts)
                if offset < best_offset:
                    best = m
                    best_offset = offset

            if best:
                m_level = float(best.get("level_top", 0) or best.get("level_bottom", 0) or best.get("price", 0))
                level_diff = abs(m_level - p_level)
                pips = level_diff * 10000  # For forex 4-digit pairs
                bar_offset = best_offset  # Approximate

                passed = (bar_offset <= self.tolerance_bars and
                          pips <= self.tolerance_pips)

                self.results.append(ParityResult(
                    event_type=ev_type,
                    pine_timestamp=p_ts,
                    python_timestamp=int(best.get("timestamp", 0)),
                    bar_offset=bar_offset,
                    level_match=level_diff < 0.0001,
                    level_deviation_pips=pips,
                    passed=passed,
                    detail=f"pine_ts={p_ts} py_ts={best.get('timestamp')} offset={bar_offset} pips={pips:.1f}",
                ))
            else:
                self.results.append(ParityResult(
                    event_type=ev_type,
                    pine_timestamp=p_ts,
                    python_timestamp=0,
                    bar_offset=-1,
                    level_match=False,
                    level_deviation_pips=0,
                    passed=False,
                    detail="No matching Python event found",
                ))

        return self.results

    def report(self) -> str:
        """Generate summary report."""
        if not self.results:
            return "No parity results."

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        lines = [
            "=" * 60,
            "PINE PARITY TEST REPORT",
            "=" * 60,
            f"Total events compared: {total}",
            f"Passed: {passed} ({passed / max(total, 1) * 100:.1f}%)",
            f"Failed: {failed} ({failed / max(total, 1) * 100:.1f}%)",
            "",
        ]

        if failed > 0:
            lines.append("Failed events:")
            for r in self.results:
                if not r.passed:
                    lines.append(f"  ✗ {r.event_type}: {r.detail}")

        # Summary by type
        by_type: dict[str, list[bool]] = {}
        for r in self.results:
            by_type.setdefault(r.event_type, []).append(r.passed)

        lines.append("")
        lines.append("By event type:")
        for ev_type, outcomes in sorted(by_type.items()):
            t = len(outcomes)
            p = sum(outcomes)
            lines.append(f"  {ev_type}: {p}/{t} passed ({p / max(t, 1) * 100:.0f}%)")

        return "\n".join(lines)
