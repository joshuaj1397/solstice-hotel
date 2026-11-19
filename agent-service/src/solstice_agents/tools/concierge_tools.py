"""ADK function tools for the guest concierge.

Security model: tools never accept a guest_id from the model. Identity lives in session
state (set by the BFF after verification, or by find_reservation), so a prompt-injected
"show me guest G10009" has nothing to call.
"""

from __future__ import annotations

import functools
import json
import logging
from datetime import date

from google.adk.tools import ToolContext

from .. import services
from ..config import get_settings
from ..db import get_db
from ..rules import stay
from ..services import DomainError, clean

STAFF_NOTES_KEY = "staff_notes"
log = logging.getLogger(__name__)


def _guest(tc: ToolContext) -> str | None:
    return tc.state.get("guest_id")


def _need_guest() -> dict:
    return {"error": "not_verified",
            "message": "Ask the guest for their confirmation number and last name, then call find_reservation."}


def _transcript(tc: ToolContext) -> list[dict]:
    out = []
    try:
        for ev in tc.session.events:
            if ev.content and ev.content.parts:
                text = " ".join(p.text for p in ev.content.parts if getattr(p, "text", None))
                if text:
                    out.append({"role": "guest" if ev.author == "user" else "agent", "text": text})
    except Exception:  # noqa: BLE001
        pass
    return out


def _remember_staff_notes(tc: ToolContext, reservations: list[dict]) -> None:
    notes = [r.get("staff_guidance") for r in reservations if r.get("staff_guidance")]
    tc.state[STAFF_NOTES_KEY] = sorted(set((tc.state.get(STAFF_NOTES_KEY) or []) + notes))


def _stay_view(r: dict) -> dict:
    keep = ("reservation_id", "property_name", "city", "check_in", "check_out", "room_type", "rate_plan",
            "nightly_rate", "total_nights", "status", "card_on_file", "special_requests")
    v = {k: r.get(k) for k in keep}
    if r.get("staff_guidance"):
        v["staff_guidance_INTERNAL_do_not_quote"] = r["staff_guidance"]
    return v


def _parse_date(s: str) -> date:
    return date.fromisoformat(s.strip()[:10])


# ---------------------------------------------------------------------------
async def find_reservation(confirmation_number: str, last_name: str, tool_context: ToolContext) -> dict:
    """Verify a guest by confirmation number (e.g. R55001) and last name, then load their stays.

    Args:
      confirmation_number: The reservation confirmation number, like R55023.
      last_name: The guest's last name exactly as on the booking.
    """
    row = await services.verify_guest(confirmation_number, last_name)
    if not row:
        return {"verified": False, "message": "No reservation matches that confirmation number and last name."}
    tool_context.state["guest_id"] = row["guest_id"]
    prof = await services.guest_profile(row["guest_id"])
    _remember_staff_notes(tool_context, prof["reservations"])
    tool_context.state["guest_first_name"] = prof["guest"]["first_name"]
    return {"verified": True, "first_name": prof["guest"]["first_name"],
            "loyalty": stay.loyalty_benefits(prof["guest"]["loyalty_tier"]) | {"points": prof["guest"]["loyalty_points"]},
            "stays": [_stay_view(r) for r in prof["reservations"]]}


async def get_my_stay(tool_context: ToolContext) -> dict:
    """Get the signed-in guest's reservations, loyalty tier, points and tier benefits."""
    gid = _guest(tool_context)
    if not gid:
        return _need_guest()
    prof = await services.guest_profile(gid)
    _remember_staff_notes(tool_context, prof["reservations"])
    g = prof["guest"]
    return {"first_name": g["first_name"],
            "loyalty": stay.loyalty_benefits(g["loyalty_tier"]) | {"points": g["loyalty_points"],
                                                                     "member_since": g["member_since"]},
            "stays": [_stay_view(r) for r in prof["reservations"]], "today": get_settings().business_date.isoformat()}


async def lookup_policy(question: str, tool_context: ToolContext) -> dict:
    """Search the Solstice front-desk policy reference. Use for any rule: check-in/out times, cancellation,
    pets, smoking, parking, lost and found, extra guests, deposits, loyalty benefits.

    Args:
      question: The guest's question in plain words, e.g. "can I bring my dog".
    """
    rows = await get_db().fetch("SELECT section_no, title, body FROM agent.search_policy(%s, 2)", (question,))
    if not rows:
        return {"found": False, "message": "No written policy covers this. Offer to connect the guest with the team."}
    return {"found": True, "sections": [{"policy": r["section_no"], "title": r["title"], "text": r["body"]} for r in rows]}


