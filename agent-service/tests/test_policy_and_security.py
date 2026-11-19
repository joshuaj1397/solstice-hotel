import asyncio
from datetime import date, datetime

import psycopg
import pytest

from solstice_agents import guardrails, services
from solstice_agents.config import get_settings
from solstice_agents.rules import escalation, stay

NOW = datetime(2026, 7, 12, 12, 0)


# --- least privilege -------------------------------------------------------------
async def test_agent_role_cannot_read_raw_pii(db):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await db.fetch("SELECT email FROM core.guests")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await db.fetch("SELECT payment_last4 FROM core.reservations")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await db.fetch("SELECT * FROM eval.group_inquiry_expectations")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await db.fetch("UPDATE ops.inventory_nights SET sold = 0")


async def test_agent_view_is_masked(db):
    g = await db.fetchrow("SELECT * FROM agent.v_guests WHERE guest_id = 'G10001'")
    assert g["email_masked"] == "l***@example.com" and g["phone_masked"] == "***-***-0148"
    assert "email" not in g and "last_name" not in g
    r = await db.fetchrow("SELECT * FROM agent.v_reservations WHERE reservation_id = 'R55001'")
    assert r["card_on_file"] is True and "payment_last4" not in r


async def test_verify_requires_matching_last_name(db):
    assert await services.verify_guest("R55010", "Smith")
    assert not await services.verify_guest("R55010", "Smyth")


# --- inventory safety under concurrency -----------------------------------------
async def test_no_overbooking_under_concurrent_holds(db):
    """40 simultaneous single-room holds against 15 Providence suites: exactly 15 succeed."""
    day_in, day_out = date(2027, 2, 10), date(2027, 2, 12)
    cap = (await db.fetchrow("SELECT min(capacity - sold - held) AS a FROM agent.v_inventory WHERE property_code='SOL-PVD' "
                             "AND room_type='Suite' AND stay_date >= %s AND stay_date < %s", (day_in, day_out)))["a"]

    async def attempt(i):
        try:
            row = await db.fetchrow(
                "SELECT hold_id FROM agent.place_hold('stay','SOL-PVD','Suite',%s,%s,1,5,%s,NULL,%s,NULL,0,'{}')",
                (day_in, day_out, f"race-{i}-{datetime.now().timestamp()}", f"race-{i}"))
            return row["hold_id"]
        except psycopg.Error as e:
            assert "insufficient_inventory" in str(e)
            return None

    results = await asyncio.gather(*(attempt(i) for i in range(40)))
    won = [h for h in results if h]
    try:
        assert len(won) == cap
        row = await db.fetchrow("SELECT max(sold + held - capacity) AS over FROM agent.v_inventory WHERE "
                                "property_code='SOL-PVD' AND room_type='Suite' AND stay_date >= %s AND stay_date < %s",
                                (day_in, day_out))
        assert row["over"] <= 0
    finally:
        for h in won:
            await db.fetchrow("SELECT agent.release_hold(%s) AS ok", (h,))


async def test_hold_is_idempotent(db):
    args = ("SOL-CHI", "Suite", date(2027, 4, 1), date(2027, 4, 3), "idem-test-1")
    q = "SELECT hold_id FROM agent.place_hold('stay',%s,%s,%s,%s,1,5,%s,NULL,NULL,NULL,0,'{}')"
    a = await db.fetchrow(q, args)
    b = await db.fetchrow(q, args)
    assert a["hold_id"] == b["hold_id"]
    await db.fetchrow("SELECT agent.release_hold(%s) AS ok", (a["hold_id"],))


# --- stay policy -----------------------------------------------------------------
def _res(**kw):
    base = dict(reservation_id="R1", status="Confirmed", rate_plan="Best Available Rate", nightly_rate=219,
                total_nights=2, check_in=date(2026, 8, 22), check_out=date(2026, 8, 24))
    return base | kw


def test_cancellation_free_window():
    q = stay.cancellation_quote(_res(), NOW)
    assert q["free_cancellation"] is True and q["policy_refs"] == [2]


