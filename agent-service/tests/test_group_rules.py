"""The ten sample inquiries are the acceptance suite for the group rules engine.

Expected outcomes come from eval.group_inquiry_expectations (the CSV's reviewer notes) plus
catches the notes miss: INQ-2003 also exceeds Austin's meeting capacity (250 > 220); INQ-2005
is also over Sacramento's 20-room auto-approve limit (22); INQ-2008 is also over Columbus's
room (28 > 20) and discount (12% > 10%) limits; and INQ-2010 falls inside Sacramento's
2027-05-03..07 blackout, not just its seasonal discount cap.
"""

import pytest

from solstice_agents import services
from solstice_agents.config import get_settings
from solstice_agents.rules import group, rescue

EXPECTED = {
    #           status                 required flag ids (subset)           forbidden flag ids
    "INQ-2001": ("auto_approved",       set(),                               {"discount", "block_size"}),
    "INQ-2002": ("needs_review",        {"block_size", "discount"},          {"blackout"}),
    "INQ-2003": ("needs_review",        {"blackout", "meeting"},             set()),
    "INQ-2004": ("needs_clarification", set(),                               set()),
    "INQ-2005": ("needs_review",        {"meeting", "block_size"},           {"discount"}),
    "INQ-2006": ("auto_approved",       set(),                               set()),
    "INQ-2007": ("needs_review",        {"route_over"},                      {"discount"}),
    "INQ-2008": ("needs_review",        {"block_size", "discount"},          {"blackout"}),
    "INQ-2009": ("needs_review",        {"discount"},                        {"block_size", "blackout", "inventory", "meeting"}),
    "INQ-2010": ("needs_review",        {"blackout", "discount"},            set()),
}


async def _decide(db, iid):
    row = await db.fetchrow("SELECT * FROM agent.v_group_inquiries WHERE inquiry_id = %s", (iid,))
    req = group.GroupRequest.from_row(row)
    cat = await services.catalog()
    d = await group.evaluate(req, cat, get_settings().business_date)
    d["alternatives"] = await rescue.group_alternatives(req, d, cat, get_settings().business_date)
    return d


@pytest.mark.parametrize("iid", sorted(EXPECTED))
async def test_inquiry_outcomes(db, iid):
    status, must, must_not = EXPECTED[iid]
    d = await _decide(db, iid)
    flags = {f["id"] for f in d["flags"]}
    assert d["status"] == status, (iid, d["status"], flags)
    assert must <= flags, (iid, flags)
    assert not (must_not & flags), (iid, flags)


async def test_2001_budget_match_option(db):
    d = await _decide(db, "INQ-2001")
    opts = {o["label"]: o for o in d["pricing"]["options"]}
    assert opts["As requested"]["rate"] == 197.10
    assert opts["Budget match"]["discount_pct"] == 11 and opts["Budget match"]["rate"] == 194.91
    assert opts["Budget match"]["auto_approvable"]


async def test_2004_asks_the_right_questions(db):
    d = await _decide(db, "INQ-2004")
    assert {m["field"] for m in d["missing"]} == {"dates", "rooms", "room_type", "meeting_capacity"}
    assert {m["field"] for m in d["optional_questions"]} >= {"budget", "phone"}


async def test_2006_is_urgent(db):
    assert (await _decide(db, "INQ-2006"))["priority"] == "urgent"


async def test_2008_requires_insurance_condition(db):
    d = await _decide(db, "INQ-2008")
    assert [c["id"] for c in d["conditions"]] == ["youth_insurance"]


async def test_2009_flags_only_the_discount_and_offers_ceiling(db):
    d = await _decide(db, "INQ-2009")
    assert [f["id"] for f in d["flags"]] == ["discount"]
    confirmable = [o for o in d["pricing"]["options"] if o["label"] == "Confirmable today"][0]
    assert confirmable["discount_pct"] == 15 and confirmable["auto_approvable"]


async def test_2002_confirmable_only_where_nothing_else_blocks(db):
    """40 rooms > 35 auto limit: no price for the full block is confirmable, but the 35-room split at the
    15% ceiling is (judged on the offered discount, not the 22% requested)."""
    d = await _decide(db, "INQ-2002")
    assert not any(o["auto_approvable"] for o in d["pricing"]["options"])
    split = [a for a in d["alternatives"] if a["kind"] == "split"][0]
    assert split["rooms"] == 35 and split["discount_pct"] == 15 and split["auto_approvable"]


async def test_2010_seasonal_cap_is_8(db):
    d = await _decide(db, "INQ-2010")
    assert d["pricing"]["effective_ceiling_pct"] == 8


async def test_2005_rescue_finds_big_enough_venue(db):
    d = await _decide(db, "INQ-2005")
    kinds = {a["kind"] for a in d["alternatives"]}
    assert "venue" in kinds
    big = [a for a in d["alternatives"] if a["kind"] == "property"]
    cat = await services.catalog()
    assert big and all(cat.get(a["property_code"]).max_meeting_capacity >= 300 for a in big)


async def test_2007_split_routes_overflow(db):
    d = await _decide(db, "INQ-2007")
    split = [a for a in d["alternatives"] if a["kind"] == "split"][0]
    assert split["rooms"] == 15 and split["overflow_rooms"] == 5 and split["auto_approvable"]


async def test_2003_rescue_offers_dates_outside_sxsw(db):
    d = await _decide(db, "INQ-2003")
    dates = [a for a in d["alternatives"] if a["kind"] == "dates"]
    # Austin can never host 250 people, so a date shift alone can't fix it; other properties can.
    assert not dates
    assert any(a["kind"] == "property" for a in d["alternatives"])
