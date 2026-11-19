"""Agent service HTTP API (called only by the Next.js BFF, never by browsers directly)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from psycopg.types.json import Jsonb
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import guardrails, services
from .agents.concierge import GUARD_KEY, HINT_KEY, REPAIRED_KEY, build_concierge
from .agents.group_workflow import build_group_workflow
from .config import get_settings
from .db import get_db
from .rules import escalation, intent, stay
from .services import DomainError, clean
from .tools.concierge_tools import TOOL_LABELS

log = logging.getLogger("solstice.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

APP = "solstice"
state: dict = {"model_ok": False, "model_warm": False}


async def _sweeper():
    while True:
        try:
            await get_db().fetchrow("SELECT agent.expire_holds() AS n")
        except Exception as exc:  # noqa: BLE001
            log.debug("sweeper: %s", exc)
        await asyncio.sleep(15)


async def _model_probe():
    """Warm the model once, then keep a cheap health signal for graceful degradation."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            try:
                if not state["model_warm"]:
                    await client.post(f"{s.ollama_base_url}/api/generate",
                                      json={"model": s.model, "prompt": "ok", "stream": False,
                                            "keep_alive": s.keep_alive, "options": {"num_predict": 1, "num_ctx": s.num_ctx}})
                    await _warm_prefix()
                    state["model_warm"] = True
                    log.info("model %s warm (weights + prompt prefix)", s.model)
                r = await client.get(f"{s.ollama_base_url}/api/ps", timeout=3)
                loaded = any(m.get("name", "").startswith(s.model) for m in r.json().get("models", []))
                state["model_ok"] = True
                state["model_warm"] = loaded
            except Exception as exc:  # noqa: BLE001
                state["model_ok"] = False
                state["model_warm"] = False
                log.warning("model probe failed: %s", exc)
            await asyncio.sleep(20)


async def _warm_prefix() -> None:
    """Run one throwaway turn through the real concierge path so Ollama caches the static prefix
    (system prompt + tool schemas). Without this the first guest of the day pays ~7 s of prefill."""
    try:
        sessions: InMemorySessionService = state["sessions"]
        sess = await sessions.create_session(app_name=APP, user_id="warmup", state={"session_id": "warmup"})
        async for _ in state["concierge"].run_async(
                user_id="warmup", session_id=sess.id,
                new_message=types.Content(role="user", parts=[types.Part(text="What time is check-in?")])):
            pass
        await sessions.delete_session(app_name=APP, user_id="warmup", session_id=sess.id)
    except Exception as exc:  # noqa: BLE001
        log.warning("prefix warm-up failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    await db.open()
    await services.catalog()
    sessions = InMemorySessionService()
    state["sessions"] = sessions
    state["concierge"] = Runner(app_name=APP, agent=build_concierge(), session_service=sessions)
    state["group_sessions"] = InMemorySessionService()
    state["group"] = Runner(app_name="group_booking", node=build_group_workflow(),
                            session_service=state["group_sessions"])
    tasks = [asyncio.create_task(_sweeper()), asyncio.create_task(_model_probe())]
    yield
    for t in tasks:
        t.cancel()
    await db.close()


app = FastAPI(title="Solstice Agent Service", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])


def require_service(x_service_token: str | None = Header(default=None)) -> None:
    expected = get_db().service_token
    if expected and x_service_token != expected:
        raise HTTPException(401, "invalid service token")


@app.exception_handler(DomainError)
async def domain_error(_: Request, exc: DomainError):
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": exc.code, "message": exc.message}, status_code=409)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    s = get_settings()
    return {"db": await get_db().ping(), "model": state["model_ok"], "model_warm": state["model_warm"],
            "model_name": s.model, "business_date": s.business_date.isoformat(), "vault_mode": s.vault_mode}


# ---------------------------------------------------------------------------
# Guest identity
# ---------------------------------------------------------------------------
class VerifyIn(BaseModel):
    reservation_id: str
    last_name: str


@app.post("/v1/guest/verify", dependencies=[Depends(require_service)])
async def verify(body: VerifyIn):
    row = await services.verify_guest(body.reservation_id, body.last_name)
    if not row:
        raise HTTPException(404, "No reservation matches that confirmation number and last name.")
    return await guest_profile(row["guest_id"])


