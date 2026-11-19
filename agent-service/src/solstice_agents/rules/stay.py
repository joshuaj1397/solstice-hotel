"""Deterministic guest-stay policy decisions (Policies 1–7, 15).

Every function returns a plain dict that includes `policy_refs`, so any answer the
agent gives can be traced to a numbered policy section.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

STANDARD_CHECKIN = time(15, 0)
STANDARD_CHECKOUT = time(11, 0)
FREE_CANCEL_HOURS = 72
SERVICE_RECOVERY_HOURS = 72
DESK_COMP_LIMIT = Decimal("50")

TIER_BENEFITS = {
    "None": {"summary": "Not enrolled in Solstice loyalty.", "late_checkout": None, "upgrade": None},
    "Silver": {"summary": "Earns points on every stay; no automatic perk beyond points.",
               "late_checkout": None, "upgrade": None},
    "Gold": {"summary": "Complimentary room upgrade at check-in when available; late check-out to 1:00 PM "
                        "subject to availability.",
             "late_checkout": {"time": "1:00 PM", "guaranteed": False},
             "upgrade": {"guaranteed": False, "detail": "Complimentary upgrade at check-in when one is available."}},
    "Platinum": {"summary": "Guaranteed upgrade to the next room class (based on same-day inventory) and "
                            "guaranteed late check-out until 2:00 PM — no blackout dates.",
                 "late_checkout": {"time": "2:00 PM", "guaranteed": True},
                 "upgrade": {"guaranteed": True,
                             "detail": "Guaranteed upgrade to the next room class, based on same-day inventory."}},
}

ROOM_CLASS_LADDER = {1: "Deluxe King", 2: "Suite", 3: None}


def as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def parse_time(text: str | None) -> time | None:
    """'1pm', '1:30 PM', '13:00', 'noon' → time."""
    if not text:
        return None
    t = text.strip().lower().replace(".", "")
    if t in ("noon", "midday"):
        return time(12, 0)
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", t)
    if not m:
        return None
    h, mnt, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if ap is None and 1 <= h <= 6:   # "late checkout at 2" means 2 PM
        h += 12
    return time(h, mnt) if 0 <= h < 24 and 0 <= mnt < 60 else None


def fmt_time(t: time) -> str:
    return datetime.combine(date.today(), t).strftime("%I:%M %p").lstrip("0")


def loyalty_benefits(tier: str) -> dict:
    return {"tier": tier, **TIER_BENEFITS.get(tier, TIER_BENEFITS["None"]), "policy_refs": [6]}


def late_checkout(tier: str, requested: str | None) -> dict:
    req = parse_time(requested) or (time(14, 0) if tier == "Platinum" else time(13, 0))
    out = {"kind": "late_checkout", "requested_time": fmt_time(req), "tier": tier, "policy_refs": [1, 6]}
    if req <= STANDARD_CHECKOUT:
        return out | {"status": "not_needed", "granted_time": fmt_time(STANDARD_CHECKOUT),
                      "explanation": "Standard check-out is 11:00 AM, so no late check-out is needed."}
    if tier == "Platinum":
        if req <= time(14, 0):
            return out | {"status": "confirmed", "granted_time": fmt_time(req),
                          "decided_by": "policy:platinum_guaranteed_late_checkout",
                          "explanation": "Platinum members are guaranteed late check-out until 2:00 PM."}
        return out | {"status": "pending_desk", "granted_time": "2:00 PM",
                      "decided_by": "policy:platinum_guaranteed_late_checkout",
                      "explanation": "2:00 PM is guaranteed for Platinum. Anything later is up to the front desk "
                                     "on the day, so 2:00 PM is confirmed and the later time is sent as a request."}
    if tier == "Gold" and req <= time(13, 0):
        return out | {"status": "pending_desk", "granted_time": None,
                      "explanation": "Gold members can have late check-out to 1:00 PM, subject to same-day "
                                     "availability. The front desk confirms on the day."}
    return out | {"status": "pending_desk", "granted_time": None,
                  "explanation": "Late check-out depends on same-day availability and is at the front desk's "
                                 "discretion. The request has been logged for the desk to confirm."}


def early_checkin(tier: str, requested: str | None) -> dict:
    req = parse_time(requested)
    return {"kind": "early_checkin", "requested_time": fmt_time(req) if req else "as early as possible",
            "tier": tier, "status": "pending_desk", "granted_time": None, "policy_refs": [1],
            "explanation": "Standard check-in is 3:00 PM. Early check-in depends on same-day room availability "
                           "and is never guaranteed, so the request has been logged for the front desk."}


def upgrade_request(tier: str, room_class: int) -> dict:
    nxt = ROOM_CLASS_LADDER.get(room_class)
    base = {"kind": "upgrade", "tier": tier, "next_room_class": nxt, "policy_refs": [6]}
    if nxt is None:
        return base | {"status": "not_available", "explanation": "You are already booked in our top room class."}
    if tier == "Platinum":
        return base | {"status": "pending_desk",
                       "explanation": f"Platinum guarantees an upgrade to the next room class ({nxt}), assigned "
                                      "against same-day inventory, so the front desk confirms the room at check-in."}
    if tier == "Gold":
        return base | {"status": "pending_desk",
                       "explanation": "Gold members receive a complimentary upgrade at check-in when one is "
                                      "available. The request has been noted."}
    return base | {"status": "pending_desk",
                   "explanation": "Upgrades for this rate are subject to availability at check-in. The request "
                                  "has been noted for the front desk."}


def cancellation_quote(res: dict, now: datetime) -> dict:
    """Policies 2–4. The free-cancellation cutoff is 72 hours before the arrival *date* (00:00).
    That reading matches the data: R55005 was cancelled 2026-06-04 for a 2026-06-06 arrival, which
    the front-desk note calls "36 hours after the 72-hour cutoff"."""
    plan = res["rate_plan"]
    rate = Decimal(res["nightly_rate"])
    nights = int(res["total_nights"])
    base = {"reservation_id": res["reservation_id"], "rate_plan": plan, "status": res["status"],
            "nightly_rate": float(rate), "nights": nights}
    if res["status"] != "Confirmed":
        return base | {"cancellable": False, "policy_refs": [2],
                       "explanation": f"This reservation is {res['status']}, so it can't be cancelled online."}
    cutoff = datetime.combine(as_date(res["check_in"]), time(0, 0)) - timedelta(hours=FREE_CANCEL_HOURS)
    if plan in ("Best Available Rate", "Corporate Negotiated"):
        free = now <= cutoff
        return base | {
            "cancellable": True, "free_cancellation": free, "free_cancel_deadline": cutoff.isoformat(),
            "penalty": None if free else {"nights": 1, "amount": float(rate), "plus_tax": True},
            "policy_refs": [2],
            "explanation": (f"Free cancellation until {cutoff:%b %d, %Y %I:%M %p} (72 hours before arrival)."
                            if free else
                            f"Inside the 72-hour window: cancelling forfeits one night's room (${rate:,.2f}) plus tax."),
        }
    if plan == "Advance Purchase":
        return base | {"cancellable": True, "free_cancellation": False,
                       "penalty": {"nights": nights, "amount": float(rate * nights), "plus_tax": True,
                                   "non_refundable": True},
                       "policy_refs": [3],
                       "explanation": "Advance Purchase rates are non-refundable and can't be changed, even for "
                                      "weather, flight problems or illness. Travel insurance, if purchased, is the "
                                      "only recourse."}
    # Loyalty Redemption (and anything else) is not covered by the written policy: don't guess.
    return base | {"cancellable": False, "free_cancellation": None, "penalty": None, "policy_refs": [2, 15],
                   "requires_human": True,
                   "explanation": f"The written policy doesn't cover cancelling a {plan} booking, so a team "
                                  "member needs to confirm how points or charges are handled."}


def service_recovery(res: dict, now: datetime, *, issue_type: str, reported_during_stay: bool,
                     amount_usd: float | None, prior_comps_usd: float = 0.0) -> dict:
    """Policies 5, 7, 15. Decides eligibility and *who* may approve; the agent itself never
    grants money. Returns a recommended action so the human closes it in one step."""
    checkout_dt = datetime.combine(as_date(res["check_out"]), STANDARD_CHECKOUT)
    window_end = checkout_dt + timedelta(hours=SERVICE_RECOVERY_HOURS)
    status = res["status"]
    total = Decimal(str(amount_usd or 0)) + Decimal(str(prior_comps_usd or 0))
    out: dict = {"reservation_id": res["reservation_id"], "issue_type": issue_type, "stay_status": status,
                 "reported_during_stay": reported_during_stay, "amount_usd": amount_usd,
                 "service_recovery_window_ends": window_end.isoformat(), "policy_refs": [5, 7, 15]}

    if issue_type == "charge_dispute":
        return out | {"eligible": None, "route_to": "Manager on Duty / AGM", "severity": "same_day",
                      "agent_may_resolve": False,
                      "assessment": "Folio disputes are never adjusted by the agent or the front desk directly.",
                      "recommended_action": "AGM reviews the folio line and the guest's account, then decides."}

    if status == "Checked-in":
        route = "Front Desk" if total <= DESK_COMP_LIMIT else "Manager on Duty / AGM"
        return out | {"eligible": True, "route_to": route, "severity": "same_day", "agent_may_resolve": False,
                      "assessment": "The guest is still in house, so the issue can be fixed during the stay. "
                                    f"Comps up to ${DESK_COMP_LIMIT} per stay are within front-desk authority.",
                      "recommended_action": "Fix the issue now and offer service recovery within authority."}

    in_window = now <= window_end
    if in_window or reported_during_stay:
        needs_mgr = total > DESK_COMP_LIMIT or issue_type == "comp_night"
        return out | {
            "eligible": True, "agent_may_resolve": False,
            "route_to": "Manager on Duty / AGM" if needs_mgr else "Front Desk",
            "severity": "same_day",
            "assessment": ("Reported during the stay, so the 72-hour window counts from check-out regardless of "
                           "when the guest followed up." if reported_during_stay and not in_window else
                           "Reported within 72 hours of check-out, so it qualifies for a refund, credit or comp night."),
            "recommended_action": ("Requires AGM/GM sign-off (over $50 or a comp night)." if needs_mgr
                                   else "Front desk may resolve up to $50 per stay."),
        }
    hours_late = int((now - window_end).total_seconds() // 3600)
    return out | {
        "eligible": False, "agent_may_resolve": False, "route_to": "Manager on Duty / AGM", "severity": "same_day",
        "assessment": f"Reported {hours_late} hours after the 72-hour window and not raised during the stay. "
                      "Not eligible for a refund or comp, but loyalty points can be offered as goodwill.",
        "recommended_action": "Offer goodwill loyalty points (front-desk discretion on amount). A refund request "
                              "outside the window goes to the MOD/AGM the same day.",
    }
