"""Group-block feasibility + pricing rules engine (deterministic).

Inputs are a group inquiry and the property catalog; output is a fully structured decision
that the proposal writer (LLM) may describe but never alter. Every number a client or a
sales manager sees comes from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from ..catalog import Catalog, Property

D = Decimal
URGENT_RE = re.compile(r"this week|urgent|asap|as soon as possible|time[- ]sensitive|deadline|by (mon|tues|wednes|thurs|fri)day", re.I)
YOUTH_RE = re.compile(r"\byouth|student|school|marching band|\bband\b|minors?\b|ages? 1[0-7]|chaperone", re.I)
ROOM_TYPES = ["Standard King", "Standard Double", "Deluxe King", "Suite", "Accessible King"]


def money(x: Decimal) -> Decimal:
    return x.quantize(D("0.01"), ROUND_HALF_UP)


def rate_at(base: Decimal, discount_pct: Decimal) -> Decimal:
    return money(base * (D(1) - discount_pct / D(100)))


def stay_nights(arrival: date, departure: date) -> list[date]:
    return [arrival + timedelta(days=i) for i in range((departure - arrival).days)]


@dataclass
class GroupRequest:
    inquiry_id: str
    company: str | None
    contact_name: str | None
    event_type: str | None
    property_code: str | None
    alternate_ok: bool | None
    arrival: date | None
    departure: date | None
    rooms: int | None
    rooms_raw: str | None
    rooms_approximate: bool
    room_type: str | None
    discount_pct: Decimal | None
    budget: Decimal | None
    meeting_needed: bool | None
    meeting_capacity: int | None
    special_requests: str | None
    date_received: date | None
    has_phone: bool

    @classmethod
    def from_row(cls, r: dict) -> "GroupRequest":
        def dec(v):
            return D(str(v)) if v is not None else None
        return cls(
            inquiry_id=r["inquiry_id"], company=r.get("company_name"), contact_name=r.get("contact_name"),
            event_type=r.get("event_type"), property_code=r.get("preferred_property_code"),
            alternate_ok=r.get("alternate_property_ok"), arrival=r.get("arrival_date"),
            departure=r.get("departure_date"), rooms=r.get("rooms_requested"),
            rooms_raw=r.get("rooms_requested_raw"), rooms_approximate=bool(r.get("rooms_approximate")),
            room_type=r.get("room_type_preference"), discount_pct=dec(r.get("requested_discount_pct")),
            budget=dec(r.get("stated_budget_per_night")), meeting_needed=r.get("meeting_space_needed"),
            meeting_capacity=r.get("meeting_capacity_needed"), special_requests=r.get("special_requests"),
            date_received=r.get("date_received"), has_phone=bool(r.get("has_phone")))

    @property
    def is_youth(self) -> bool:
        return bool(YOUTH_RE.search(f"{self.event_type or ''} {self.special_requests or ''}"))

    @property
    def nights(self) -> int | None:
        return (self.departure - self.arrival).days if self.arrival and self.departure else None


def missing_information(req: GroupRequest, prop: Property | None, today: date) -> tuple[list[dict], list[dict]]:
    """Returns (blocking, optional) clarification items."""
    blocking, optional = [], []
    if not prop:
        blocking.append({"field": "property", "question": "Which Solstice city or property would you like?"})
    if not (req.arrival and req.departure):
        blocking.append({"field": "dates", "question": "Your confirmed arrival and departure dates."})
    elif req.departure <= req.arrival:
        blocking.append({"field": "dates", "question": "Departure needs to be after arrival. Could you confirm the dates?"})
    elif req.arrival <= today:
        blocking.append({"field": "dates", "question": "The requested dates have already passed. What are your new dates?"})
    if req.rooms is None:
        blocking.append({"field": "rooms", "question": "How many rooms you need per night."})
    elif req.rooms_approximate:
        blocking.append({"field": "rooms", "question": f"An exact room count (the request said \"{req.rooms_raw}\")."})
    if not req.room_type:
        blocking.append({"field": "room_type",
                         "question": "Your preferred room mix (Standard King, Standard Double, Deluxe King, Suite)."})
    elif req.room_type not in ROOM_TYPES:
        blocking.append({"field": "room_type", "question": f"Which of our room types matches \"{req.room_type}\"?"})
    if req.meeting_needed and not req.meeting_capacity:
        blocking.append({"field": "meeting_capacity", "question": "How many people the meeting space should seat, and the setup you need."})
    if req.budget is None:
        optional.append({"field": "budget", "question": "Your target nightly rate, so we can tailor options."})
    if req.discount_pct is None:
        optional.append({"field": "discount", "question": "Any corporate or group rate agreement we should honor."})
    if not req.has_phone:
        optional.append({"field": "phone", "question": "The best phone number to reach you."})
    return blocking, optional


def effective_ceiling(prop: Property, nights: list[date]) -> tuple[Decimal, str, list[dict]]:
    ceiling, reason, applied = prop.max_discount_pct, f"{prop.name} auto-approve ceiling", []
    for rule in prop.rules_of("seasonal_discount_cap"):
        p = rule["params"]
        hit = [n for n in nights if n.month in p["months"] and n.weekday() in p["weekdays"]]
        if hit and D(str(p["cap_pct"])) < ceiling:
            ceiling = D(str(p["cap_pct"]))
            reason = f"{p['label']} cap ({len(hit)} of {len(nights)} nights affected)"
            applied.append({"rule_id": rule["rule_id"], "description": rule["description"], "nights_affected": len(hit)})
    return ceiling, reason, applied


class _Checks:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, cid: str, label: str, ok: bool | None, detail: str, severity: str = "review",
            ref: str | None = None) -> None:
        status = "pass" if ok is True else ("info" if ok is None else ("warn" if severity in ("advisory", "condition") else "fail"))
        self.items.append({"id": cid, "label": label, "status": status, "severity": severity, "detail": detail, "ref": ref})

    def flags(self) -> list[dict]:
        return [c for c in self.items if c["status"] == "fail"]

    def by_severity(self, sev: str) -> list[dict]:
        return [c for c in self.items if c["status"] in ("warn", "fail") and c["severity"] == sev]


async def evaluate(req: GroupRequest, catalog: Catalog, today: date, *, budget_match: bool = True) -> dict:
    prop = catalog.get(req.property_code)
    blocking, optional = missing_information(req, prop, today)
    priority, priority_reason = "normal", None
    if req.special_requests and URGENT_RE.search(req.special_requests):
        priority, priority_reason = "urgent", "Client stated a time-sensitive deadline."
    elif req.arrival and (req.arrival - today).days <= 30:
        priority, priority_reason = "urgent", f"Arrival is {(req.arrival - today).days} days out."

    decision: dict = {
        "inquiry_id": req.inquiry_id, "company": req.company, "contact_name": req.contact_name,
        "event_type": req.event_type, "property": prop.public() if prop else None,
        "requirements": {
            "arrival": req.arrival.isoformat() if req.arrival else None,
            "departure": req.departure.isoformat() if req.departure else None, "nights": req.nights,
            "rooms": req.rooms, "room_type": req.room_type,
            "requested_discount_pct": float(req.discount_pct) if req.discount_pct is not None else None,
            "budget_per_night": float(req.budget) if req.budget is not None else None,
            "meeting_capacity": req.meeting_capacity if req.meeting_needed else None,
            "alternate_property_ok": req.alternate_ok, "special_requests": req.special_requests,
        },
        "missing": blocking, "optional_questions": optional, "priority": priority,
        "priority_reason": priority_reason, "checks": [], "pricing": None, "flags": [],
        "conditions": [], "advisories": [], "alternatives": [],
    }
    if blocking:
        decision["status"] = "needs_clarification"
        return decision

    assert prop and req.arrival and req.departure and req.rooms and req.room_type
    nights = stay_nights(req.arrival, req.departure)
    checks = _Checks()
    discount = req.discount_pct or D(0)

    # 1. Blackouts (hard)
    bo = prop.blackout_overlap(req.arrival, req.departure)
    checks.add("blackout", "Dates clear of blackouts", bo is None,
               f"Overlaps blackout {bo[0]} to {bo[1]}: {bo[2]}." if bo else "No blackout dates in the stay.",
               "hard", "properties.blackout_dates")

    # 2. Inventory for every night (hard)
    avail = await catalog.availability(prop.code, req.arrival, req.departure)
    rt_avail = avail.get(req.room_type, {}).get("available", 0)
    checks.add("inventory", f"{req.rooms} × {req.room_type} available every night", rt_avail >= req.rooms,
               f"Lowest availability across the stay: {rt_avail} {req.room_type} rooms.", "hard", "inventory_nights")

    # 3. Meeting capacity (hard at this property)
    if req.meeting_needed and req.meeting_capacity:
        cap = prop.max_meeting_capacity or 0
        checks.add("meeting", f"Meeting space for {req.meeting_capacity}", req.meeting_capacity <= cap,
                   f"{prop.name} seats at most {cap}.", "hard", "properties.max_meeting_capacity")

    # 4. Block size vs auto-approve limit (review)
    checks.add("block_size", f"Block ≤ {prop.auto_max_rooms} rooms (auto-approve limit)",
               req.rooms <= prop.auto_max_rooms,
               f"{req.rooms} rooms requested; auto-approve limit is {prop.auto_max_rooms}.", "review",
               "properties.group_block_auto_approve_max_rooms")

    # 5. Property rules from notes
    for rule in prop.rules_of("route_over_rooms"):
        mx = rule["params"]["max_rooms"]
        checks.add("route_over", f"Block ≤ {mx} rooms at this property", req.rooms <= mx,
                   f"{rule['description']} {rule['params']['route_to']} is not in the provided property "
                   "directory, so Group Sales must place the overflow.", "review", f"property_rule:{rule['rule_id']}")
    for rule in prop.rules_of("lead_time"):
        p = rule["params"]
        lead = (req.arrival - today).days
        if req.rooms > p["min_rooms_exclusive"]:
            checks.add("lead_time", f"Lead time ≥ {p['min_days']} days for blocks over {p['min_rooms_exclusive']}",
                       lead >= p["min_days"], f"Arrival is {lead} days out.", "review", f"property_rule:{rule['rule_id']}")
    for rule in prop.rules_of("youth_insurance_required"):
        if req.is_youth:
            checks.add("youth_insurance", "Youth-group insurance certificate on file", False,
                       rule["description"] + " Required before the block can be confirmed.", "condition",
                       f"property_rule:{rule['rule_id']}")
    for rule in prop.rules_of("weekend_preference"):
        wk = [n for n in nights if n.weekday() in rule["params"]["weekdays"]]
        if wk:
            checks.add("weekend", "Weekday block preferred", False,
                       f"{len(wk)} weekend night(s). {rule['description']}", "advisory", f"property_rule:{rule['rule_id']}")
    for rule in prop.rules_of("seasonal_rate_advisory"):
        if any(n.month in rule["params"]["months"] for n in nights):
            checks.add("seasonal_rate", "Off-peak seasonal pricing may apply", None, rule["description"],
                       "advisory", f"property_rule:{rule['rule_id']}")
    for rule in prop.rules_of("selling_point"):
        checks.add("selling_point", "Property highlight", None, rule["description"], "advisory")

    # 6. Pricing
    base = prop.room_types.get(req.room_type).base_rate if req.room_type in prop.room_types else None
    ceiling, ceiling_reason, caps = effective_ceiling(prop, nights)
    pricing = None
    if base is None:
        checks.add("rate", f"Published rate for {req.room_type}", False,
                   "No valid base rate on file (quarantined by data validation). A human must price this block.",
                   "review", "data_quality")
    else:
        checks.add("discount", f"Discount ≤ {ceiling}% ({ceiling_reason})", discount <= ceiling,
                   f"Requested {discount}% against an effective ceiling of {ceiling}%.", "review",
                   "properties.max_discount_auto_approve_pct" + (" + seasonal rule" if caps else ""))
        options = []
        # A price is only "confirmable today" if nothing else about the request needs a human.
        other_blockers = [c for c in checks.items if c["status"] == "fail" and c["id"] != "discount"]

        def option(label: str, pct: Decimal, note: str) -> dict:
            r = rate_at(base, pct)
            return {"label": label, "discount_pct": float(pct), "rate": float(r),
                    "subtotal": float(money(r * req.rooms * len(nights))),
                    "auto_approvable": pct <= ceiling and not other_blockers,
                    "within_budget": (r <= req.budget) if req.budget else None,
                    "note": note}

        options.append(option("As requested", discount, "Client's requested discount."))
        if discount > ceiling:
            options.append(option("Confirmable today", ceiling,
                                  "Highest discount inside property authority. Can be confirmed without GM review."))
        if budget_match and req.budget and rate_at(base, discount) > req.budget:
            need = ((D(1) - req.budget / base) * D(100)).quantize(D(1), ROUND_CEILING)
            if discount < need <= ceiling:
                options.append(option("Budget match", need,
                                      f"Smallest whole-percent discount that meets the ${req.budget}/night budget."))
        req_rate = rate_at(base, discount)
        pricing = {
            "base_rate": float(base), "room_type": req.room_type, "rooms": req.rooms, "nights": len(nights),
            "room_nights": req.rooms * len(nights), "requested_discount_pct": float(discount),
            "effective_ceiling_pct": float(ceiling), "ceiling_reason": ceiling_reason, "seasonal_caps": caps,
            "group_rate": float(req_rate), "subtotal": float(money(req_rate * req.rooms * len(nights))),
            "budget_per_night": float(req.budget) if req.budget else None,
            "within_budget": (req_rate <= req.budget) if req.budget else None,
            "taxes": "plus applicable taxes and fees", "options": options,
        }
        if req.budget and req_rate > req.budget:
            checks.add("budget", "Rate within stated budget", False,
                       f"Requested-discount rate ${req_rate} is above the ${req.budget} budget.", "advisory")

    decision["checks"] = checks.items
    decision["pricing"] = pricing
    decision["flags"] = [c for c in checks.flags()]
    decision["conditions"] = checks.by_severity("condition")
    decision["advisories"] = [c for c in checks.items if c["severity"] == "advisory"]
    decision["status"] = "needs_review" if decision["flags"] else "auto_approved"
    return decision