def test_cancellation_inside_72h_matches_r55005_note():
    # R55005: arrival 06-06, cancelled 06-04 — the note calls that 36h past the cutoff.
    q = stay.cancellation_quote(_res(check_in=date(2026, 6, 6), check_out=date(2026, 6, 8)), datetime(2026, 6, 4, 12))
    assert q["free_cancellation"] is False and q["penalty"]["nights"] == 1


def test_advance_purchase_non_refundable():
    q = stay.cancellation_quote(_res(rate_plan="Advance Purchase"), NOW)
    assert q["penalty"]["non_refundable"] and q["policy_refs"] == [3]


def test_loyalty_redemption_is_a_policy_gap_not_a_guess():
    q = stay.cancellation_quote(_res(rate_plan="Loyalty Redemption", nightly_rate=0), NOW)
    assert q["requires_human"] and not q["cancellable"]


@pytest.mark.parametrize("tier,req,status", [
    ("Platinum", "2pm", "confirmed"), ("Platinum", "4pm", "pending_desk"), ("Gold", "1pm", "pending_desk"),
    ("None", "1pm", "pending_desk"), ("Silver", "10am", "not_needed")])
def test_late_checkout(tier, req, status):
    assert stay.late_checkout(tier, req)["status"] == status


def test_service_recovery_r55012_outside_window():
    r = _res(status="Checked-out", check_in=date(2026, 6, 20), check_out=date(2026, 6, 22), rate_plan="Advance Purchase")
    a = stay.service_recovery(r, datetime(2026, 7, 5, 12), issue_type="refund_request", reported_during_stay=False,
                              amount_usd=None)
    assert a["eligible"] is False and "goodwill" in a["recommended_action"].lower()


def test_service_recovery_reported_during_stay_counts():
    r = _res(status="Checked-out", check_in=date(2026, 6, 20), check_out=date(2026, 6, 22))
    a = stay.service_recovery(r, datetime(2026, 7, 5, 12), issue_type="stay_problem", reported_during_stay=True,
                              amount_usd=40)
    assert a["eligible"] is True and a["route_to"] == "Front Desk"


def test_comp_over_50_needs_manager():
    r = _res(status="Checked-out", check_out=date(2026, 7, 11), check_in=date(2026, 7, 9))
    a = stay.service_recovery(r, NOW, issue_type="stay_problem", reported_during_stay=False, amount_usd=30,
                              prior_comps_usd=25)
    assert a["route_to"] == "Manager on Duty / AGM"


# --- guardrails ------------------------------------------------------------------
def test_redacts_real_card_numbers_only():
    out, kinds = guardrails.redact_pii("my card is 4111 1111 1111 1111 and my confirmation is R55001, cvv 123")
    assert "4111 1111" not in out and "card ending 1111" in out and "R55001" in out and "123" not in out
    out2, kinds2 = guardrails.redact_pii("order 1234 5678 9012 3456")   # fails Luhn
    assert "card" not in kinds2


def test_ungrounded_figures():
    assert guardrails.ungrounded_figures("Late checkout costs $75.", '{"policy": 1}') == ["$75"]
    assert guardrails.ungrounded_figures("Your rate is $219 per night until 2:00 PM.", '{"nightly_rate": 219.0, "t": "2:00 PM"}') == []
    assert guardrails.ungrounded_figures("Check-out is 11 AM.", "Standard check-out is 11:00 AM.") == []


def test_staff_note_leak():
    note = "Promo code SOLSTICE2024 expired 2025-12-31. Do not apply retroactively."
    assert guardrails.leaks_staff_notes("Sorry, promo code SOLSTICE2024 expired 2025-12-31. Do not apply retroactively.", [note])
    assert not guardrails.leaks_staff_notes("That promo code is no longer valid, sorry.", [note])


@pytest.mark.parametrize("text,cat", [
    ("someone is banging on my door and threatening me", "safety"),
    ("my son is having an allergic reaction", "medical"),
    ("I'm going to contact my lawyer", "legal"),
    ("I'm sick of waiting for towels", None),
    ("what's the hospitality fee?", None),
    ("can I get late checkout", None)])
def test_triage(text, cat):
    assert escalation.triage(text) == cat
