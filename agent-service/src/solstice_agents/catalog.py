"""Read-mostly reference data (properties, room types, blackouts, rules), cached in memory.

Loaded through the agent DB role, so it only ever sees the masked `agent.*` surface.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .db import Database


@dataclass(frozen=True)
class RoomType:
    room_type: str
    room_class: int
    room_count: int
    base_rate: Decimal | None


@dataclass
class Property:
    code: str
    name: str
    city: str
    state: str
    market_type: str
    total_rooms: int
    meeting_space_sqft: int | None
    max_meeting_capacity: int | None
    auto_max_rooms: int
    max_discount_pct: Decimal
    general_manager: str | None
    notes: str
    lat: float | None
    lon: float | None
    room_types: dict[str, RoomType] = field(default_factory=dict)
    blackouts: list[tuple[date, date, str]] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)

    def rules_of(self, rule_type: str) -> list[dict]:
        return [r for r in self.rules if r["rule_type"] == rule_type]

    def blackout_overlap(self, arrival: date, departure: date) -> tuple[date, date, str] | None:
        """Blackouts are inclusive date spans; a stay occupies nights [arrival, departure)."""
        last_night = departure - timedelta(days=1)
        for start, end, reason in self.blackouts:
            if arrival <= end and last_night >= start:
                return start, end, reason
        return None

    def miles_to(self, other: "Property") -> float | None:
        if None in (self.lat, self.lon, other.lat, other.lon):
            return None
        r = 3958.8
        p1, p2 = math.radians(self.lat), math.radians(other.lat)
        dp, dl = p2 - p1, math.radians(other.lon - self.lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return round(2 * r * math.asin(math.sqrt(a)))

    def public(self) -> dict:
        return {
            "property_code": self.code, "property_name": self.name, "city": self.city, "state": self.state,
            "market_type": self.market_type, "total_rooms": self.total_rooms,
            "max_meeting_capacity": self.max_meeting_capacity, "meeting_space_sqft": self.meeting_space_sqft,
            "room_types": [
                {"room_type": rt.room_type, "base_rate": float(rt.base_rate) if rt.base_rate else None}
                for rt in sorted(self.room_types.values(), key=lambda x: (x.room_class, x.room_type))
            ],
        }


class Catalog:
    TTL_S = 300

    def __init__(self, db: Database):
        self.db = db
        self._props: dict[str, Property] = {}
        self._loaded = 0.0

    async def refresh(self) -> None:
        props: dict[str, Property] = {}
        for r in await self.db.fetch("SELECT * FROM agent.v_properties ORDER BY property_code"):
            props[r["property_code"]] = Property(
                code=r["property_code"], name=r["property_name"], city=r["city"], state=r["state"],
                market_type=r["market_type"], total_rooms=r["total_rooms"],
                meeting_space_sqft=r["meeting_space_sqft"], max_meeting_capacity=r["max_meeting_capacity"],
                auto_max_rooms=r["group_auto_approve_max_rooms"],
                max_discount_pct=Decimal(r["max_discount_auto_approve_pct"]),
                general_manager=r["general_manager"], notes=r["notes"] or "",
                lat=r["latitude"], lon=r["longitude"])
        for r in await self.db.fetch("SELECT * FROM agent.v_room_types"):
            props[r["property_code"]].room_types[r["room_type"]] = RoomType(
                r["room_type"], r["room_class"], r["room_count"],
                Decimal(r["base_rate"]) if r["base_rate"] is not None else None)
        for r in await self.db.fetch("SELECT * FROM agent.v_blackouts ORDER BY start_date"):
            props[r["property_code"]].blackouts.append((r["start_date"], r["end_date"], r["reason"]))
        for r in await self.db.fetch("SELECT * FROM agent.v_property_rules ORDER BY rule_id"):
            props[r["property_code"]].rules.append(dict(r))
        self._props = props
        self._loaded = time.monotonic()

    async def ensure(self) -> "Catalog":
        if not self._props or time.monotonic() - self._loaded > self.TTL_S:
            await self.refresh()
        return self

    def get(self, code: str | None) -> Property | None:
        return self._props.get((code or "").upper())

    def all(self) -> list[Property]:
        return list(self._props.values())

    def resolve(self, text: str | None) -> Property | None:
        """Match a property code, property name, or city mentioned by a guest."""
        if not text:
            return None
        t = text.strip().lower()
        for p in self._props.values():
            if t in (p.code.lower(), p.city.lower(), p.name.lower()) or p.city.lower() in t or t in p.name.lower():
                return p
        return None

    async def availability(self, code: str, arrival: date, departure: date) -> dict[str, dict]:
        rows = await self.db.fetch("SELECT * FROM agent.availability(%s, %s, %s)", (code, arrival, departure))
        nights = (departure - arrival).days
        out = {}
        for r in rows:
            # A missing calendar night means we cannot vouch for availability: treat as 0.
            avail = r["min_available"] if r["nights"] == nights else 0
            out[r["room_type"]] = {"available": avail, "base_rate": r["base_rate"], "room_class": r["room_class"]}
        return out
