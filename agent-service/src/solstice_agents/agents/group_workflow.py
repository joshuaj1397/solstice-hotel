"""Group Booking Workflow — ADK 2.x graph Workflow.

    START → intake ─┬─"email"→ extract(LLM) → register ─→ evaluate
                    └─"form"──────────────────────────→ evaluate
    evaluate ─┬─"clarify"→ clarification_prompt → clarification_writer(LLM) → finalize
              ├─"review"─→ rescue → proposal_prompt → proposal_writer(LLM) → finalize
              └─"auto"───→ hold_block ─┘

Deterministic nodes own every decision and number. LLM nodes only (a) turn a free-text
email into fields, which code then verifies against the email text, and (b) write prose,
which code checks number-by-number before it is saved. If either LLM step fails or
misbehaves, a template takes over: the workflow never blocks on the model.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.models.lite_llm import LiteLlm
from google.adk.workflow import START, Workflow
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .. import guardrails, services
from ..config import get_settings
from ..db import get_db
from ..rules import group as group_rules
from ..rules import rescue

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas for LLM nodes
# ---------------------------------------------------------------------------
class ExtractedInquiry(BaseModel):
    company_name: str | None = None
    contact_name: str | None = None
    event_type: str | None = None
    city_or_property: str | None = Field(None, description="Solstice city or property the client wants")
    arrival_date: str | None = Field(None, description="YYYY-MM-DD, null if not stated")
    departure_date: str | None = Field(None, description="YYYY-MM-DD, null if not stated")
    rooms_requested: int | None = None
    rooms_is_approximate: bool = False
    room_type_preference: str | None = Field(None, description="Standard King, Standard Double, Deluxe King or Suite")
    requested_discount_pct: float | None = None
    budget_per_night: float | None = None
    meeting_space_needed: bool = False
    meeting_capacity_needed: int | None = None
    alternate_property_ok: bool | None = None
    special_requests: str | None = None


class CoverNote(BaseModel):
    subject: str
    body: str


def _llm() -> LiteLlm:
    s = get_settings()
    return LiteLlm(model=s.model_id, api_base=s.ollama_base_url, think=False, keep_alive=s.keep_alive, num_ctx=s.num_ctx,
                   timeout=s.llm_timeout_s * 2, temperature=0.2)


def _trace(ctx: Context, node: str, summary: str, **extra) -> None:
    ctx.state["trace"] = (ctx.state.get("trace") or []) + [{"node": node, "summary": summary, **extra}]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
async def intake(node_input: str, ctx: Context):
    """Route: an inquiry id from the web portal, or a raw email body."""
    payload = json.loads(node_input) if node_input.strip().startswith("{") else {"inquiry_id": node_input.strip()}
    if payload.get("email"):
        clean, kinds = guardrails.redact_pii(payload["email"])
        contact_email = (re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", payload["email"]) or [None])[0]
        phone = (re.search(r"\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}", payload["email"]) or [None])[0]
        ctx.state["email"] = {"redacted": clean, "contact_email": contact_email, "contact_phone": phone}
        _trace(ctx, "intake", f"Email received; PII removed before the model sees it ({', '.join(kinds) or 'none found'}).")
        yield Event(output=(
            "Extract the group booking request from this email. Use null for anything not stated. "
            f"Today is {get_settings().business_date.isoformat()}; resolve dates to YYYY-MM-DD.\n\n---\n{clean}\n---"),
            route="email")
        return
    row = await get_db().fetchrow("SELECT * FROM agent.v_group_inquiries WHERE inquiry_id = %s", (payload["inquiry_id"],))
    if not row:
        raise ValueError(f"unknown inquiry {payload['inquiry_id']}")
    ctx.state["inquiry"] = services.clean(row)
    _trace(ctx, "intake", f"Loaded {row['inquiry_id']} from the reservation portal ({row['company_name']}).")
    yield Event(output=row["inquiry_id"], route="form")


extract = LlmAgent(
    name="extract",
    description="Turns a free-text group inquiry email into structured fields.",
    model=_llm(),
    instruction="You extract hotel group-booking requirements from emails into JSON. Never guess: use null.",
    output_schema=ExtractedInquiry,
)


async def register(node_input: dict, ctx: Context):
    """Verify extracted numbers against the email text, then save the inquiry."""
    email = ctx.state["email"]
    text = email["redacted"]
    x = ExtractedInquiry.model_validate(node_input)
    dropped = []
    for field in ("rooms_requested", "requested_discount_pct", "budget_per_night", "meeting_capacity_needed"):
        v = getattr(x, field)
        if v is not None and not re.search(rf"(?<!\d){int(v)}(?!\d)", text):
            dropped.append(field)
            setattr(x, field, None)
    if x.rooms_requested is not None:
        # The model proposes; code decides. "about 16 rooms" is approximate, "16 rooms ... around $190" is not.
        x.rooms_is_approximate = bool(re.search(
            rf"\b(about|around|approx\w*|roughly|~|maybe|up to)\s*{x.rooms_requested}\b", text, re.I))
    cat = await services.catalog()
    prop = cat.resolve(x.city_or_property)
    try:
        arrival = date.fromisoformat(x.arrival_date) if x.arrival_date else None
        departure = date.fromisoformat(x.departure_date) if x.departure_date else None
    except ValueError:
        arrival = departure = None
        dropped.append("dates")
    db = get_db()
    seq = (await db.fetchrow("SELECT nextval('ops.inquiry_seq') AS n"))["n"]
    iid = f"INQ-{seq}"
    await db.fetch(
        """INSERT INTO core.group_inquiries (inquiry_id, date_received, received_via, company_name, contact_name,
             contact_email, contact_phone, event_type, preferred_property_code, alternate_property_ok, arrival_date,
             departure_date, nights, rooms_requested_raw, rooms_requested, rooms_approximate, room_type_preference,
             requested_discount_pct, stated_budget_per_night, meeting_space_needed, meeting_capacity_needed,
             special_requests, raw_text)
           VALUES (%s,%s,'email',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (iid, get_settings().business_date, x.company_name, x.contact_name, email["contact_email"],
         email["contact_phone"], x.event_type, prop.code if prop else None, x.alternate_property_ok, arrival, departure,
         (departure - arrival).days if arrival and departure else None,
         str(x.rooms_requested) if x.rooms_requested else None, x.rooms_requested, x.rooms_is_approximate,
         x.room_type_preference, x.requested_discount_pct, x.budget_per_night, x.meeting_space_needed,
         x.meeting_capacity_needed, x.special_requests, text))
    row = await db.fetchrow("SELECT * FROM agent.v_group_inquiries WHERE inquiry_id = %s", (iid,))
    ctx.state["inquiry"] = services.clean(row)
    _trace(ctx, "register", f"Created {iid} from email." + (f" Discarded unverifiable fields: {', '.join(dropped)}." if dropped else ""),
           dropped=dropped)
    return iid