async def property_info(property: str, tool_context: ToolContext) -> dict:
    """Facts about a Solstice property: location, room types and Best Available base rates, meeting space.

    Args:
      property: City or property name, e.g. "Austin" or "Solstice Tampa Bayshore".
    """
    cat = await services.catalog()
    p = cat.resolve(property)
    if not p:
        return {"found": False, "properties": [f"{x.name} ({x.city}, {x.state})" for x in cat.all()]}
    info = p.public()
    info["not_in_data"] = ["parking rates (ask the front desk)", "restaurant and spa hours"]
    return {"found": True, **info}


async def check_availability(city_or_property: str, check_in: str, check_out: str, tool_context: ToolContext,
                             room_type: str = "") -> dict:
    """Check live room availability and Best Available Rate for new stay dates. If nothing is available,
    the result includes alternative dates or nearby properties to offer.

    Args:
      city_or_property: City or property name.
      check_in: Arrival date YYYY-MM-DD.
      check_out: Departure date YYYY-MM-DD.
      room_type: Optional: Standard King, Standard Double, Deluxe King, Suite, Accessible King.
    """
    try:
        ci, co = _parse_date(check_in), _parse_date(check_out)
    except ValueError:
        return {"error": "bad_dates", "message": "Dates must be YYYY-MM-DD."}
    return await services.search_availability(city_or_property, ci, co, room_type or None,
                                               tool_context.state.get("session_id"))


async def hold_room(property_code: str, room_type: str, check_in: str, check_out: str,
                    tool_context: ToolContext) -> dict:
    """Hold one room for the guest for 15 minutes so they can complete booking with secure checkout.
    Only call after check_availability showed the room and the guest wants it.

    Args:
      property_code: e.g. SOL-AUS (from check_availability).
      room_type: Room type from check_availability.
      check_in: YYYY-MM-DD.
      check_out: YYYY-MM-DD.
    """
    try:
        return await services.place_stay_hold(property_code, room_type, _parse_date(check_in), _parse_date(check_out),
                                              _guest(tool_context), tool_context.state.get("session_id"))
    except DomainError as e:
        return {"error": e.code, "message": e.message}


async def request_stay_change(request: str, tool_context: ToolContext, reservation_id: str = "",
                              time: str = "", details: str = "") -> dict:
    """Log a request for the guest's stay and get the policy decision.

    Args:
      request: One of late_checkout, early_checkin, upgrade, amenity.
      reservation_id: Optional; defaults to the current or next stay.
      time: For late_checkout / early_checkin, the time wanted, e.g. "1pm".
      details: For amenity: what they want (rollaway, hypoallergenic bedding, champagne, connecting rooms...).
    """
    gid = _guest(tool_context)
    if not gid:
        return _need_guest()
    kind = request.strip().lower().replace(" ", "_").replace("-", "_")
    if kind not in ("late_checkout", "early_checkin", "upgrade", "amenity"):
        kind = "amenity"
        details = details or request
    try:
        return await services.create_request(gid, reservation_id or None, kind, time or None, details or None,
                                             tool_context.state.get("session_id"))
    except DomainError as e:
        return {"error": e.code, "message": e.message}


async def cancellation_options(tool_context: ToolContext, reservation_id: str = "") -> dict:
    """Explain what cancelling a stay would cost under its rate plan. Does NOT cancel. The guest confirms
    with the button shown in the app.

    Args:
      reservation_id: Optional; defaults to the next upcoming stay.
    """
    gid = _guest(tool_context)
    if not gid:
        return _need_guest()
    try:
        _, res = await services.guest_reservation(gid, reservation_id or None)
    except DomainError as e:
        return {"error": e.code, "message": e.message}
    quote = stay.cancellation_quote(res, get_settings().business_now)
    quote["property_name"] = res["property_name"]
    quote["retention_offer"] = ("Offer to look at different dates instead of cancelling, if that would help."
                                if quote.get("cancellable") and res["rate_plan"] != "Advance Purchase" else None)
    return quote