@app.get("/v1/guest/{guest_id}", dependencies=[Depends(require_service)])
async def guest_profile(guest_id: str):
    prof = await services.guest_profile(guest_id)
    if not prof["guest"]:
        raise HTTPException(404, "guest not found")
    tier = prof["guest"]["loyalty_tier"]
    for r in prof["reservations"]:
        r.pop("staff_guidance", None)          # internal notes never leave the service toward guests
    db = get_db()
    requests = await db.fetch("SELECT request_id, kind, reservation_id, status, details, created_at FROM ops.service_requests "
                              "WHERE guest_id = %s ORDER BY created_at DESC LIMIT 20", (guest_id,))
    cases = await db.fetch("SELECT case_id, category, severity, route_to, status, created_at, sla_due_at FROM ops.escalations "
                           "WHERE guest_id = %s ORDER BY created_at DESC LIMIT 10", (guest_id,))
    return {**prof, "benefits": stay.loyalty_benefits(tier), "today": get_settings().business_date.isoformat(),
            "requests": [clean(r) for r in requests], "cases": [clean(c) for c in cases]}


# ---------------------------------------------------------------------------
# Concierge chat
# ---------------------------------------------------------------------------
class SessionIn(BaseModel):
    guest_id: str | None = None


@app.post("/v1/concierge/sessions", dependencies=[Depends(require_service)])
async def new_session(body: SessionIn):
    sid = f"cs_{uuid.uuid4().hex[:16]}"
    st: dict = {"session_id": sid}
    if body.guest_id:
        prof = await services.guest_profile(body.guest_id)
        if not prof["guest"]:
            raise HTTPException(404, "guest not found")
        g = prof["guest"]
        st |= {"guest_id": g["guest_id"], "guest_first_name": g["first_name"], "loyalty_tier": g["loyalty_tier"],
               "stay_summary": "; ".join(f"{r['reservation_id']} {r['property_name']} {r['check_in']}→{r['check_out']} "
                                         f"{r['room_type']} {r['rate_plan']} ({r['status']})" for r in prof["reservations"]),
               "staff_notes": [r["staff_guidance"] for r in prof["reservations"] if r.get("staff_guidance")]}
    await state["sessions"].create_session(app_name=APP, user_id=body.guest_id or "anonymous", session_id=sid, state=st)
    await services.log_event(sid, "concierge", "session_start", meta={"verified": bool(body.guest_id)})
    return {"session_id": sid}


class MessageIn(BaseModel):
    text: str
    guest_id: str | None = None


def _sse(kind: str, **data) -> dict:
    return {"event": kind, "data": json.dumps(data, default=str)}


async def _degraded_reply(text: str) -> str:
    """Model unavailable: answer from policy search (no LLM) and point at the buttons that still work."""
    rows = await get_db().fetch("SELECT section_no, title, body FROM agent.search_policy(%s, 1)", (text,))
    if rows:
        r = rows[0]
        return (f"Our assistant is running in limited mode right now, but here is the relevant policy: "
                f"Policy {r['section_no']}, {r['title'].title()}: {r['body']}\n\nThe buttons on your stay card "
                "still work for requests, and you can ask for a team member anytime.")
    return ("Our assistant is running in limited mode right now. The buttons on your stay card still work for "
            "late check-out, early check-in and cancellations, and you can reach a team member with "
            "\"Talk to a person\".")