async def evaluate(node_input, ctx: Context):
    s = get_settings()
    inq = ctx.state["inquiry"]
    row = await get_db().fetchrow("SELECT * FROM agent.v_group_inquiries WHERE inquiry_id = %s", (inq["inquiry_id"],))
    req = group_rules.GroupRequest.from_row(row)
    decision = await group_rules.evaluate(req, await services.catalog(), s.business_date, budget_match=s.budget_match)
    ctx.state["decision"] = decision
    fails = [c["label"] for c in decision["checks"] if c["status"] == "fail"]
    _trace(ctx, "evaluate", f"{len(decision['checks'])} rule checks · status {decision['status']}"
           + (f" · flagged: {'; '.join(fails)}" if fails else ""))
    route = {"needs_clarification": "clarify", "needs_review": "review", "auto_approved": "auto"}[decision["status"]]
    yield Event(output=decision["status"], route=route)


async def rescue_node(node_input, ctx: Context):
    s = get_settings()
    decision = ctx.state["decision"]
    row = await get_db().fetchrow("SELECT * FROM agent.v_group_inquiries WHERE inquiry_id = %s", (decision["inquiry_id"],))
    alts = await rescue.group_alternatives(group_rules.GroupRequest.from_row(row), decision,
                                           await services.catalog(), s.business_date)
    decision["alternatives"] = alts
    ctx.state["decision"] = decision
    _trace(ctx, "rescue", f"Booking Rescue found {len(alts)} alternative(s); "
           f"{sum(1 for a in alts if a.get('auto_approvable'))} can be confirmed without GM review.")
    return "ok"


