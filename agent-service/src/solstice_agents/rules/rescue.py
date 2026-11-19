"""Booking Rescue — net-new skill.

The supplied data describes when to say "no" (blackouts, limits, ceilings, capacity) but not
what to offer instead. Every "no" is a lost reservation unless someone builds the next-best
"yes" while the client is still engaged. This engine does that, deterministically:

  * shifted dates at the same property (same length, same weekday pattern)
  * nearby sister properties that satisfy every hard constraint, ranked by distance
  * split / partial blocks that stay inside auto-approve authority
  * off-site venue pairing when only the meeting room is the blocker

It's used by the group workflow and by the concierge's availability search.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ..catalog import Catalog, Property
from .group import GroupRequest, effective_ceiling, money, rate_at, stay_nights

SHIFTS = (7, -7, 14, -14, 21, -21, 28)


async def _fits(catalog: Catalog, prop: Property, arrival: date, departure: date, room_type: str,
                rooms: int, meeting: int | None) -> tuple[bool, str]:
    if prop.blackout_overlap(arrival, departure):
        return False, "blackout"
    if meeting and (prop.max_meeting_capacity or 0) < meeting:
        return False, "meeting capacity"
    rt = prop.room_types.get(room_type)
    if not rt or rt.base_rate is None:
        return False, "no published rate"
    avail = (await catalog.availability(prop.code, arrival, departure)).get(room_type, {}).get("available", 0)
    if avail < rooms:
        return False, f"only {avail} available"
    return True, "ok"


def _priced(prop: Property, arrival: date, departure: date, room_type: str, rooms: int,
            requested: Decimal) -> dict:
    nights = stay_nights(arrival, departure)
    ceiling, reason, _ = effective_ceiling(prop, nights)
    pct = min(requested, ceiling)
    rate = rate_at(prop.room_types[room_type].base_rate, pct)
    # Approvability is judged on what we OFFER (pct, already capped at the ceiling), not on what was asked.
    return {"discount_pct": float(pct), "rate": float(rate), "subtotal": float(money(rate * rooms * len(nights))),
            "effective_ceiling_pct": float(ceiling),
            "auto_approvable": rooms <= prop.auto_max_rooms and pct <= ceiling
                               and not any(rooms > r["params"]["max_rooms"] for r in prop.rules_of("route_over_rooms")),
            "discount_capped": requested > ceiling}


async def group_alternatives(req: GroupRequest, decision: dict, catalog: Catalog, today: date,
                             limit: int = 4) -> list[dict]:
    prop = catalog.get(req.property_code)
    if not prop or decision["status"] != "needs_review":
        return []
    flag_ids = {f["id"] for f in decision["flags"]}
    requested = req.discount_pct or Decimal(0)
    meeting = req.meeting_capacity if req.meeting_needed else None
    out: list[dict] = []

    # 1) Shifted dates at the preferred property — when the dates are the problem.
    if flag_ids & {"blackout", "inventory", "lead_time"}:
        n = req.nights
        for shift in SHIFTS:
            a = req.arrival + timedelta(days=shift)
            d = a + timedelta(days=n)
            if a <= today + timedelta(days=14 if "lead_time" in flag_ids else 1):
                continue
            ok, _ = await _fits(catalog, prop, a, d, req.room_type, req.rooms, meeting)
            if ok:
                out.append({"kind": "dates", "label": f"Same property, {abs(shift)} days {'later' if shift > 0 else 'earlier'}",
                            "property_code": prop.code, "property_name": prop.name, "arrival": a.isoformat(),
                            "departure": d.isoformat(), "room_type": req.room_type, "rooms": req.rooms,
                            **_priced(prop, a, d, req.room_type, req.rooms, requested)})
                if sum(1 for o in out if o["kind"] == "dates") >= 2:
                    break

    # 2) Split / partial block — when only the size is over authority.
    size_flags = flag_ids & {"block_size", "route_over"}
    if size_flags and not flag_ids & {"blackout", "meeting", "inventory"}:
        cap = prop.auto_max_rooms
        for r in prop.rules_of("route_over_rooms"):
            cap = min(cap, r["params"]["max_rooms"])
        rest = req.rooms - cap
        route_to = next((r["params"]["route_to"] for r in prop.rules_of("route_over_rooms")), None)
        out.append({"kind": "split", "label": f"Confirm {cap} rooms now; {rest} need {'routing to the ' + route_to if route_to else 'GM approval or a second property'}",
                    "property_code": prop.code, "property_name": prop.name, "arrival": req.arrival.isoformat(),
                    "departure": req.departure.isoformat(), "room_type": req.room_type, "rooms": cap,
                    "overflow_rooms": rest, "overflow_to": route_to,
                    **_priced(prop, req.arrival, req.departure, req.room_type, cap, requested)})

    # 3) Nearby sister properties — when the property itself can't host it as asked.
    if flag_ids & {"blackout", "meeting", "inventory", "block_size", "route_over"}:
        ranked = sorted((p for p in catalog.all() if p.code != prop.code),
                        key=lambda p: prop.miles_to(p) or 99999)
        props_found = 0
        for p in ranked:
            ok, _ = await _fits(catalog, p, req.arrival, req.departure, req.room_type, req.rooms, meeting)
            if not ok:
                continue
            priced = _priced(p, req.arrival, req.departure, req.room_type, req.rooms, requested)
            out.append({"kind": "property", "label": f"{p.name} ({prop.miles_to(p)} mi away)",
                        "property_code": p.code, "property_name": p.name, "arrival": req.arrival.isoformat(),
                        "departure": req.departure.isoformat(), "room_type": req.room_type, "rooms": req.rooms,
                        "distance_miles": prop.miles_to(p),
                        "client_consent_needed": req.alternate_ok is False, **priced})
            props_found += 1
            if props_found >= 2:
                break

    # 4) Off-site venue — rooms fit, only the meeting room doesn't.
    if "meeting" in flag_ids and not flag_ids & {"blackout", "inventory"}:
        out.append({"kind": "venue", "label": f"Keep rooms at {prop.name}; pair with an off-site venue for "
                                              f"{req.meeting_capacity} people",
                    "property_code": prop.code, "property_name": prop.name, "arrival": req.arrival.isoformat(),
                    "departure": req.departure.isoformat(), "room_type": req.room_type, "rooms": req.rooms,
                    "venue_needed_capacity": req.meeting_capacity, "property_max_capacity": prop.max_meeting_capacity,
                    **_priced(prop, req.arrival, req.departure, req.room_type, req.rooms, requested)})

    # Auto-approvable options first: they can be confirmed while the client is still engaged.
    out.sort(key=lambda o: (not o.get("auto_approvable"), o["kind"] != "dates"))
    return out[:limit]


async def stay_alternatives(catalog: Catalog, prop: Property, arrival: date, departure: date,
                            room_type: str | None, rooms: int = 1) -> list[dict]:
    """For a sold-out individual stay: nearby dates first, then nearby properties."""
    n = (departure - arrival).days
    out: list[dict] = []
    for shift in (1, -1, 2, -2, 3, -3, 7):
        a = arrival + timedelta(days=shift)
        avail = await catalog.availability(prop.code, a, a + timedelta(days=n))
        for rt, info in avail.items():
            if (room_type is None or rt == room_type) and info["available"] >= rooms and info["base_rate"]:
                out.append({"kind": "dates", "property_code": prop.code, "property_name": prop.name,
                            "check_in": a.isoformat(), "check_out": (a + timedelta(days=n)).isoformat(),
                            "room_type": rt, "nightly_rate": float(info["base_rate"])})
                break
        if len(out) >= 2:
            break
    for p in sorted((p for p in catalog.all() if p.code != prop.code), key=lambda p: prop.miles_to(p) or 99999)[:3]:
        avail = await catalog.availability(p.code, arrival, departure)
        for rt, info in avail.items():
            if (room_type is None or rt == room_type) and info["available"] >= rooms and info["base_rate"]:
                out.append({"kind": "property", "property_code": p.code, "property_name": p.name,
                            "check_in": arrival.isoformat(), "check_out": departure.isoformat(), "room_type": rt,
                            "nightly_rate": float(info["base_rate"]), "distance_miles": prop.miles_to(p)})
                break
    return out[:4]