@app.post("/v1/concierge/sessions/{sid}/messages", dependencies=[Depends(require_service)])
async def send_message(sid: str, body: MessageIn):
    sessions: InMemorySessionService = state["sessions"]
    user_id = body.guest_id or "anonymous"
    session = await sessions.get_session(app_name=APP, user_id=user_id, session_id=sid)
    if not session:
        raise HTTPException(404, "session not found")

    async def stream():
        t0 = time.perf_counter()
        tools_used: list[str] = []
        text, kinds = guardrails.redact_pii(body.text)
        if kinds:
            await services.log_guardrail(sid, "pii_redacted", {"kinds": kinds})
            yield _sse("notice", text="For your security, I removed sensitive details (like card numbers) from "
                                      "your message. Please never share them in chat.", kinds=kinds)
        if guardrails.injection_score(text):
            await services.log_guardrail(sid, "injection_attempt", {"text": text[:300]})

        # 1) Deterministic risk triage: safety/medical/legal/media never wait on the model.
        category = escalation.triage(text)
        if category:
            st = session.state
            res = None
            if st.get("guest_id"):
                try:
                    _, res = await services.guest_reservation(st["guest_id"], None)
                except DomainError:
                    res = None
            case = await services.escalate(
                category=category, guest_ask=text, summary=f"Triage: {category} keywords detected",
                guest_id=st.get("guest_id"), reservation_id=res["reservation_id"] if res else None,
                property_code=res["property_code"] if res else None,
                assessment={"triage": category, "bypassed_llm": True}, recommended_action="Contact the guest now.",
                transcript=[{"role": "guest", "text": text}], session_id=sid)
            yield _sse("card", card={"kind": "escalate_to_staff", "data": case})
            msg = escalation.SCRIPTED[category].format(case_id=case["case_id"])
            yield _sse("message", text=msg)
            ms = int((time.perf_counter() - t0) * 1000)
            await _log_turn(sid, ms, 0, ["triage"], "triage_bypass")
            yield _sse("done", latency_ms=ms, path="triage_bypass", tools=["escalate"])
            return

        # 2) Model path, with a hard timeout and graceful degradation.
        if not state["model_ok"]:
            yield _sse("message", text=await _degraded_reply(text), degraded=True)
            ms = int((time.perf_counter() - t0) * 1000)
            await _log_turn(sid, ms, 0, [], "degraded")
            yield _sse("done", latency_ms=ms, path="degraded", tools=[])
            return

        runner: Runner = state["concierge"]
        final_text, llm_calls = None, 0
        queue: asyncio.Queue = asyncio.Queue()
        abort = asyncio.Event()

        async def pump():
            try:
                async for ev in runner.run_async(
                        user_id=user_id, session_id=sid, abort_signal=abort,
                        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
                        state_delta=turn_state):
                    await queue.put(ev)
            except Exception as exc:  # noqa: BLE001
                await queue.put(exc)
            finally:
                await queue.put(None)

        hint = intent.detect(text)
        if hint:
            yield _sse("route", tool=hint.tool, reason=hint.reason)
        turn_state = {"last_user_text": text, "turn_evidence": "", GUARD_KEY: None,
                      HINT_KEY: hint.as_dict() if hint else None, REPAIRED_KEY: False}
        task = asyncio.create_task(pump())
        deadline = t0 + get_settings().llm_timeout_s
        try:
            while True:
                ev = await asyncio.wait_for(queue.get(), timeout=max(0.1, deadline - time.perf_counter()))
                if ev is None:
                    break
                if isinstance(ev, Exception):
                    raise ev
                if ev.author != "user" and ev.content:
                    llm_calls += 1 if any(getattr(p, "function_call", None) or getattr(p, "text", None)
                                          for p in ev.content.parts or []) else 0
                for fc in ev.get_function_calls():
                    tools_used.append(fc.name)
                    yield _sse("status", tool=fc.name, label=TOOL_LABELS.get(fc.name, "Working on it"))
                for fr in ev.get_function_responses():
                    yield _sse("card", card={"kind": fr.name, "data": fr.response})
                if ev.content and ev.content.parts and not ev.partial and not ev.get_function_calls():
                    t = "".join(p.text or "" for p in ev.content.parts if not getattr(p, "thought", False))
                    if t.strip():
                        final_text = t.strip()
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            abort.set()
            task.cancel()
            log.warning("concierge turn failed/timeout: %r", exc)
            yield _sse("message", text=await _degraded_reply(text), degraded=True)
            ms = int((time.perf_counter() - t0) * 1000)
            await _log_turn(sid, ms, llm_calls, tools_used, "degraded")
            yield _sse("done", latency_ms=ms, path="degraded", tools=tools_used)
            return

        refreshed = await sessions.get_session(app_name=APP, user_id=user_id, session_id=sid)
        guard = refreshed.state.get(GUARD_KEY) if refreshed else None
        guard_kind = None
        if guard:
            guard_kind = "blocked" if guard.get("blocked") else "tool_call_repaired"
            await services.log_guardrail(sid, guard_kind, guard)
        yield _sse("message", text=final_text or "Sorry, I didn't catch that. Could you rephrase?",
                   guardrail=guard_kind)
        ms = int((time.perf_counter() - t0) * 1000)
        await _log_turn(sid, ms, llm_calls, tools_used, "llm")
        if not any(t in tools_used for t in ("escalate_to_staff", "report_problem")):
            await services.log_event(sid, "concierge", "resolved_by_agent", meta={"tools": tools_used})
        yield _sse("done", latency_ms=ms, path="llm", tools=tools_used)

    return EventSourceResponse(stream())


