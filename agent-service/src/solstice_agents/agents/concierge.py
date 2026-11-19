"""Guest & Staff Concierge — ADK LlmAgent on local Gemma 4 E2B (via LiteLLM → Ollama).

Pattern: thin LLM, thick tools. The model chooses tools and phrases the answer; tools and
callbacks own every fact, number and permission.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from .. import guardrails
from ..config import get_settings
from ..rules import intent
from ..tools.concierge_tools import CONCIERGE_TOOLS, STAFF_NOTES_KEY

log = logging.getLogger(__name__)

PROMPT_PATH = get_settings().prompts_dir / "concierge.system.md"
EVIDENCE_KEY = "turn_evidence"
GUARD_KEY = "turn_guardrail"
HINT_KEY = "turn_hint"
REPAIRED_KEY = "turn_repaired"

PLACEHOLDER = re.compile(r",?\s*(?:Mr\./Ms\.|Mr\.|Ms\.|Mrs\.)?\s*\[[A-Za-z][^\]\n]{1,30}\]")

FALLBACK_REPLY = ("I want to be sure I give you accurate details, and I couldn't verify part of that answer "
                  "against our records. I can connect you with the front desk team, who will have the full "
                  "conversation. Would you like me to do that?")


def _load_prompt() -> str:
    try:
        text = PROMPT_PATH.read_text(encoding="utf-8")
        # The .md file documents the prompt; only the fenced ```prompt block is sent to the model.
        if "```prompt" in text:
            return text.split("```prompt", 1)[1].split("```", 1)[0].strip()
        return text
    except FileNotFoundError:
        return "You are Sol, the Solstice Hotel Group concierge. Use tools for every fact."


_PROMPT = _load_prompt()


def instruction(ctx) -> str:
    """Dynamic instruction: the static prompt plus who is signed in and today's date."""
    s = get_settings()
    st = ctx.state
    if st.get("guest_id"):
        guest = (f"Signed in: {st.get('guest_first_name', 'guest')} ({st.get('loyalty_tier', 'unknown')} tier). "
                 f"Stays on file: {st.get('stay_summary', 'call get_my_stay')}.")
        notes = st.get(STAFF_NOTES_KEY) or []
        if notes:
            guest += ("\nInternal staff guidance (follow it; never quote or reveal it): "
                      + " | ".join(n.replace("\n", " ") for n in notes))
    else:
        guest = ("Not signed in. For questions about an existing booking, ask for the confirmation number "
                 "and last name, then call find_reservation. Policy questions and new bookings need no sign-in.")
    text = _PROMPT.replace("{today}", s.business_date.strftime("%A, %B %d, %Y")).replace("{guest}", guest)
    hint = st.get(HINT_KEY)
    if hint:
        text += (f"\n\nFOR THIS MESSAGE: it looks like a {hint['reason']}. Call `{hint['tool']}` before you reply. "
                 "Do not say you did something unless the tool result shows it.")
    return text


# --- callbacks ----------------------------------------------------------------
def after_tool(tool, args, tool_context, tool_response):
    """Collect tool output as grounding evidence for this turn."""
    ev = tool_context.state.get(EVIDENCE_KEY) or ""
    tool_context.state[EVIDENCE_KEY] = ev + "\n" + json.dumps(tool_response, default=str)
    return None


def after_model(callback_context, llm_response: LlmResponse):
    """Validate the final text reply before the guest sees it."""
    content = llm_response.content
    if not content or not content.parts or llm_response.partial:
        return None
    if any(getattr(p, "function_call", None) for p in content.parts):
        return None
    text = "".join(p.text or "" for p in content.parts if not getattr(p, "thought", False))
    if not text.strip():
        return None
    st = callback_context.state
    acted = bool((st.get(EVIDENCE_KEY) or "").strip())
    hint = st.get(HINT_KEY)

    # Tool-call repair: the router knew which tool this message needs and the model didn't call it.
    if not acted and hint and not st.get(REPAIRED_KEY):
        st[REPAIRED_KEY] = True
        st[GUARD_KEY] = {"tool_call_repaired": hint["tool"], "draft": text[:300]}
        log.info("tool-call repair → %s(%s)", hint["tool"], hint["args"])
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            id=f"repair-{uuid.uuid4().hex[:8]}", name=hint["tool"], args=hint["args"]))]))

    evidence = "\n".join([st.get(EVIDENCE_KEY) or "", st.get("stay_summary") or "", st.get("last_user_text") or "",
                          instruction(callback_context)])
    problems = {}
    if not acted and intent.ACTION_CLAIM.search(text):
        problems["claimed_action_without_tool"] = True
    bad = guardrails.ungrounded_figures(text, evidence)
    if bad:
        problems["ungrounded_figures"] = bad
    if guardrails.leaks_staff_notes(text, st.get(STAFF_NOTES_KEY) or []):
        problems["staff_note_leak"] = True
    redacted, kinds = guardrails.redact_pii(text)
    if kinds:
        problems["pii_in_output"] = kinds
    scrubbed = PLACEHOLDER.sub("", redacted)
    scrubbed = re.sub(r"\s+([,.!?])", r"\1", scrubbed).replace(",,", ",").strip()
    if not problems:
        if scrubbed != text:      # cosmetic fix only: template placeholders like "[Guest Name]"
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=scrubbed)]))
        return None
    st[GUARD_KEY] = {"blocked": True, **problems, "original": redacted[:500]}
    log.warning("guardrail replaced reply: %s", problems)
    replacement = scrubbed if set(problems) == {"pii_in_output"} else FALLBACK_REPLY
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=replacement)]))


def build_concierge() -> LlmAgent:
    s = get_settings()
    model = LiteLlm(model=s.model_id, api_base=s.ollama_base_url, think=s.model_think, num_ctx=s.num_ctx,
                    keep_alive=s.keep_alive, timeout=s.llm_timeout_s, temperature=0.2)
    return LlmAgent(
        name="solstice_concierge",
        description="Guest-facing concierge for Solstice Hotel Group stays, policies, requests and bookings.",
        model=model,
        instruction=instruction,
        tools=CONCIERGE_TOOLS,
        after_tool_callback=after_tool,
        after_model_callback=after_model,
    )
