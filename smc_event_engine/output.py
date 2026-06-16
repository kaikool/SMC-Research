"""
Output — Event, Snapshot, and Object loggers.
Produces the 3 files that are the foundation for backtesting.

events.csv     — timestamped SMC events (BOS, CHOCH, OB_CREATED, ...)
snapshots.csv  — per-bar state dump for debugging
objects.csv    — lifecycle of all created objects (OBs, FVGs, zones)
"""

import csv
import os
from typing import TextIO, Optional
from .models import Event, Snapshot, OrderBlock, FVG, Zone
from .config import EngineConfig


class EventLogger:
    """Writes SMC events to CSV — the primary output."""

    FIELDS = [
        "timestamp", "bar_index", "symbol", "timeframe",
        "event_type", "direction", "price",
        "level_top", "level_bottom",
        "source_object_id", "object_id",
        "status", "confirmed", "metadata",
    ]

    def __init__(self, path: str):
        self.path = path
        self.file: Optional[TextIO] = None
        self.writer = None
        self._row_count = 0

    def open(self):
        self.file = open(self.path, "w", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDS)
        self.writer.writeheader()
        return self

    def write(self, event: Event):
        if self.writer is None:
            raise RuntimeError("EventLogger not opened")
        self.writer.writerow({
            "timestamp": event.timestamp,
            "bar_index": event.bar_index,
            "symbol": event.symbol,
            "timeframe": event.timeframe,
            "event_type": event.event_type,
            "direction": event.direction,
            "price": f"{event.price:.5f}" if event.price else "",
            "level_top": f"{event.level_top:.5f}" if event.level_top else "",
            "level_bottom": f"{event.level_bottom:.5f}" if event.level_bottom else "",
            "source_object_id": event.source_object_id,
            "object_id": event.object_id,
            "status": event.status,
            "confirmed": str(event.confirmed),
            "metadata": event.metadata,
        })
        self._row_count += 1

    def write_dict(self, d: dict):
        """Write a raw dict for flexibility."""
        if self.writer is None:
            raise RuntimeError("EventLogger not opened")
        row = {f: d.get(f, "") for f in self.FIELDS}
        if "price" in d and d["price"]:
            row["price"] = f"{d['price']:.5f}"
        if "level_top" in d and d["level_top"]:
            row["level_top"] = f"{d['level_top']:.5f}"
        if "level_bottom" in d and d["level_bottom"]:
            row["level_bottom"] = f"{d['level_bottom']:.5f}"
        self.writer.writerow(row)
        self._row_count += 1

    def close(self):
        if self.file:
            self.file.close()
            self.file = None
            self.writer = None

    @property
    def row_count(self) -> int:
        return self._row_count


class SnapshotLogger:
    """Per-bar state dump — essential for debugging repaint issues."""

    FIELDS = [
        "timestamp", "bar_index",
        "current_trend", "last_swing_high", "last_swing_low",
        "last_internal_high", "last_internal_low",
        "active_ob_count", "active_fvg_count", "active_liquidity_count",
        "in_premium", "in_discount",
        "last_bos_direction", "last_choch_direction",
        "swing_high_crossed", "swing_low_crossed",
        "last_swing_leg", "last_internal_leg",
    ]

    def __init__(self, path: str):
        self.path = path
        self.file: Optional[TextIO] = None
        self.writer = None

    def open(self):
        self.file = open(self.path, "w", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDS)
        self.writer.writeheader()
        return self

    def write(self, snap: Snapshot):
        if self.writer is None:
            raise RuntimeError("SnapshotLogger not opened")
        d = {
            "timestamp": snap.timestamp,
            "bar_index": snap.bar_index,
            "current_trend": snap.current_trend,
            "last_swing_high": f"{snap.last_swing_high:.5f}",
            "last_swing_low": f"{snap.last_swing_low:.5f}",
            "last_internal_high": f"{snap.last_internal_high:.5f}",
            "last_internal_low": f"{snap.last_internal_low:.5f}",
            "active_ob_count": snap.active_ob_count,
            "active_fvg_count": snap.active_fvg_count,
            "active_liquidity_count": snap.active_liquidity_count,
            "in_premium": snap.in_premium,
            "in_discount": snap.in_discount,
            "last_bos_direction": snap.last_bos_direction,
            "last_choch_direction": snap.last_choch_direction,
            "swing_high_crossed": snap.swing_high_crossed,
            "swing_low_crossed": snap.swing_low_crossed,
            "last_swing_leg": snap.last_swing_leg,
            "last_internal_leg": snap.last_internal_leg,
        }
        self.writer.writerow(d)

    def close(self):
        if self.file:
            self.file.close()
            self.file = None
            self.writer = None