async def _log_turn(sid: str, ms: int, llm_calls: int, tools: list[str], path: str) -> None:
    try:
        await get_db().fetchrow(
            "INSERT INTO ops.turn_metrics (session_id, agent, latency_ms, llm_calls, tool_calls, path, model) "
            "VALUES (%s,'concierge',%s,%s,%s,%s,%s) RETURNING turn_id",
            (sid, ms, llm_calls, tools, path, get_settings().model))
    except Exception as exc:  # noqa: BLE001
        log.warning("turn metric dropped: %s", exc)


@app.get("/v1/concierge/sessions/{sid}/updates", dependencies=[Depends(require_service)])
async def session_updates(sid: str, after: int = 0):
    """Staff replies on cases opened from this chat, so hand-offs flow back into the conversation."""
    rows = await get_db().fetch(
        "SELECT m.message_id, m.case_id, m.author_name, m.body, m.created_at, e.status FROM ops.escalation_messages m "
        "JOIN ops.escalations e USING (case_id) WHERE e.session_id = %s AND m.author = 'staff' AND m.message_id > %s "
        "ORDER BY m.message_id", (sid, after))
    return [clean(r) for r in rows]


# ---------------------------------------------------------------------------
# Deterministic quick actions (work without the model)
# ---------------------------------------------------------------------------
class RequestIn(BaseModel):
    guest_id: str
    reservation_id: str | None = None
    kind: str
    time: str | None = None
    details: str | None = None
    session_id: str | None = None


@app.post("/v1/actions/request", dependencies=[Depends(require_service)])
async def action_request(body: RequestIn):
    out = await services.create_request(body.guest_id, body.reservation_id, body.kind, body.time, body.details,
                                        body.session_id)
    await services.log_event(body.session_id, "quick_action", "request_created", meta={"kind": body.kind})
    return out


class CancelIn(BaseModel):
    guest_id: str
    reservation_id: str
    confirm: bool = False
    session_id: str | None = None


@app.post("/v1/actions/cancel", dependencies=[Depends(require_service)])
async def action_cancel(body: CancelIn):
    _, res = await services.guest_reservation(body.guest_id, body.reservation_id)
    quote = stay.cancellation_quote(res, get_settings().business_now)
    if not body.confirm:
        return {"quote": quote}
    if not quote.get("cancellable"):
        raise DomainError("not_cancellable", quote["explanation"])
    status = (await get_db().fetchrow("SELECT agent.cancel_reservation(%s, %s) AS s",
                                      (res["reservation_id"], body.guest_id)))["s"]
    await services.log_event(body.session_id, "quick_action", "reservation_cancelled", res["property_code"],
                             meta={"reservation_id": res["reservation_id"], "free": quote.get("free_cancellation")})
    return {"status": status, "quote": quote}


class EscalateIn(BaseModel):
    guest_id: str | None = None
    session_id: str | None = None
    reason: str
    transcript: list[dict] = []


@app.post("/v1/actions/escalate", dependencies=[Depends(require_service)])
async def action_escalate(body: EscalateIn):
    res = None
    if body.guest_id:
        try:
            _, res = await services.guest_reservation(body.guest_id, None)
        except DomainError:
            pass
    reason, _ = guardrails.redact_pii(body.reason)
    return await services.escalate(
        category="guest_request", guest_ask=reason, summary=reason, guest_id=body.guest_id,
        reservation_id=res["reservation_id"] if res else None, property_code=res["property_code"] if res else None,
        assessment={"source": "talk_to_a_person_button"}, recommended_action=None,
        transcript=[{"role": t.get("role"), "text": guardrails.redact_pii(t.get("text", ""))[0]} for t in body.transcript],
        session_id=body.session_id)


@app.get("/v1/policy/search", dependencies=[Depends(require_service)])
async def policy_search(q: str):
    return [clean(r) for r in await get_db().fetch("SELECT * FROM agent.search_policy(%s, 3)", (q,))]


@app.get("/v1/properties", dependencies=[Depends(require_service)])
async def properties():
    return [p.public() for p in (await services.catalog()).all()]