async def hold_block(node_input, ctx: Context):
    """Clean, in-policy request: hold the inventory now so the proposal is real, not aspirational."""
    s = get_settings()
    d = ctx.state["decision"]
    p, req = d["pricing"], d["requirements"]
    try:
        hold = await get_db().fetchrow(
            "SELECT * FROM agent.place_hold('group', %s, %s, %s::date, %s::date, %s::int, %s::int, %s, NULL, NULL, %s, "
            "%s::numeric, %s::jsonb)",
            (d["property"]["property_code"], req["room_type"], req["arrival"], req["departure"], req["rooms"],
             s.group_hold_ttl_hours * 60, f"group:{d['inquiry_id']}", d["inquiry_id"], p["group_rate"], Jsonb(p)))
        d["hold"] = {"hold_id": str(hold["hold_id"]), "expires_at": hold["expires_at"].isoformat(),
                     "hours": s.group_hold_ttl_hours}
        _trace(ctx, "hold_block", f"Courtesy hold placed: {req['rooms']} × {req['room_type']} for {s.group_hold_ttl_hours}h.")
    except Exception as exc:  # noqa: BLE001 — never auto-approve without a real hold: degrade to human review
        raced = "insufficient_inventory" in str(exc)
        d["status"] = "needs_review"
        d["flags"].append({"id": "inventory_race" if raced else "hold_error",
                           "label": "Inventory changed during processing" if raced else "Could not place courtesy hold",
                           "status": "fail", "severity": "hard", "detail": str(exc)[:200], "ref": "inventory_nights"})
        _trace(ctx, "hold_block", f"Hold failed ({'inventory changed' if raced else 'system error'}); routed to human review.")
    ctx.state["decision"] = d
    return "ok"


def _facts(d: dict) -> str:
    """Compact, pre-formatted facts. The writer may only restate these."""
    p, req = d.get("pricing") or {}, d["requirements"]
    lines = [f"Client: {d.get('contact_name')} at {d.get('company')} ({d.get('event_type')})",
             f"Hotel: {d['property']['property_name'] if d.get('property') else 'unknown'}",
             f"Dates: {req['arrival']} to {req['departure']} ({req['nights']} nights)",
             f"Rooms: {req['rooms']} x {req['room_type']}"]
    if p:
        lines.append(f"Group rate: ${p['group_rate']:.2f} per room per night ({p['requested_discount_pct']:g}% off "
                     f"${p['base_rate']:.2f}), subtotal ${p['subtotal']:,.2f} {p['taxes']}")
    if d.get("hold"):
        lines.append(f"Rooms are on courtesy hold for {d['hold']['hours']} hours.")
    for c in d.get("conditions", []):
        lines.append(f"Condition before confirming: {c['detail']}")
    for a in d.get("alternatives", [])[:3]:
        lines.append(f"Alternative: {a['label']}: {a['rooms']} rooms at ${a['rate']:.2f}/night "
                     f"({a['discount_pct']:g}% off){' - can confirm today' if a.get('auto_approvable') else ''}")
    if d["status"] == "needs_review":
        lines.append("Status: our sales team is reviewing parts of this request and will confirm.")
    if req.get("special_requests"):
        lines.append(f"Client notes: {req['special_requests']}")
    return "\n".join(lines)


def proposal_prompt(node_input, ctx: Context) -> str:
    return ("Write a short, warm cover note (max 120 words) from Solstice Hotel Group's group sales team to the "
            "client below. Use ONLY these facts; do not add prices, percentages, dates or promises that are not "
            "listed. Plain text, no markdown.\n\n" + _facts(ctx.state["decision"]))


