"""Run the group-booking workflow on every sample inquiry (plus one free-text email) and write
Markdown proposals/transcripts to agents/transcripts/group/.

    uv run python scripts/run_group.py [--base http://localhost:8080]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[2] / "agents" / "transcripts" / "group"

SAMPLE_EMAIL = """From: Jordan Ellis <jordan.ellis@northwindrobotics.com>
Phone: 615-555-0199
Subject: Team offsite in Nashville

Hi Solstice team,
We're planning our engineering offsite in Nashville from October 20 to October 22, 2026 and need
16 Standard King rooms. We'd also like a meeting room for 40 people with a projector.
Our budget is around $190 per room per night - is a 10% group discount possible?
Thanks, Jordan (Northwind Robotics)"""


def _headers() -> dict:
    tok = os.environ.get("SOLSTICE_SERVICE_TOKEN")
    return {"x-service-token": tok} if tok else {}


def _stream(c: httpx.Client, url: str, payload: dict | None = None) -> tuple[list, dict | None]:
    steps, result, kind = [], None, None
    with c.stream("POST", url, json=payload, headers=_headers(), timeout=300) as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1])
                if kind == "step":
                    steps.append(data)
                elif kind == "result":
                    result = data
                elif kind == "error":
                    raise RuntimeError(data)
    return steps, result


def render(iid: str, steps: list, res: dict) -> str:
    d = res["decision"]
    p = d.get("pricing") or {}
    out = [f"# {iid} · {d.get('company') or 'Email intake'} → **{res['status'].replace('_', ' ')}**"
           f"{'  🔥 urgent' if res['priority'] == 'urgent' else ''}", "",
           f"*{res['proposal_id']} · end-to-end {res['latency_ms']} ms · "
           f"workflow path: {' → '.join(s['node'] for s in steps)}*", "", "## Agent trace", ""]
    out += [f"1. **{t['node']}**: {t['summary']}" for t in res["trace"]]
    out += ["", "## Rule checks", "", "| Check | Result | Detail |", "|---|---|---|"]
    icon = {"pass": "✅", "fail": "🚩", "warn": "⚠️", "info": "ℹ️"}
    out += [f"| {c['label']} | {icon[c['status']]} {c['severity']} | {c['detail']} |" for c in d["checks"]]
    if d.get("missing"):
        out += ["", "## Missing information (blocking)", ""] + [f"- {m['question']}" for m in d["missing"]]
    if p:
        out += ["", "## Pricing", "", f"Base ${p['base_rate']:.2f} · effective ceiling {p['effective_ceiling_pct']:g}% "
                f"({p['ceiling_reason']}) · {p['rooms']} rooms × {p['nights']} nights", "",
                "| Option | Discount | Rate | Subtotal | Auto-approvable | Within budget |", "|---|---|---|---|---|---|"]
        out += [f"| {o['label']} | {o['discount_pct']:g}% | ${o['rate']:.2f} | ${o['subtotal']:,.2f} | "
                f"{'yes' if o['auto_approvable'] else 'GM review'} | {o['within_budget']} |" for o in p["options"]]
    if d.get("alternatives"):
        out += ["", "## Booking Rescue alternatives", ""]
        out += [f"- **{a['label']}**: {a['rooms']} × {a['room_type']} {a['arrival']}→{a['departure']} at "
                f"${a['rate']:.2f} ({a['discount_pct']:g}%) · {'confirmable today' if a.get('auto_approvable') else 'needs approval'}"
                for a in d["alternatives"]]
    note = res.get("cover_note") or {}
    out += ["", "## Draft to client (LLM-written, numerically verified)", "", f"**Subject:** {note.get('subject')}", "",
            "> " + (note.get("body") or "").replace("\n", "\n> "), ""]
    return "\n".join(out)


def main(base: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(base_url=base) as c:
        inquiries = c.get("/v1/group/inquiries", headers=_headers()).json()
        jobs = [(i["inquiry_id"], f"/v1/group/inquiries/{i['inquiry_id']}/run", None) for i in inquiries
                if i["received_via"] == "web_portal"]
        jobs.append(("EMAIL", "/v1/group/intake/email", {"email": SAMPLE_EMAIL}))
        for iid, url, payload in jobs:
            steps, res = _stream(c, url, payload)
            name = res["decision"]["inquiry_id"] if iid == "EMAIL" else iid
            (OUT / f"{name}.md").write_text(render(name, steps, res), encoding="utf-8")
            flags = ", ".join(f["id"] for f in res["decision"]["flags"]) or "—"
            rows.append(f"| [{name}]({name}.md) | {res['decision'].get('company')} | {res['status']} | {flags} | "
                        f"{len(res['decision'].get('alternatives') or [])} | {res['latency_ms']} |")
            print(f"{name}: {res['status']:<20} flags={flags:<40} {res['latency_ms']} ms")
    (OUT / "README.md").write_text(
        "# Group booking workflow runs\n\n| Inquiry | Client | Outcome | Flags | Rescue options | ms |\n"
        "|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    main(ap.parse_args().base)