@app.get("/v1/availability", dependencies=[Depends(require_service)])
async def availability(where: str, check_in: date, check_out: date, room_type: str | None = None,
                       session_id: str | None = None):
    return await services.search_availability(where, check_in, check_out, room_type, session_id)


class HoldIn(BaseModel):
    property_code: str
    room_type: str
    check_in: date
    check_out: date
    session_id: str | None = None
    guest_id: str | None = None
    idempotency_key: str | None = None


@app.post("/v1/holds", dependencies=[Depends(require_service)])
async def create_hold(body: HoldIn):
    return await services.place_stay_hold(body.property_code, body.room_type, body.check_in, body.check_out,
                                          body.guest_id, body.session_id, body.idempotency_key)


class BookingIn(BaseModel):
    hold_id: str
    first_name: str
    last_name: str
    email: str
    card_last4: str            # the BFF's payment tokenizer returns only last4 + token; PAN never arrives here
    guest_id: str | None = None
    session_id: str | None = None


@app.post("/v1/bookings", dependencies=[Depends(require_service)])
async def create_booking(body: BookingIn):
    db = get_db()
    gid = body.guest_id or (await db.fetchrow("SELECT agent.upsert_portal_guest(%s,%s,%s) AS g",
                                              (body.first_name, body.last_name, body.email)))["g"]
    try:
        hold = await db.fetchrow("SELECT * FROM agent.convert_hold(%s::uuid, %s, %s)",
                                 (body.hold_id, gid, body.card_last4[-4:]))
    except Exception as exc:  # noqa: BLE001
        if "hold_expired" in str(exc):
            raise DomainError("hold_expired", "This hold expired. Please check availability again.")
        raise
    total = float(hold["nightly_rate"] or 0) * (hold["check_out"] - hold["check_in"]).days
    await services.log_event(body.session_id, "booking", "booking_confirmed", hold["property_code"], total,
                             {"reservation_id": hold["reservation_id"]})
    return {"reservation_id": hold["reservation_id"], "guest_id": gid, "property_code": hold["property_code"],
            "room_type": hold["room_type"], "check_in": hold["check_in"].isoformat(),
            "check_out": hold["check_out"].isoformat(), "total_before_tax": total}


# ---------------------------------------------------------------------------
# Group booking workflow
# ---------------------------------------------------------------------------
@app.get("/v1/group/inquiries", dependencies=[Depends(require_service)])
async def group_inquiries():
    rows = await get_db().fetch(
        """SELECT i.*, p.proposal_id, p.status AS proposal_status, p.priority, p.created_at AS proposal_at
             FROM agent.v_group_inquiries i
             LEFT JOIN LATERAL (SELECT * FROM ops.group_proposals gp WHERE gp.inquiry_id = i.inquiry_id
                                ORDER BY created_at DESC LIMIT 1) p ON true
            ORDER BY i.inquiry_id""")
    return [clean(r) for r in rows]


async def _run_group(payload: str):
    runner: Runner = state["group"]
    sess = await state["group_sessions"].create_session(app_name="group_booking", user_id="sales")
    t0 = time.perf_counter()
    result = None
    try:
        async for ev in runner.run_async(user_id="sales", session_id=sess.id,
                                         new_message=types.Content(role="user", parts=[types.Part(text=payload)])):
            node = (ev.node_info.path or "").split("/")[-1].split("@")[0] if ev.node_info else ev.author
            if ev.output is not None or (ev.actions and ev.actions.route):
                yield _sse("step", node=node, ms=int((time.perf_counter() - t0) * 1000),
                           route=ev.actions.route if ev.actions else None)
            if node == "finalize" and isinstance(ev.output, dict):
                result = ev.output
    except Exception as exc:  # noqa: BLE001
        log.exception("group workflow failed")
        yield _sse("error", message=str(exc)[:300])
        return
    ms = int((time.perf_counter() - t0) * 1000)
    if result:
        await get_db().fetchrow("UPDATE ops.group_proposals SET latency_ms = %s WHERE proposal_id = %s RETURNING 1",
                                (ms, result["proposal_id"]))
        yield _sse("result", latency_ms=ms, **result)
    yield _sse("done", latency_ms=ms)


