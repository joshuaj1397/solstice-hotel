"""Guardrails that don't depend on the model behaving.

  redact_pii        — runs on every guest message BEFORE the model, logs, or the DB see it
  ungrounded_figures— every $ amount, % and clock time in a reply must appear in tool output,
                      policy text, or the guest's own words; otherwise the reply is replaced
  leaks_staff_notes — internal front-desk notes may guide the agent, never be quoted to a guest
  injection_score   — cheap heuristics for prompt-injection attempts (logged, and the agent's
                      tools are session-scoped anyway, so injection can't reach other guests)
"""

from __future__ import annotations

import re

_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CVV = re.compile(r"\b(cvv|cvc|security code)\D{0,10}\d{3,4}\b", re.I)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Mask payment cards (Luhn-checked), CVVs, SSNs, emails and phone numbers."""
    kinds: list[str] = []

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            kinds.append("card")
            return f"[card ending {digits[-4:]} removed]"
        return m.group()

    out = _CARD.sub(card, text)
    if _CVV.search(out):
        kinds.append("cvv")
        out = _CVV.sub("[security code removed]", out)
    if _SSN.search(out):
        kinds.append("ssn")
        out = _SSN.sub("[ssn removed]", out)
    if _EMAIL.search(out):
        kinds.append("email")
        out = _EMAIL.sub(lambda m: m.group()[0] + "***@" + m.group().split("@")[1], out)
    if _PHONE.search(out):
        kinds.append("phone")
        out = _PHONE.sub(lambda m: "***-***-" + re.sub(r"\D", "", m.group())[-4:], out)
    return out, kinds


# --- numeric grounding --------------------------------------------------------
_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s?([ap])\.?m\.?\b", re.I)


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return s
    return f"{f:.2f}".rstrip("0").rstrip(".")


def figures(text: str) -> set[str]:
    out: set[str] = set()
    for m in _MONEY.finditer(text or ""):
        out.add("$" + _norm_num(m.group(1)))
    for m in _PCT.finditer(text or ""):
        out.add(_norm_num(m.group(1)) + "%")
    for m in _CLOCK.finditer(text or ""):
        h, mm, ap = int(m.group(1)), m.group(2) or "00", m.group(3).lower()
        out.add(f"{h}:{mm}{ap}")
    return out


def _corpus_numbers(corpus: str) -> set[str]:
    """Every bare number in the evidence also counts as a grounded $ / % value."""
    nums = {_norm_num(n) for n in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", corpus or "")}
    return {"$" + n for n in nums} | {n + "%" for n in nums} | figures(corpus)


def ungrounded_figures(reply: str, evidence: str) -> list[str]:
    allowed = _corpus_numbers(evidence)
    # Clock times in evidence may be written "3:00 PM" or "15:00"; normalise both.
    for m in re.finditer(r"\b(\d{1,2}):(\d{2})\b", evidence or ""):
        h, mm = int(m.group(1)), m.group(2)
        if h <= 23:
            allowed.add(f"{h % 12 or 12}:{mm}{'p' if h >= 12 else 'a'}")
    return sorted(f for f in figures(reply) if f not in allowed)


# --- staff-note leakage --------------------------------------------------------
def _shingles(text: str, n: int = 7) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9$%]+", (text or "").lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def leaks_staff_notes(reply: str, staff_notes: list[str]) -> bool:
    r = _shingles(reply)
    return any(r & _shingles(note) for note in staff_notes if note)


_INJECTION = re.compile(
    r"ignore (all|any|previous|prior) (instructions|rules)|system prompt|you are now|developer mode|"
    r"act as (an? )?(admin|manager|staff)|reveal (your|the) (prompt|instructions)|other guests?'? (data|info|reservation)",
    re.I)


def injection_score(text: str) -> int:
    return len(_INJECTION.findall(text or ""))