class ObjectLogger:
    """Lifecycle of all created objects (OBs, FVGs, zones)."""

    FIELDS = [
        "object_id", "type", "direction",
        "created_at", "active_from",
        "top", "bottom",
        "status",
        "first_touch_at", "mitigated_at", "invalidated_at", "expired_at",
        "source_event",
    ]

    def __init__(self, path: str):
        self.path = path
        self.file: Optional[TextIO] = None
        self.writer = None

    def open(self):
        self.file = open(self.path, "w", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDS)
        self.writer.writeheader()
        return self

    def write_ob(self, ob: OrderBlock):
        if self.writer is None:
            raise RuntimeError("ObjectLogger not opened")
        self.writer.writerow({
            "object_id": ob.id,
            "type": f"ORDER_BLOCK_{'SWING' if ob.structure_type == 'swing' else 'INTERNAL'}",
            "direction": ob.direction,
            "created_at": ob.created_at,
            "active_from": ob.active_from,
            "top": f"{ob.top:.5f}",
            "bottom": f"{ob.bottom:.5f}",
            "status": ob.status,
            "first_touch_at": ob.first_touch_at or "",
            "mitigated_at": ob.mitigated_at or "",
            "invalidated_at": ob.invalidated_at or "",
            "expired_at": ob.expired_at or "",
            "source_event": ob.source_event,
        })

    def write_fvg(self, fvg: FVG):
        if self.writer is None:
            raise RuntimeError("ObjectLogger not opened")
        self.writer.writerow({
            "object_id": fvg.id,
            "type": "FVG",
            "direction": fvg.direction,
            "created_at": fvg.created_at,
            "active_from": fvg.created_at,
            "top": f"{fvg.top:.5f}",
            "bottom": f"{fvg.bottom:.5f}",
            "status": fvg.status,
            "first_touch_at": "",
            "mitigated_at": "",
            "invalidated_at": fvg.invalidated_at or "",
            "expired_at": "",
            "source_event": "",
        })

    def write_zone(self, zone: Zone):
        if self.writer is None:
            raise RuntimeError("ObjectLogger not opened")
        self.writer.writerow({
            "object_id": zone.id,
            "type": zone.zone_type.upper(),
            "direction": zone.direction,
            "created_at": zone.created_at,
            "active_from": zone.created_at,
            "top": f"{zone.top:.5f}",
            "bottom": f"{zone.bottom:.5f}",
            "status": zone.status,
            "first_touch_at": "",
            "mitigated_at": "",
            "invalidated_at": "",
            "expired_at": "",
            "source_event": "",
        })

    def close(self):
        if self.file:
            self.file.close()
            self.file = None
            self.writer = None


class CombinedOutput:
    """Convenience wrapper — manages all 3 loggers together."""

    def __init__(self, config: EngineConfig):
        self.event_logger = EventLogger(config.logging.events_path)
        self.snapshot_logger = SnapshotLogger(config.logging.snapshots_path)
        self.object_logger = ObjectLogger(config.logging.objects_path)

    def open_all(self):
        self.event_logger.open()
        self.snapshot_logger.open()
        self.object_logger.open()
        return self

    def close_all(self):
        self.event_logger.close()
        self.snapshot_logger.close()
        self.object_logger.close()

    def write_event(self, event: Event):
        self.event_logger.write(event)

    def write_snapshot(self, snap: Snapshot):
        self.snapshot_logger.write(snap)

    def write_ob(self, ob: OrderBlock):
        self.object_logger.write_ob(ob)

    def write_fvg(self, fvg: FVG):
        self.object_logger.write_fvg(fvg)

    def write_zone(self, zone: Zone):
        self.object_logger.write_zone(zone)