@app.post("/v1/group/inquiries/{inquiry_id}/run", dependencies=[Depends(require_service)])
async def run_inquiry(inquiry_id: str):
    return EventSourceResponse(_run_group(json.dumps({"inquiry_id": inquiry_id})))


class GroupRequestIn(BaseModel):
    company_name: str
    contact_name: str
    contact_email: str
    contact_phone: str | None = None
    event_type: str | None = None
    preferred_property_code: str
    alternate_property_ok: bool = False
    arrival_date: date | None = None
    departure_date: date | None = None
    rooms_requested: int | None = None
    room_type_preference: str | None = None
    requested_discount_pct: float | None = None
    stated_budget_per_night: float | None = None
    meeting_space_needed: bool = False
    meeting_capacity_needed: int | None = None
    special_requests: str | None = None


@app.post("/v1/group/inquiries", dependencies=[Depends(require_service)])
async def create_group_inquiry(body: GroupRequestIn):
    """Structured web-portal request: saved as-is (no LLM parsing needed), then run through the workflow."""
    db = get_db()
    iid = f"INQ-{(await db.fetchrow('SELECT nextval(%s) AS n', ('ops.inquiry_seq',)))['n']}"
    nights = (body.departure_date - body.arrival_date).days if body.arrival_date and body.departure_date else None
    special, _ = guardrails.redact_pii(body.special_requests or "")
    await db.fetch(
        """INSERT INTO core.group_inquiries (inquiry_id, date_received, received_via, company_name, contact_name,
             contact_email, contact_phone, event_type, preferred_property_code, alternate_property_ok, arrival_date,
             departure_date, nights, rooms_requested_raw, rooms_requested, rooms_approximate, room_type_preference,
             requested_discount_pct, stated_budget_per_night, meeting_space_needed, meeting_capacity_needed, special_requests)
           VALUES (%s,%s,'web_portal',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s,%s,%s,%s)""",
        (iid, get_settings().business_date, body.company_name, body.contact_name, body.contact_email,
         body.contact_phone, body.event_type, body.preferred_property_code.upper(), body.alternate_property_ok,
         body.arrival_date, body.departure_date, nights,
         str(body.rooms_requested) if body.rooms_requested else None, body.rooms_requested, body.room_type_preference,
         body.requested_discount_pct, body.stated_budget_per_night, body.meeting_space_needed,
         body.meeting_capacity_needed, special or None))
    return EventSourceResponse(_run_group(json.dumps({"inquiry_id": iid})))


class EmailIn(BaseModel):
    email: str


@app.post("/v1/group/intake/email", dependencies=[Depends(require_service)])
async def run_email(body: EmailIn):
    return EventSourceResponse(_run_group(json.dumps({"email": body.email})))


@app.get("/v1/group/proposals/{proposal_id}", dependencies=[Depends(require_service)])
async def get_proposal(proposal_id: str):
    row = await get_db().fetchrow("SELECT * FROM ops.group_proposals WHERE proposal_id = %s", (proposal_id,))
    if not row:
        raise HTTPException(404)
    out = clean(row)
    out["cover_note"] = json.loads(row["narrative"]) if row["narrative"] else None
    return out


# ---------------------------------------------------------------------------
# Staff console (staff DB role)
# ---------------------------------------------------------------------------
@app.get("/v1/staff/queue", dependencies=[Depends(require_service)])
async def staff_queue():
    db = get_db()
    esc = await db.fetch(
        """SELECT e.*, g.first_name || ' ' || g.last_name AS guest_name, g.loyalty_tier, p.property_name,
                  (SELECT count(*) FROM ops.escalation_messages m WHERE m.case_id = e.case_id) AS messages
             FROM ops.escalations e LEFT JOIN core.guests g USING (guest_id) LEFT JOIN core.properties p USING (property_code)
            ORDER BY (e.status = 'resolved'), CASE e.severity WHEN 'immediate' THEN 0 WHEN 'same_day' THEN 1 ELSE 2 END,
                     e.created_at DESC LIMIT 100""", staff=True)
    reqs = await db.fetch(
        """SELECT r.*, g.first_name || ' ' || g.last_name AS guest_name, g.loyalty_tier, p.property_name
             FROM ops.service_requests r JOIN core.guests g USING (guest_id) JOIN core.properties p USING (property_code)
            ORDER BY (r.status <> 'pending_desk'), r.created_at DESC LIMIT 100""", staff=True)
    props = await db.fetch(
        """SELECT gp.proposal_id, gp.inquiry_id, gp.status, gp.priority, gp.created_at, gp.latency_ms,
                  gp.decision->'property'->>'property_name' AS property_name, i.company_name,
                  jsonb_array_length(gp.decision->'flags') AS flag_count
             FROM ops.group_proposals gp JOIN core.group_inquiries i USING (inquiry_id)
            ORDER BY (gp.status NOT IN ('needs_review', 'needs_clarification')), (gp.priority <> 'urgent'), gp.created_at DESC""",
        staff=True)
    return {"escalations": [clean(r) for r in esc], "requests": [clean(r) for r in reqs],
            "proposals": [clean(r) for r in props]}