def clarification_prompt(node_input, ctx: Context) -> str:
    d = ctx.state["decision"]
    items = "\n".join(f"- {m['question']}" for m in d["missing"] + d["optional_questions"])
    return ("Write a short, friendly email (max 110 words) from Solstice Hotel Group's group sales team thanking "
            f"{d.get('contact_name') or 'the client'} of {d.get('company') or 'their organization'} for their "
            f"{d.get('event_type') or 'group'} inquiry and asking ONLY for these details as a bulleted list:\n{items}\n"
            "Do not quote any rates. Plain text.")


proposal_writer = LlmAgent(name="proposal_writer", model=_llm(), output_schema=CoverNote,
                           instruction="You are a hotel group-sales coordinator. You write concise, accurate notes.")
clarification_writer = LlmAgent(name="clarification_writer", model=_llm(), output_schema=CoverNote,
                                instruction="You are a hotel group-sales coordinator. You write concise, friendly emails.")


def _template(d: dict) -> CoverNote:
    if d["status"] == "needs_clarification":
        items = "\n".join(f"- {m['question']}" for m in d["missing"] + d["optional_questions"])
        return CoverNote(subject=f"Your {d.get('event_type') or 'group'} inquiry: a few quick details",
                         body=f"Hi {d.get('contact_name') or 'there'},\n\nThank you for considering Solstice. "
                              f"To put together accurate options, could you share:\n{items}\n\nWarm regards,\n"
                              "Solstice Group Sales")
    return CoverNote(subject=f"Solstice group proposal: {d.get('company')}",
                     body=f"Hi {d.get('contact_name') or 'there'},\n\nThank you for your inquiry. Here is your proposal:\n"
                          f"{_facts(d)}\n\nWarm regards,\nSolstice Group Sales")


async def finalize(node_input, ctx: Context):
    d = ctx.state["decision"]
    try:
        note = CoverNote.model_validate(node_input)
        bad = guardrails.ungrounded_figures(note.body + " " + note.subject, json.dumps(d, default=str))
        if bad:
            await services.log_guardrail(None, "ungrounded_figure", {"inquiry_id": d["inquiry_id"], "figures": bad})
            _trace(ctx, "finalize", f"Writer used unverified figures {bad}; replaced with template.")
            note = _template(d)
        else:
            _trace(ctx, "finalize", "Cover note passed numeric grounding check.")
    except Exception as exc:  # noqa: BLE001
        _trace(ctx, "finalize", f"Writer output unusable ({type(exc).__name__}); template used.")
        note = _template(d)
    hold_ids = [d["hold"]["hold_id"]] if d.get("hold") else []
    row = await get_db().fetchrow(
        """INSERT INTO ops.group_proposals (inquiry_id, status, priority, decision, narrative, trace, hold_ids)
           VALUES (%s,%s,%s,%s,%s,%s,%s::uuid[]) RETURNING proposal_id, created_at""",
        (d["inquiry_id"], d["status"], d["priority"], Jsonb(d), json.dumps(note.model_dump()),
         Jsonb(ctx.state.get("trace") or []), hold_ids))
    await services.log_event(None, "group", "proposal_generated", d["property"]["property_code"] if d.get("property") else None,
                             d["pricing"]["subtotal"] if d.get("pricing") else None,
                             {"inquiry_id": d["inquiry_id"], "status": d["status"], "proposal_id": row["proposal_id"]})
    return {"proposal_id": row["proposal_id"], "status": d["status"], "priority": d["priority"],
            "decision": d, "cover_note": note.model_dump(), "trace": ctx.state.get("trace") or []}


def build_group_workflow() -> Workflow:
    return Workflow(
        name="group_booking",
        edges=[
            (START, intake),
            (intake, {"email": extract, "form": evaluate}),
            (extract, register, evaluate),
            (evaluate, {"clarify": clarification_prompt, "review": rescue_node, "auto": hold_block}),
            (clarification_prompt, clarification_writer, finalize),
            (rescue_node, proposal_prompt),
            (hold_block, proposal_prompt),
            (proposal_prompt, proposal_writer, finalize),
        ],
    )