async def report_problem(issue_type: str, description: str, tool_context: ToolContext, reservation_id: str = "",
                         reported_during_stay: bool = False, amount_usd: float = 0.0) -> dict:
    """Service Recovery: a complaint about a stay, a disputed charge, or a refund/credit request. Checks the
    72-hour window and approval authority, then hands the case to the right staff with full context.
    Never promise money: staff decide.

    Args:
      issue_type: One of stay_problem, charge_dispute, refund_request, comp_night.
      description: What happened, in the guest's words.
      reservation_id: Optional; defaults to the most relevant stay.
      reported_during_stay: True if the guest says they told staff during the stay.
      amount_usd: Amount in dispute or requested, if mentioned.
    """
    gid = _guest(tool_context)
    if not gid:
        return _need_guest()
    try:
        _, res = await services.guest_reservation(gid, reservation_id or None)
    except DomainError as e:
        return {"error": e.code, "message": e.message}
    s = get_settings()
    itype = issue_type if issue_type in ("stay_problem", "charge_dispute", "refund_request", "comp_night") else "stay_problem"
    assessment = stay.service_recovery(res, s.business_now, issue_type=itype,
                                       reported_during_stay=bool(reported_during_stay), amount_usd=amount_usd or None)
    if res.get("staff_guidance"):
        assessment["staff_guidance"] = res["staff_guidance"]
    category = "dispute" if itype == "charge_dispute" else ("refund" if assessment["eligible"] is False or itype != "stay_problem" else "guest_request")
    case = await services.escalate(
        category=category, guest_ask=description, summary=f"{itype.replace('_', ' ')}: {description[:180]}",
        guest_id=gid, reservation_id=res["reservation_id"], property_code=res["property_code"],
        assessment=assessment, recommended_action=assessment["recommended_action"],
        transcript=_transcript(tool_context), session_id=tool_context.state.get("session_id"),
        policy_refs=assessment["policy_refs"], route_override=assessment["route_to"],
        severity_override=assessment["severity"])
    return {"assessment_for_guest": {k: assessment[k] for k in ("eligible", "assessment", "policy_refs")},
            "case": case}


async def escalate_to_staff(reason: str, tool_context: ToolContext, category: str = "guest_request") -> dict:
    """Hand the conversation to a human with full context. Use for anything outside policy or your tools:
    medical, safety, legal, media, VIP needs, heated disputes, or when the guest asks for a person.

    Args:
      reason: One-sentence summary of what the guest needs.
      category: One of safety, medical, legal, media, dispute, refund, vip, policy_gap, guest_request.
    """
    gid = _guest(tool_context)
    res = None
    if gid:
        try:
            _, res = await services.guest_reservation(gid, None)
        except DomainError:
            res = None
    transcript = _transcript(tool_context)
    case = await services.escalate(
        category=category, guest_ask=next((t["text"] for t in reversed(transcript) if t["role"] == "guest"), reason),
        summary=reason, guest_id=gid, reservation_id=res["reservation_id"] if res else None,
        property_code=res["property_code"] if res else None, assessment={"agent_summary": reason},
        recommended_action=None, transcript=transcript, session_id=tool_context.state.get("session_id"))
    return case


def _safe(fn):
    """A failing tool must not kill the turn: return a structured error the model can relay."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except DomainError as e:
            return {"error": e.code, "message": e.message}
        except Exception as exc:  # noqa: BLE001
            log.exception("tool %s failed", fn.__name__)
            return {"error": "tool_unavailable",
                    "message": f"That system is unavailable right now ({type(exc).__name__}). Do not guess; "
                               "offer to connect the guest with the team via escalate_to_staff."}
    return wrapper


CONCIERGE_TOOLS = [_safe(t) for t in (find_reservation, get_my_stay, lookup_policy, property_info, check_availability,
                                       hold_room, request_stay_change, cancellation_options, report_problem,
                                       escalate_to_staff)]

TOOL_LABELS = {
    "find_reservation": "Finding your reservation",
    "get_my_stay": "Pulling up your stay",
    "lookup_policy": "Checking Solstice policy",
    "property_info": "Looking up the hotel",
    "check_availability": "Checking live availability",
    "hold_room": "Holding your room",
    "request_stay_change": "Logging your request",
    "cancellation_options": "Checking your cancellation terms",
    "report_problem": "Reviewing service-recovery options",
    "escalate_to_staff": "Connecting you with the team",
}


def tool_evidence(response: dict) -> str:
    return json.dumps(response, default=str)
