"""Shared domain services used by BOTH the LLM tools and the deterministic quick-action API.

One implementation per capability means the chat agent and the buttons can never disagree,
and the buttons keep working when the model is down.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from psycopg.types.json import Jsonb

from .catalog import Catalog
from .config import get_settings
from .db import Database, get_db
from .rules import escalation, rescue, stay

log = logging.getLogger(__name__)

_catalog: Catalog | None = None


async def catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog(get_db())
    return await _catalog.ensure()


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    return v


def clean(row: dict | None) -> dict | None:
    return None if row is None else {k: _jsonable(v) for k, v in row.items()}


class DomainError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Guest identity
# ---------------------------------------------------------------------------
async def verify_guest(reservation_id: str, last_name: str, db: Database | None = None) -> dict | None:
    db = db or get_db()
    row = await db.fetchrow("SELECT * FROM agent.verify_guest(%s, %s)", (reservation_id, last_name))
    return row


async def guest_profile(guest_id: str) -> dict:
    db = get_db()
    g = await db.fetchrow("SELECT * FROM agent.v_guests WHERE guest_id = %s", (guest_id,))
    res = await db.fetch("SELECT * FROM agent.v_reservations WHERE guest_id = %s ORDER BY check_in", (guest_id,))
    return {"guest": clean(g), "reservations": [clean(r) for r in res]}


def pick_reservation(reservations: list[dict], reservation_id: str | None, today: date) -> dict:
    """Choose which stay the guest means: explicit id → checked-in → next upcoming → latest."""
    if reservation_id:
        for r in reservations:
            if r["reservation_id"].upper() == reservation_id.strip().upper():
                return r
        raise DomainError("not_found", "That confirmation number isn't on this guest's profile.")
    if not reservations:
        raise DomainError("not_found", "No reservations found for this guest.")
    inhouse = [r for r in reservations if r["status"] == "Checked-in"]
    if inhouse:
        return inhouse[0]
    upcoming = sorted((r for r in reservations if r["status"] == "Confirmed" and str(r["check_in"]) >= today.isoformat()),
                      key=lambda r: str(r["check_in"]))
    if upcoming:
        return upcoming[0]
    return sorted(reservations, key=lambda r: str(r["check_out"]))[-1]


async def guest_reservation(guest_id: str, reservation_id: str | None) -> tuple[dict, dict]:
    prof = await guest_profile(guest_id)
    res = pick_reservation(prof["reservations"], reservation_id, get_settings().business_date)
    return prof, res


# ---------------------------------------------------------------------------
# Requests (late checkout / early check-in / upgrade / amenity)
# ---------------------------------------------------------------------------
AMENITY_CATALOG = {
    # What the provided data actually tells us about each kind of ask.
    "hypoallergenic bedding": ("free_request", "Logged for housekeeping at no charge."),
    "turndown": ("free_request", "A complimentary turndown note can be arranged."),
    "champagne": ("paid_addon", "Champagne and celebration amenities are paid add-ons priced by the property."),
    "rollaway": ("paid_addon", "Rollaway beds carry a nightly fee set by the property and are subject to the room's "
                               "fire-code maximum occupancy (Policy 9)."),
    "connecting rooms": ("inventory", "Connecting rooms are limited inventory. The desk confirms before promising them."),
    "ground floor": ("inventory", "Floor requests are noted but not guaranteed."),
    "high floor": ("inventory", "Floor requests are noted but not guaranteed."),
    "parking": ("not_in_data", "Parking prices vary by property and aren't in the data I can access (Policy 12). "
                               "The front desk will confirm the current rate."),
}


def classify_amenity(details: str) -> tuple[str, str]:
    d = (details or "").lower()
    for key, val in AMENITY_CATALOG.items():
        if key in d or key.split()[0] in d:
            return val
    return ("desk_review", "Request passed to the front desk to confirm what's possible.")


async def create_request(guest_id: str, reservation_id: str | None, kind: str, time_text: str | None,
                         details: str | None, session_id: str | None) -> dict:
    prof, res = await guest_reservation(guest_id, reservation_id)
    tier = prof["guest"]["loyalty_tier"]
    if res["status"] not in ("Confirmed", "Checked-in"):
        raise DomainError("not_active", f"Reservation {res['reservation_id']} is {res['status']}.")
    if kind == "late_checkout":
        decision = stay.late_checkout(tier, time_text)
    elif kind == "early_checkin":
        decision = stay.early_checkin(tier, time_text)
    elif kind == "upgrade":
        rt = (await catalog()).get(res["property_code"]).room_types.get(res["room_type"])
        decision = stay.upgrade_request(tier, rt.room_class if rt else 1)
    else:
        category, explanation = classify_amenity(details or "")
        decision = {"kind": "amenity", "status": "pending_desk", "category": category, "details": details,
                    "explanation": explanation, "policy_refs": [9] if "rollaway" in (details or "").lower() else []}
    if decision["status"] in ("not_needed", "not_available"):
        return {"reservation_id": res["reservation_id"], "property_name": res["property_name"], **decision}
    row = await get_db().fetchrow(
        """INSERT INTO ops.service_requests (kind, reservation_id, guest_id, property_code, details, status,
                                             decided_by, session_id, decided_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s, CASE WHEN %s = 'confirmed' THEN now() END) RETURNING request_id""",
        (kind, res["reservation_id"], guest_id, res["property_code"], Jsonb(decision),
         decision["status"], decision.get("decided_by"), session_id, decision["status"]))
    await log_event(session_id, "concierge", "request_created", res["property_code"],
                    meta={"kind": kind, "status": decision["status"]})
    return {"request_id": row["request_id"], "reservation_id": res["reservation_id"],
            "property_name": res["property_name"], **decision}


# ---------------------------------------------------------------------------
# Availability, holds, bookings
# ---------------------------------------------------------------------------
async def search_availability(where: str, check_in: date, check_out: date, room_type: str | None,
                              session_id: str | None) -> dict:
    cat = await catalog()
    prop = cat.resolve(where)
    if not prop:
        return {"found": False, "message": f"No Solstice property matches '{where}'.",
                "properties": [f"{p.name} ({p.city}, {p.state})" for p in cat.all()]}
    today = get_settings().business_date
    if check_in <= today or check_out <= check_in:
        return {"found": False, "message": "Dates must be in the future with check-out after check-in.",
                "today": today.isoformat()}
    await get_db().fetchrow("SELECT agent.expire_holds() AS n")
    avail = await cat.availability(prop.code, check_in, check_out)
    nights = (check_out - check_in).days
    options = [{"room_type": rt, "available": info["available"], "nightly_rate": float(info["base_rate"]),
                "total_before_tax": float(Decimal(info["base_rate"]) * nights)}
               for rt, info in avail.items()
               if info["available"] > 0 and info["base_rate"] and (not room_type or rt.lower() == room_type.lower())]
    result = {"found": bool(options), "property_code": prop.code, "property_name": prop.name,
              "city": prop.city, "check_in": check_in.isoformat(), "check_out": check_out.isoformat(),
              "nights": nights, "rate_plan": "Best Available Rate", "options": options,
              "cancellation": "Free cancellation up to 72 hours before arrival (Policy 2).", "policy_refs": [2]}
    if not options:
        result["alternatives"] = await rescue.stay_alternatives(cat, prop, check_in, check_out, room_type or None)
        await log_event(session_id, "concierge", "rescue_offered", prop.code, meta={"n": len(result["alternatives"])})
    await log_event(session_id, "concierge", "availability_shown", prop.code, meta={"options": len(options)})
    return result


async def place_stay_hold(property_code: str, room_type: str, check_in: date, check_out: date,
                          guest_id: str | None, session_id: str | None, idem: str | None = None) -> dict:
    cat = await catalog()
    prop = cat.get(property_code) or cat.resolve(property_code)
    if not prop:
        raise DomainError("not_found", "Unknown property.")
    rt = next((r for r in prop.room_types.values() if r.room_type.lower() == room_type.lower()), None)
    if not rt or rt.base_rate is None:
        raise DomainError("no_rate", f"No published rate for {room_type} at {prop.name}.")
    nights = (check_out - check_in).days
    total = rt.base_rate * nights
    s = get_settings()
    try:
        hold = await get_db().fetchrow(
            "SELECT * FROM agent.place_hold('stay', %s, %s, %s, %s, 1, %s, %s, %s, %s, NULL, %s, %s)",
            (prop.code, rt.room_type, check_in, check_out, s.stay_hold_ttl_minutes,
             idem or f"stay:{session_id}:{prop.code}:{rt.room_type}:{check_in}:{check_out}",
             guest_id, session_id, rt.base_rate,
             Jsonb({"nights": nights, "nightly_rate": float(rt.base_rate), "total_before_tax": float(total)})))
    except Exception as exc:  # noqa: BLE001
        if "insufficient_inventory" in str(exc):
            alts = await rescue.stay_alternatives(cat, prop, check_in, check_out, rt.room_type)
            raise DomainError("sold_out", json.dumps({"message": "That room just sold out.", "alternatives": alts}))
        raise
    await log_event(session_id, "concierge", "hold_created", prop.code, float(total), {"hold_id": str(hold["hold_id"])})
    return {"hold_id": str(hold["hold_id"]), "property_code": prop.code, "property_name": prop.name,
            "room_type": rt.room_type, "check_in": check_in.isoformat(), "check_out": check_out.isoformat(),
            "nights": nights, "nightly_rate": float(rt.base_rate), "total_before_tax": float(total),
            "rate_plan": "Best Available Rate", "expires_at": hold["expires_at"].isoformat(),
            "hold_minutes": s.stay_hold_ttl_minutes,
            "next_step": "Guest completes booking with the secure checkout button (card details never pass through chat)."}


# ---------------------------------------------------------------------------
# Escalation hand-off packet
# ---------------------------------------------------------------------------
async def escalate(*, category: str, guest_ask: str, summary: str, guest_id: str | None,
                   reservation_id: str | None, property_code: str | None, assessment: dict | None,
                   recommended_action: str | None, transcript: list[dict], session_id: str | None,
                   policy_refs: list[int] | None = None, route_override: str | None = None,
                   severity_override: str | None = None) -> dict:
    cat = await catalog()
    prop = cat.get(property_code)
    route = escalation.route_for(category, prop.general_manager if prop else None)
    severity = severity_override or route.severity
    route_to = route_override or route.route_to
    due = datetime.now() + escalation.SLA[severity]
    row = await get_db().fetchrow(
        """INSERT INTO ops.escalations (category, severity, route_to, property_code, guest_id, reservation_id,
               guest_ask, summary, agent_assessment, policy_refs, recommended_action, transcript, sla_due_at, session_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING case_id, sla_due_at""",
        (category, severity, route_to, property_code, guest_id, reservation_id, guest_ask, summary,
         Jsonb(assessment or {}), sorted(set((policy_refs or []) + list(route.policy_refs))), recommended_action,
         Jsonb(transcript[-30:]), due, session_id))
    await log_event(session_id, "concierge", "escalated", property_code, meta={"category": category, "case_id": row["case_id"]})
    expect = {"immediate": "within 15 minutes", "same_day": "today (within about 4 hours)",
              "standard": "within 24 hours"}[severity]
    return {"case_id": row["case_id"], "category": category, "severity": severity, "route_to": route_to,
            "expected_response": expect, "property_name": prop.name if prop else None,
            "guest_message": f"Case {row['case_id']} is with the {route_to.split(' (')[0]}. They have the full "
                             f"conversation, so you won't need to repeat yourself. Expect a response {expect}."}


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
async def log_event(session_id: str | None, channel: str, event: str, property_code: str | None = None,
                    value: float | None = None, meta: dict | None = None) -> None:
    try:
        await get_db().fetchrow(
            "INSERT INTO ops.funnel_events (session_id, channel, event, property_code, value_usd, meta) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING event_id",
            (session_id, channel, event, property_code, value, Jsonb(meta or {})))
    except Exception as exc:  # noqa: BLE001 — telemetry must never break a guest flow
        log.warning("funnel event dropped: %s", exc)


async def log_guardrail(session_id: str | None, kind: str, detail: dict) -> None:
    try:
        await get_db().fetchrow("INSERT INTO ops.guardrail_events (session_id, kind, detail) VALUES (%s,%s,%s) "
                                "RETURNING event_id", (session_id, kind, Jsonb(detail)))
    except Exception as exc:  # noqa: BLE001
        log.warning("guardrail event dropped: %s", exc)