@app.get("/v1/staff/escalations/{case_id}", dependencies=[Depends(require_service)])
async def staff_case(case_id: str):
    db = get_db()
    row = await db.fetchrow(
        """SELECT e.*, g.first_name, g.last_name, g.loyalty_tier, g.loyalty_points, p.property_name,
                  r.check_in, r.check_out, r.room_type, r.rate_plan, r.nightly_rate, r.status AS reservation_status,
                  r.internal_notes
             FROM ops.escalations e LEFT JOIN core.guests g USING (guest_id)
             LEFT JOIN core.properties p USING (property_code) LEFT JOIN core.reservations r USING (reservation_id)
            WHERE e.case_id = %s""", (case_id,), staff=True)
    if not row:
        raise HTTPException(404)
    msgs = await db.fetch("SELECT * FROM ops.escalation_messages WHERE case_id = %s ORDER BY message_id", (case_id,), staff=True)
    return {**clean(row), "messages": [clean(m) for m in msgs]}


class ReplyIn(BaseModel):
    body: str
    author_name: str = "Front Desk"
    resolve: bool = False


@app.post("/v1/staff/escalations/{case_id}/reply", dependencies=[Depends(require_service)])
async def staff_reply(case_id: str, body: ReplyIn):
    db = get_db()
    async with db.staff_conn() as conn:
        async with conn.transaction():
            await conn.execute("INSERT INTO ops.escalation_messages (case_id, author, author_name, body) "
                               "VALUES (%s,'staff',%s,%s)", (case_id, body.author_name, body.body))
            await conn.execute(
                "UPDATE ops.escalations SET status = %s, assigned_to = coalesce(assigned_to, %s), "
                "resolution_note = CASE WHEN %s THEN %s ELSE resolution_note END, "
                "resolved_at = CASE WHEN %s THEN now() ELSE resolved_at END WHERE case_id = %s",
                ("resolved" if body.resolve else "acknowledged", body.author_name, body.resolve, body.body,
                 body.resolve, case_id))
    return await staff_case(case_id)


class DecideIn(BaseModel):
    status: str   # approved | declined
    note: str | None = None
    staff: str = "Front Desk"


@app.post("/v1/staff/requests/{request_id}/decide", dependencies=[Depends(require_service)])
async def staff_decide(request_id: str, body: DecideIn):
    if body.status not in ("approved", "declined"):
        raise HTTPException(422, "status must be approved or declined")
    row = await get_db().fetchrow(
        "UPDATE ops.service_requests SET status = %s, desk_note = %s, decided_by = %s, decided_at = now() "
        "WHERE request_id = %s RETURNING request_id, status", (body.status, body.note, body.staff, request_id), staff=True)
    return clean(row)


class ApproveIn(BaseModel):
    option: str = "requested"     # requested | alternative:<index> | decline | send
    reviewer: str = "Group Sales"
    note: str | None = None


