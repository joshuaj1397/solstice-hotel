"""Deterministic intent router for the concierge.

Small models are good at phrasing and weak at reliably deciding to act. Measured on the
sample scenarios, Gemma 4 E2B skipped the needed tool in 6 of 14 turns (thinking on) and
10 of 14 (thinking off), sometimes claiming an action it never took ("I am submitting this
as a dispute...", "case number [Case Number]").

This router recognises the unambiguous asks and pre-computes the tool call with arguments
parsed in code. The agent sees it as a hint; if it still answers without acting, the
after-model callback swaps its reply for exactly this call (tool-call repair).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

_TIME = re.compile(r"\b(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))|\b(?:at|by|until|till)\s+(\d{1,2}(?::\d{2})?)\b|\b(noon)\b", re.I)
_MONEY = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")


@dataclass
class Intent:
    tool: str
    args: dict = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _time(text: str) -> str:
    m = _TIME.search(text)
    return next((g for g in m.groups() if g), "") if m else ""


def _issue_type(t: str) -> str:
    if re.search(r"\b(charge[ds]?|bill|folio|invoice|dispute|overcharg\w*|minibar)\b", t):
        return "charge_dispute"
    if re.search(r"\b(comp|free night)\b", t):
        return "comp_night"
    if re.search(r"\b(refund|money back|credit|reimburs\w*)\b", t):
        return "refund_request"
    return "stay_problem"


RULES: list[tuple[str, re.Pattern]] = [
    ("policy", re.compile(r"\bpolic(y|ies)\b|\brules?\b", re.I)),
    ("cancel", re.compile(r"\bcancel\w*", re.I)),
    ("problem", re.compile(r"\b(dispute|overcharg\w*|charged|charge on|refund|money back|complain\w*|noisy|noise|dirty|"
                           r"filthy|broken|didn'?t work|not working|terrible|awful|unhappy|disappoint\w*|compensat\w*|"
                           r"never (touched|used|ordered))\b", re.I)),
    ("late_checkout", re.compile(r"\blate check ?-?out\b|\bcheck ?-?out (later|at|by|until)\b|\bstay (later|until)\b|"
                                 r"\binstead of 11\b", re.I)),
    ("early_checkin", re.compile(r"\bearly check ?-?in\b|\bcheck ?-?in early\b|\barrive early\b|\b(land|landing|lands) at\b", re.I)),
    ("upgrade", re.compile(r"\bupgrade\b", re.I)),
    ("amenity", re.compile(r"\b(rollaway|crib|cot|hypoallergenic|feather|extra (towels?|pillows?|bed)|champagne|"
                           r"turndown|connecting rooms?|ground floor|high floor)\b", re.I)),
    ("person", re.compile(r"\b(speak|talk) (to|with) (a|an|someone|human|person|manager|agent)\b|\breal person\b", re.I)),
    ("faq", re.compile(r"\b(pets?|dogs?|cats?|service animal|smok\w*|vap\w*|parking|valet|lost and found|left (my|behind)|"
                       r"check ?-?in time|check ?-?out time|what time|deposit|incidental|extra guests?|no[- ]?show|"
                       r"photo id)\b", re.I)),
    ("my_stay", re.compile(r"\bmy (reservation|booking|stay|points|tier|status|loyalty)\b|\bhow many points\b", re.I)),
]


def detect(text: str) -> Intent | None:
    t = text or ""
    hits = {name for name, rx in RULES if rx.search(t)}
    if not hits:
        return None
    if "policy" in hits and "problem" not in hits:
        return Intent("lookup_policy", {"question": t}, "explicit policy question")
    if "cancel" in hits:
        return Intent("cancellation_options", {}, "cancellation")
    if "problem" in hits:
        m = _MONEY.search(t)
        return Intent("report_problem", {
            "issue_type": _issue_type(t.lower()), "description": t[:500],
            "reported_during_stay": bool(re.search(r"\b(told|reported|mentioned|called)\b.*\b(desk|housekeeping|staff|"
                                                   r"front|during)\b", t, re.I)),
            "amount_usd": float(m.group(1)) if m else 0.0}, "complaint / dispute / refund")
    for kind in ("late_checkout", "early_checkin", "upgrade"):
        if kind in hits:
            return Intent("request_stay_change", {"request": kind, "time": _time(t)}, kind.replace("_", " "))
    if "amenity" in hits:
        return Intent("request_stay_change", {"request": "amenity", "details": t[:200]}, "amenity request")
    if "person" in hits:
        return Intent("escalate_to_staff", {"reason": f"Guest asked for a person: {t[:200]}"}, "asked for a human")
    if "faq" in hits:
        return Intent("lookup_policy", {"question": t}, "policy topic")
    if "my_stay" in hits:
        return Intent("get_my_stay", {}, "stay details")
    return None


# Replies that claim an action happened. Without a tool call this turn, they are false.
ACTION_CLAIM = re.compile(
    r"\bI('ve| have| just)? ?(submitted|logged|created|escalated|placed|confirmed|requested|cancelled|canceled|"
    r"sent|filed|opened|forwarded)\b|\bI('m| am) (submitting|creating|escalating|logging|filing|opening|forwarding)\b|"
    r"\bcase (number|id)\b|\[[A-Z][a-z]+ ?[A-Z]?[a-z]*\]", re.I)
