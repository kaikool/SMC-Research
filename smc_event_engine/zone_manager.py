"""
Zone Manager — central lifecycle for all SMC zones.

Responsible for:
  - Adding / updating / removing zones
  - Checking touches, mitigations, invalidations, expiries
  - Limiting max active zones
  - Coordinating between OB, FVG, Liquidity, and PD engines
"""

from typing import Optional
from .models import Zone, OrderBlock, FVG, Event, Bar, Snapshot
from .config import EngineConfig, BULLISH, BEARISH


class ZoneManager:
    """
    Unified zone lifecycle manager.

    Zones are created by sub-engines (OB Engine, FVG Engine, etc.)
    but ALL lifecycle transitions go through ZoneManager.
    """

    def __init__(self, config: EngineConfig):
        self.cfg = config
        self.zones: dict[str, Zone] = {}
        self.zone_order: list[str] = []
        self._touched_zones: set[str] = set()  # zones that have had their first touch

        self.max_per_type = {
            "order_block": config.order_block.max_active,
            "fvg": 20,
            "liquidity": config.liquidity.max_active_zones,
            "pd_range": 1,
        }

    def add_zone(self, zone: Zone) -> None:
        """Add a new zone. Enforce max-active limits."""
        zone_type = zone.zone_type
        max_active = self.max_per_type.get(zone_type, 20)

        # Count active of this type
        active_of_type = sum(
            1 for z in self.zones.values()
            if z.zone_type == zone_type and z.status == "active"
        )

        # Remove oldest active if at limit
        if active_of_type >= max_active:
            for zid in self.zone_order:
                z = self.zones.get(zid)
                if z and z.zone_type == zone_type and z.status == "active":
                    z.status = "expired"
                    break

        self.zones[zone.id] = zone
        if zone.id not in self.zone_order:
            self.zone_order.append(zone.id)

    def remove_zone(self, zone_id: str) -> Optional[Zone]:
        zone = self.zones.pop(zone_id, None)
        if zone_id in self.zone_order:
            self.zone_order.remove(zone_id)
        return zone

    def get_active_zones(self, zone_type: str = "") -> list[Zone]:
        """Get all active zones, optionally filtered by type."""
        result = []
        for zid in self.zone_order:
            z = self.zones.get(zid)
            if z and z.status == "active":
                if not zone_type or z.zone_type == zone_type:
                    result.append(z)
        return result

    def count_active(self, zone_type: str = "") -> int:
        return len(self.get_active_zones(zone_type))

    def check_touches(self, bar: Bar, bar_index: int) -> list[Event]:
        """Check if any active zone is touched by current bar.
        Only fires TOUCHED once per zone (on first touch).
        """
        events: list[Event] = []
        for zid in self.zone_order:
            z = self.zones.get(zid)
            if not z or z.status != "active":
                continue

            # Check if bar overlaps the zone (first touch only)
            if zid not in self._touched_zones and bar.high >= z.bottom and bar.low <= z.top:
                self._touched_zones.add(zid)
                events.append(Event(
                    timestamp=bar.timestamp, bar_index=bar_index,
                    symbol=bar.symbol, timeframe=bar.timeframe,
                    event_type=f"{z.zone_type.upper()}_TOUCHED",
                    direction=z.direction,
                    price=bar.close, level_top=z.top, level_bottom=z.bottom,
                    source_object_id=z.id, object_id=z.id,
                    status="active", confirmed=True,
                ))

        return events

    def clean_expired(self, current_bar: int, max_age: int = 500) -> list[Event]:
        """Remove zones that have exceeded their max age."""
        events: list[Event] = []
        to_remove: list[str] = []
        for zid in self.zone_order:
            z = self.zones.get(zid)
            if not z:
                continue
            # Zone age check would go here if we track creation bar
        for zid in to_remove:
            self.remove_zone(zid)
        return events

    def update_from_ob(self, ob: OrderBlock) -> Zone:
        """Create/update a zone from an OrderBlock."""
        z = Zone(
            id=f"zone_{ob.id}",
            zone_type="order_block",
            direction=ob.direction,
            top=ob.top,
            bottom=ob.bottom,
            created_at=ob.created_at,
            status=ob.status,
            source_object_id=ob.id,
            reference=ob,
        )
        self.add_zone(z)
        return z

    def update_from_lifecycle_event(self, event: Event) -> None:
        """Keep zones in sync when the backing OB lifecycle ends."""
        if not event.object_id:
            return
        if event.event_type not in {"OB_MITIGATED", "OB_INVALIDATED", "OB_EXPIRED"}:
            return
        zone_id = f"zone_{event.object_id}"
        zone = self.zones.get(zone_id)
        if zone:
            zone.status = event.status or event.event_type.removeprefix("OB_").lower()

    def update_from_fvg(self, fvg: FVG) -> Zone:
        z = Zone(
            id=f"zone_{fvg.id}",
            zone_type="fvg",
            direction=fvg.direction,
            top=fvg.top,
            bottom=fvg.bottom,
            created_at=fvg.created_at,
            status=fvg.status,
            source_object_id=fvg.id,
            reference=fvg,
        )
        self.add_zone(z)
        return z

    def update_snapshot(self, snapshot: Snapshot) -> None:
        """Fill zone-related counts in snapshot."""
        snapshot.active_ob_count = self.count_active("order_block")
        snapshot.active_fvg_count = self.count_active("fvg")
        snapshot.active_liquidity_count = self.count_active("liquidity")