@app.post("/v1/staff/proposals/{proposal_id}/review", dependencies=[Depends(require_service)])
async def staff_review(proposal_id: str, body: ApproveIn):
    db = get_db()
    gp = await db.fetchrow("SELECT * FROM ops.group_proposals WHERE proposal_id = %s", (proposal_id,), staff=True)
    if not gp:
        raise HTTPException(404)
    d = gp["decision"]
    hold_ids = list(gp["hold_ids"] or [])
    if body.option == "decline":
        status = "declined"
    else:
        status = "sent" if body.option == "send" else "approved"
        if body.option.startswith("alternative:"):
            alt = d["alternatives"][int(body.option.split(":")[1])]
            target = (alt["property_code"], alt["room_type"], alt["arrival"], alt["departure"], alt["rooms"], alt["rate"])
        else:
            req, p = d["requirements"], d.get("pricing") or {}
            target = (d["property"]["property_code"], req["room_type"], req["arrival"], req["departure"], req["rooms"],
                      p.get("group_rate"))
        if not hold_ids and body.option != "send":
            try:
                hold = await db.fetchrow(
                    "SELECT * FROM agent.place_hold('group', %s, %s, %s::date, %s::date, %s::int, %s::int, %s, NULL, NULL, "
                    "%s, %s::numeric, %s::jsonb)",
                    (*target[:5], get_settings().group_hold_ttl_hours * 60, f"group:{gp['inquiry_id']}:{body.option}",
                     gp["inquiry_id"], target[5], Jsonb({"approved_by": body.reviewer})), staff=True)
                hold_ids.append(hold["hold_id"])
            except Exception as exc:  # noqa: BLE001
                raise DomainError("hold_failed", f"Could not hold inventory: {str(exc)[:160]}")
    row = await db.fetchrow(
        "UPDATE ops.group_proposals SET status = %s, reviewed_by = %s, reviewed_at = now(), review_note = %s, "
        "hold_ids = %s::uuid[] WHERE proposal_id = %s RETURNING proposal_id, status, hold_ids",
        (status, body.reviewer, body.note, [str(h) for h in hold_ids], proposal_id), staff=True)
    await db.fetchrow("INSERT INTO ops.funnel_events (channel, event, property_code, meta) VALUES "
                      "('group', %s, %s, %s) RETURNING event_id",
                      (f"proposal_{status}", d["property"]["property_code"] if d.get("property") else None,
                       Jsonb({"proposal_id": proposal_id, "option": body.option})), staff=True)
    return clean(row)


@app.get("/v1/staff/metrics", dependencies=[Depends(require_service)])
async def staff_metrics():
    db = get_db()
    funnel = await db.fetch("SELECT event, count(*)::int AS n, coalesce(sum(value_usd),0)::float AS usd "
                            "FROM ops.funnel_events GROUP BY event ORDER BY n DESC", staff=True)
    lat = await db.fetchrow(
        """SELECT count(*)::int AS turns,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)::int AS p50,
                  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::int AS p95,
                  count(*) FILTER (WHERE path = 'degraded')::int AS degraded,
                  count(*) FILTER (WHERE path = 'triage_bypass')::int AS triaged
             FROM ops.turn_metrics""", staff=True)
    by_path = await db.fetch("SELECT path, count(*)::int AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)::int AS p50, "
                             "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::int AS p95 "
                             "FROM ops.turn_metrics GROUP BY path", staff=True)
    guards = await db.fetch("SELECT kind, count(*)::int AS n FROM ops.guardrail_events GROUP BY kind", staff=True)
    proposals = await db.fetch("SELECT status, count(*)::int AS n, avg(latency_ms)::int AS avg_ms FROM ops.group_proposals "
                               "GROUP BY status", staff=True)
    dq = await db.fetch("SELECT * FROM core.data_quality_issues ORDER BY issue_id", staff=True)
    sessions = await db.fetchrow("SELECT count(DISTINCT session_id)::int AS n FROM ops.funnel_events "
                                 "WHERE event = 'session_start'", staff=True)
    escalated = await db.fetchrow("SELECT count(DISTINCT session_id)::int AS n FROM ops.escalations WHERE session_id IS NOT NULL",
                                  staff=True)
    n_sessions = sessions["n"] or 0
    return {"funnel": funnel, "latency": lat, "latency_by_path": by_path, "guardrails": guards, "proposals": proposals,
            "data_quality": [clean(r) for r in dq],
            "containment_rate": round(1 - (escalated["n"] / n_sessions), 3) if n_sessions else None,
            "sessions": n_sessions}


def run() -> None:
    import sys

    import uvicorn
    if sys.platform == "win32":   # psycopg async needs the selector loop on Windows (containers run Linux)
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        config = uvicorn.Config("solstice_agents.api:app", host="127.0.0.1", port=8080, log_level="info", loop="none")
        asyncio.run(uvicorn.Server(config).serve())
        return
    uvicorn.run("solstice_agents.api:app", host="0.0.0.0", port=8080, log_level="info")
