"""Schema migrations + validated CSV ingestion. Run as a one-shot job, never by the API.

    uv run solstice-migrate            # apply migrations, seed if empty
    uv run solstice-migrate --reseed   # wipe data tables and reload the CSVs
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from . import secrets
from .config import Settings, get_settings

log = logging.getLogger("solstice.migrate")

INVENTORY_START = date(2026, 6, 1)
INVENTORY_END = date(2027, 6, 30)

# Approximate downtown coordinates (public geography, used to rank nearby alternatives).
CITY_COORDS = {
    "Chicago": (41.8781, -87.6298), "Austin": (30.2672, -97.7431), "Denver": (39.7392, -104.9903),
    "Nashville": (36.1627, -86.7816), "Tampa": (27.9506, -82.4572), "Phoenix": (33.4484, -112.0740),
    "Charlotte": (35.2271, -80.8431), "Sacramento": (38.5816, -121.4944),
    "Columbus": (39.9612, -82.9988), "Providence": (41.8240, -71.4128),
}

# Human-reviewed extraction of the free-text property notes into structured rules.
# `anchor` must still appear in the source note; if the note changes, the rule is flagged
# for re-review instead of silently drifting. Weekday numbers: Mon=0 … Sun=6.
PROPERTY_RULES: dict[str, list[dict]] = {
    "SOL-CHI": [dict(rule_type="lead_time", severity="review", anchor="2+ weeks lead time",
                     params={"min_rooms_exclusive": 25, "min_days": 14},
                     description="Group requests over 25 rooms need at least 14 days of lead time.")],
    "SOL-DEN": [dict(rule_type="seasonal_discount_cap", severity="review", anchor="reduced group discount ceiling of 8%",
                     params={"months": [12, 1, 2], "weekdays": [3, 4, 5, 6], "cap_pct": 8, "label": "ski-season weekend"},
                     description="Ski-season weekends (Dec–Feb, Thu–Sun nights) cap group discounts at 8%.")],
    "SOL-NSH": [dict(rule_type="weekend_preference", severity="advisory", anchor="weekday group blocks preferred",
                     params={"weekdays": [4, 5]},
                     description="High weekend leisure demand; weekday group blocks are preferred.")],
    "SOL-TPA": [dict(rule_type="selling_point", severity="advisory", anchor="dedicated group check-in lane",
                     params={}, description="Dedicated group check-in lane; popular for sports-team travel.")],
    "SOL-PHX": [dict(rule_type="seasonal_rate_advisory", severity="advisory", anchor="Rate drops ~20% June-Aug",
                     params={"months": [6, 7, 8], "approx_drop_pct": 20},
                     description="Off-peak June–August: seasonal rates run about 20% lower. Revenue management "
                                 "must confirm the seasonal rate before it is quoted.")],
    "SOL-CLT": [dict(rule_type="selling_point", severity="advisory", anchor="New property",
                     params={}, description="New property (opened 2025), building its group-sales track record.")],
    "SOL-SAC": [dict(rule_type="seasonal_discount_cap", severity="review", anchor="reduced discount ceiling of 8%",
                     params={"months": [1, 2, 3, 4, 5], "weekdays": [0, 1, 2, 3, 4], "cap_pct": 8,
                             "label": "legislature-session weekday"},
                     description="State-legislature session weeks (Jan–May weekday nights) cap group discounts at 8%.")],
    "SOL-CMH": [dict(rule_type="youth_insurance_required", severity="condition", anchor="insurance certificate",
                     params={"event_keywords": ["youth", "student", "school", "band", "minor"]},
                     description="Youth groups must have an insurance certificate on file before confirmation.")],
    "SOL-PVD": [dict(rule_type="route_over_rooms", severity="review", anchor="routed to Boston-area sister property",
                     params={"max_rooms": 15, "route_to": "Boston-area sister property"},
                     description="Blocks over 15 rooms should be routed to the Boston-area sister property.")],
}

BLACKOUT_REASONS = {"SOL-AUS": "SXSW week — hard blackout, no group holds regardless of discount"}

POLICY_KEYWORDS = {
    1: "checkin check in early arrival checkout check out late departure time",
    2: "cancel cancellation refund change modify reservation 72 hours penalty fee",
    3: "advance purchase prepaid nonrefundable non-refundable refund change weather flight illness insurance",
    4: "no show noshow missed arrival didn't arrive charge first night",
    5: "complaint problem noise dirty broken refund credit comp compensation service recovery unhappy",
    6: "loyalty member tier silver gold platinum upgrade benefits points perks late checkout",
    7: "comp compensation credit waive fee minibar parking manager approval goodwill",
    8: "pet dog cat animal service animal emotional support ADA",
    9: "extra guest rollaway cot bed kids children occupancy",
    10: "smoking smoke vape vaping e-cigarette cigarette fee",
    11: "lost found forgot left behind item ship shipping",
    12: "parking valet car garage self-park",
    13: "group block event wedding conference rooms discount sales",
    14: "ID identification deposit incidental hold cash card check-in name",
    15: "escalate manager dispute safety security police media emergency threat",
}


def _admin_conninfo(s: Settings) -> str:
    cred = secrets.admin_credentials(s)
    return make_conninfo(host=s.db_host, port=s.db_port, dbname=s.db_name,
                         user=cred.user, password=cred.password, application_name="solstice-migrate")


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
def apply_migrations(conn: psycopg.Connection, migrations_dir: Path) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations "
                 "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
    conn.commit()
    done = {r[0] for r in conn.execute("SELECT version FROM public.schema_migrations")}
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.stem in done:
            continue
        log.info("applying %s", path.name)
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("RESET ROLE")
            conn.execute("INSERT INTO public.schema_migrations (version) VALUES (%s)", (path.stem,))
        applied.append(path.stem)
    return applied


def ensure_login_user(conn: psycopg.Connection, user: str, password: str, group: str) -> None:
    """Static login users (Vault KV mode). In dynamic mode Vault creates users itself."""
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
    stmt = "ALTER ROLE {} WITH LOGIN PASSWORD {}" if exists else "CREATE ROLE {} WITH LOGIN PASSWORD {}"
    conn.execute(sql.SQL(stmt).format(sql.Identifier(user), sql.Literal(password)))
    conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(user)))
    conn.commit()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------
def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()} for row in csv.DictReader(f)]


def _nz(v: str | None) -> str | None:
    return v if v not in (None, "") else None


def _int(v: str | None) -> int | None:
    return int(v) if _nz(v) is not None else None


def _yn(v: str | None) -> bool | None:
    return None if _nz(v) is None else v.upper().startswith("Y")


def _date(v: str | None) -> date | None:
    return date.fromisoformat(v) if _nz(v) else None


class Seeder:
    def __init__(self, conn: psycopg.Connection, s: Settings):
        self.c = conn
        self.s = s
        self.issues = 0

    def issue(self, source: str, key: str, field: str, raw, issue: str, action: str) -> None:
        self.issues += 1
        self.c.execute(
            "INSERT INTO core.data_quality_issues (source_file, record_key, field, raw_value, issue, action) "
            "VALUES (%s,%s,%s,%s,%s,%s)", (source, key, field, None if raw is None else str(raw), issue, action))

    # -- properties ----------------------------------------------------------
    def properties(self) -> None:
        src = "solstice-properties.csv"
        for r in _read_csv(self.s.data_dir / src):
            code = r["property_code"]
            lat, lon = CITY_COORDS.get(r["city"], (None, None))
            self.c.execute(
                """INSERT INTO core.properties (property_code, property_name, city, state, market_type,
                     total_rooms, accessible_rooms, meeting_space_sqft, max_meeting_capacity,
                     group_auto_approve_max_rooms, max_discount_auto_approve_pct, general_manager,
                     notes, latitude, longitude)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (code, r["property_name"], r["city"], r["state"], r["market_type"], int(r["total_rooms"]),
                 int(r["accessible_rooms"]), _int(r["meeting_space_sqft"]), _int(r["max_meeting_capacity"]),
                 int(r["group_block_auto_approve_max_rooms"]), float(r["max_discount_auto_approve_pct"]),
                 r["general_manager"], r["notes"], lat, lon))

            room_types = [
                ("Standard King", 1, "standard_king_rooms", "base_rate_standard"),
                ("Standard Double", 1, "standard_double_rooms", "base_rate_standard"),
                ("Accessible King", 1, "accessible_rooms", "base_rate_standard"),
                ("Deluxe King", 2, "deluxe_king_rooms", "base_rate_deluxe"),
                ("Suite", 3, "suite_rooms", "base_rate_suite"),
            ]
            counted = 0
            for name, cls, count_col, rate_col in room_types:
                count = int(r[count_col])
                counted += count
                raw_rate = _nz(r[rate_col])
                rate = float(raw_rate) if raw_rate else None
                if rate is not None and rate <= 0:
                    self.issue(src, code, rate_col, raw_rate, f"non-positive rate for {name}",
                               "quarantined: rate set to NULL; agent will not quote it and escalates instead")
                    rate = None
                self.c.execute(
                    "INSERT INTO core.property_room_types VALUES (%s,%s,%s,%s,%s,%s)",
                    (code, name, cls, count, rate, rate_col + (" (accessible priced as standard)" if name == "Accessible King" else "")))
            if counted != int(r["total_rooms"]):
                self.issue(src, code, "total_rooms", r["total_rooms"],
                           f"room-type counts sum to {counted}", "inventory built from room-type counts")

            bo = r["blackout_dates"]
            if bo and bo.lower() != "none scheduled":
                for span in bo.split(";"):
                    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\s*", span)
                    if not m:
                        self.issue(src, code, "blackout_dates", span, "unparseable blackout span", "ignored — needs review")
                        continue
                    self.c.execute("INSERT INTO core.property_blackouts VALUES (%s,%s,%s,%s)",
                                   (code, m.group(1), m.group(2), BLACKOUT_REASONS.get(code, "Property blackout")))

            for rule in PROPERTY_RULES.get(code, []):
                if rule["anchor"].lower() not in r["notes"].lower():
                    self.issue(src, code, "notes", r["notes"], f"rule '{rule['rule_type']}' anchor not found",
                               "rule NOT loaded — property notes changed, re-review extraction")
                    continue
                self.c.execute(
                    "INSERT INTO core.property_rules (property_code, rule_type, severity, params, description, source_text) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (code, rule["rule_type"], rule["severity"], Jsonb(rule["params"]), rule["description"], r["notes"]))

    # -- guests & reservations -------------------------------------------------
    def guests(self) -> None:
        src = "solstice-guest-profiles.csv"
        seen: dict[str, dict] = {}
        names: dict[tuple, set] = {}
        for r in _read_csv(self.s.data_dir / src):
            gid = r["guest_id"]
            profile = {k: r[k] for k in ("first_name", "last_name", "email", "phone", "loyalty_tier")}
            if gid in seen and seen[gid] != profile:
                self.issue(src, gid, "profile", None, "conflicting profile rows for one guest_id", "first row kept")
            if gid not in seen:
                seen[gid] = profile
                self.c.execute(
                    "INSERT INTO core.guests VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (gid, r["first_name"], r["last_name"], _nz(r["email"]), _nz(r["phone"]),
                     r["loyalty_tier"] or "None", _int(r["loyalty_points"]) or 0, _int(r["member_since"]),
                     _yn(r["marketing_opt_in"]) or False))
            names.setdefault((r["first_name"].lower(), r["last_name"].lower()), set()).add(gid)

            ci, co = _date(r["check_in_date"]), _date(r["check_out_date"])
            nights = _int(r["total_nights"])
            if ci and co and nights != (co - ci).days:
                self.issue(src, r["reservation_id"], "total_nights", nights,
                           f"dates imply {(co - ci).days} nights", "dates treated as authoritative")
            if r["reservation_status"] == "Checked-in" and ci and ci > self.s.business_date:
                self.issue(src, r["reservation_id"], "reservation_status", r["reservation_status"],
                           f"status Checked-in but arrival {ci} is after business date {self.s.business_date}",
                           "kept as exported; PMS is the source of truth for stay status")
            self.c.execute(
                """INSERT INTO core.reservations (reservation_id, guest_id, property_code, check_in, check_out,
                     room_type, rate_plan, nightly_rate, total_nights, status, payment_last4,
                     special_requests, internal_notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (r["reservation_id"], gid, r["property_code"], ci, co, r["room_type"], r["rate_plan"],
                 float(r["nightly_rate"] or 0), nights, r["reservation_status"], _nz(r["payment_method_last4"]),
                 _nz(r["special_requests"]), _nz(r["internal_notes"])))
        for (fn, ln), ids in names.items():
            if len(ids) > 1:
                self.issue(src, ",".join(sorted(ids)), "name", f"{fn} {ln}",
                           "distinct guests share a name", "agent verifies by confirmation number + last name, never name alone")

    # -- inventory calendar ---------------------------------------------------
    def inventory(self) -> None:
        self.c.execute(
            """INSERT INTO ops.inventory_nights (property_code, room_type, stay_date, capacity)
               SELECT rt.property_code, rt.room_type, d::date, rt.room_count
                 FROM core.property_room_types rt
                 CROSS JOIN generate_series(%s::date, %s::date, interval '1 day') d""",
            (INVENTORY_START, INVENTORY_END))
        # Occupied nights from active reservations in the export.
        self.c.execute(
            """WITH nights AS (
                 SELECT r.property_code, r.room_type, d::date AS stay_date, count(*) AS n
                   FROM core.reservations r
                   CROSS JOIN LATERAL generate_series(r.check_in, r.check_out - 1, interval '1 day') d
                  WHERE r.status IN ('Confirmed', 'Checked-in')
                  GROUP BY 1, 2, 3)
               UPDATE ops.inventory_nights i SET sold = i.sold + nights.n
                 FROM nights
                WHERE (i.property_code, i.room_type, i.stay_date) = (nights.property_code, nights.room_type, nights.stay_date)""")

    # -- policies --------------------------------------------------------------
    def policies(self) -> None:
        path = next(self.s.data_dir.glob("*POLICY*.md"), None) or next(self.s.data_dir.glob("*polic*"))
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^(\d+)\.\s+([^\n]+)\n(.*?)(?=^\d+\.\s|\Z)", text, re.M | re.S):
            no = int(m.group(1))
            self.c.execute("INSERT INTO core.policy_sections (section_no, title, body, keywords) VALUES (%s,%s,%s,%s)",
                           (no, m.group(2).strip(), m.group(3).strip(), POLICY_KEYWORDS.get(no, "")))

    # -- group inquiries -------------------------------------------------------
    def inquiries(self) -> None:
        src = "solstice-group-inquiries.csv"
        for r in _read_csv(self.s.data_dir / src):
            iid = r["inquiry_id"]
            raw_rooms = _nz(r["rooms_requested"])
            rooms, approx = None, False
            if raw_rooms:
                m = re.search(r"\d+", raw_rooms)
                rooms = int(m.group()) if m else None
                approx = not raw_rooms.isdigit()
            self.c.execute(
                """INSERT INTO core.group_inquiries (inquiry_id, date_received, company_name, contact_name,
                     contact_email, contact_phone, event_type, preferred_property_code, alternate_property_ok,
                     arrival_date, departure_date, nights, rooms_requested_raw, rooms_requested,
                     rooms_approximate, room_type_preference, requested_discount_pct, stated_budget_per_night,
                     meeting_space_needed, meeting_capacity_needed, special_requests)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (iid, _date(r["date_received"]), r["company_name"], r["contact_name"], _nz(r["contact_email"]),
                 _nz(r["contact_phone"]), r["event_type"], _nz(r["preferred_property_code"]),
                 _yn(r["alternate_property_ok"]), _date(r["arrival_date"]), _date(r["departure_date"]),
                 _int(r["nights"]), raw_rooms, rooms, approx, _nz(r["room_type_preference"]),
                 float(r["requested_discount_pct"]) if _nz(r["requested_discount_pct"]) else None,
                 float(r["stated_budget_per_night"]) if _nz(r["stated_budget_per_night"]) else None,
                 _yn(r["meeting_space_needed"]), _int(r["meeting_capacity_needed"]), _nz(r["special_requests"])))
            if _nz(r.get("notes")):
                self.c.execute("INSERT INTO eval.group_inquiry_expectations VALUES (%s,%s)", (iid, r["notes"]))

    def run(self) -> int:
        self.properties()
        self.guests()
        self.inventory()
        self.policies()
        self.inquiries()
        return self.issues


