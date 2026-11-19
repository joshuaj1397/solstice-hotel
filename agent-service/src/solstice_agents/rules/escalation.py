"""Escalation matrix (Policy 15) + deterministic risk triage on raw guest input.

Triage runs BEFORE the LLM. Safety / medical / legal messages never depend on a 2B model
noticing them: they short-circuit to a scripted reply and an immediate hand-off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

SLA = {"immediate": timedelta(minutes=15), "same_day": timedelta(hours=4), "standard": timedelta(hours=24)}


@dataclass(frozen=True)
class Route:
    category: str
    severity: str
    route_to: str
    policy_refs: tuple[int, ...]


MATRIX: dict[str, Route] = {
    "safety":        Route("safety", "immediate", "General Manager + Regional Security", (15,)),
    "medical":       Route("medical", "immediate", "General Manager + Regional Security", (15,)),
    "legal":         Route("legal", "same_day", "General Manager", (15,)),
    "media":         Route("media", "same_day", "Manager on Duty / AGM", (15,)),
    "dispute":       Route("dispute", "same_day", "Manager on Duty / AGM", (7, 15)),
    "refund":        Route("refund", "same_day", "Manager on Duty / AGM", (5, 7, 15)),
    "comp_over_limit": Route("comp_over_limit", "same_day", "Manager on Duty / AGM", (7, 15)),
    "vip":           Route("vip", "same_day", "General Manager", (15,)),
    "group_block":   Route("group_block", "standard", "Group Sales + General Manager", (13,)),
    "policy_gap":    Route("policy_gap", "standard", "Front Desk", (15,)),
    "guest_request": Route("guest_request", "standard", "Front Desk", (15,)),
}


def route_for(category: str, gm_name: str | None = None) -> Route:
    r = MATRIX.get(category, MATRIX["guest_request"])
    if gm_name and "General Manager" in r.route_to:
        return Route(r.category, r.severity, r.route_to.replace("General Manager", f"General Manager ({gm_name})"),
                     r.policy_refs)
    return r


# Ordered: first match wins. Patterns are deliberately broad; a false positive costs a
# human glance, a false negative on a safety message is unacceptable.
_TRIAGE: list[tuple[str, re.Pattern]] = [
    ("safety", re.compile(
        r"\b(gun|weapon|knife|threat(en(ed|ing)?)?|assault(ed)?|attack(ed)?|police|911|fire\b|smoke alarm|"
        r"break[- ]?in|stalk(ing|ed)?|harass(ed|ing|ment)?|unsafe|danger(ous)?|bomb|fight(ing)?|violen(ce|t)|"
        r"intruder|someone in my room|being followed)", re.I)),
    ("medical", re.compile(
        r"\b(ambulance|chest pains?|can'?t breathe|unconscious|seizure|bleeding|overdose|allergic reaction|"
        r"anaphyla\w*|heart attack|stroke|injur(ed|y)|fell (down|over|and)|fainted|medical emergency|"
        r"need a doctor|hospital\b|sick(?! of)|poison(ed|ing)?)", re.I)),
    ("legal", re.compile(r"\b(lawyer|attorney|sue|suing|lawsuit|legal action|court\b|discriminat\w*|"
                         r"ada complaint)", re.I)),
    ("media", re.compile(r"\b(journalist|reporter|press inquiry|news story|media inquiry)", re.I)),
]

SCRIPTED = {
    "safety": ("If anyone is in immediate danger, please call 911 now. I've alerted the General Manager and "
               "Regional Security, and they will contact you right away. Case {case_id}."),
    "medical": ("If this is a medical emergency, please call 911 now. I've alerted the General Manager and the "
                "on-site team so someone can help you right away. Case {case_id}."),
    "legal": ("I've passed this to the General Manager with the full details of our conversation, so you won't "
              "need to repeat anything. You'll hear back today. Case {case_id}."),
    "media": ("Thanks for reaching out. Media inquiries go to our management team, and I've sent them your "
              "message. They'll respond today. Case {case_id}."),
}


def triage(text: str) -> str | None:
    for category, pattern in _TRIAGE:
        if pattern.search(text or ""):
            return category
    return None