DATA_TABLES = [
    "ops.guardrail_events", "ops.turn_metrics", "ops.funnel_events", "ops.group_proposals",
    "ops.escalation_messages", "ops.escalations", "ops.service_requests", "ops.holds",
    "ops.inventory_nights", "eval.group_inquiry_expectations", "core.group_inquiries",
    "core.policy_sections", "core.reservations", "core.guests", "core.property_rules",
    "core.property_blackouts", "core.property_room_types", "core.properties", "core.data_quality_issues",
]


def seed(conn: psycopg.Connection, s: Settings, reseed: bool = False) -> int | None:
    with conn.transaction():
        conn.execute("SET LOCAL ROLE solstice_owner")
        if reseed:
            conn.execute("TRUNCATE " + ", ".join(DATA_TABLES) + " RESTART IDENTITY CASCADE")
        elif conn.execute("SELECT count(*) FROM core.properties").fetchone()[0]:
            log.info("seed: data present, skipping (use --reseed to reload)")
            return None
        issues = Seeder(conn, s).run()
    log.info("seed: loaded CSVs with %d data-quality issues recorded", issues)
    return issues


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--reseed", action="store_true")
    p.add_argument("--create-static-users", action="store_true",
                   help="create LOGIN users from configured agent/staff credentials (Vault KV mode)")
    args = p.parse_args()
    s = get_settings()
    with psycopg.connect(_admin_conninfo(s)) as conn:
        applied = apply_migrations(conn, s.migrations_dir)
        log.info("migrations applied: %s", applied or "none (up to date)")
        if args.create_static_users:
            res = secrets.resolve(s) if s.vault_mode != "off" else None
            agent = res.agent_db if res else secrets.DbCredential(s.agent_db_user, s.agent_db_password)
            staff = res.staff_db if res else secrets.DbCredential(s.staff_db_user, s.staff_db_password)
            ensure_login_user(conn, agent.user, agent.password, "solstice_agent")
            ensure_login_user(conn, staff.user, staff.password, "solstice_staff")
            log.info("static login users ensured: %s, %s", agent.user, staff.user)
        seed(conn, s, reseed=args.reseed)


if __name__ == "__main__":
    main()
