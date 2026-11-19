import pytest

from solstice_agents.rules import intent


@pytest.mark.parametrize("text,tool,args", [
    ("Could I check out at 1pm instead of 11?", "request_stay_change", {"request": "late_checkout", "time": "1pm"}),
    ("Hi! Can I get a late checkout at 2pm on my Denver stay?", "request_stay_change", {"request": "late_checkout"}),
    ("My flight lands at 8am, can I check in early?", "request_stay_change", {"request": "early_checkin"}),
    ("I need to cancel my Sacramento booking, will I get my money back?", "cancellation_options", {}),
    ("There's a $45 minibar charge on my bill but I never touched the minibar.", "report_problem",
     {"issue_type": "charge_dispute", "amount_usd": 45.0}),
    ("It was really noisy. I want a refund.", "report_problem", {"issue_type": "refund_request"}),
    ("The AC was broken and I told the front desk during my stay", "report_problem", {"reported_during_stay": True}),
    ("What time is check-in?", "lookup_policy", {}),
    ("What's your cancellation policy?", "lookup_policy", {}),
    ("Can I bring my dog?", "lookup_policy", {}),
    ("Could we get a rollaway bed?", "request_stay_change", {"request": "amenity"}),
    ("I want to talk to a real person", "escalate_to_staff", {}),
    ("How many points do I have?", "get_my_stay", {}),
])
def test_detect(text, tool, args):
    got = intent.detect(text)
    assert got and got.tool == tool, got
    for k, v in args.items():
        assert got.args[k] == v, (k, got.args)


def test_no_intent_for_open_questions():
    assert intent.detect("Do you have a room in Austin from September 18 to 20?") is None


@pytest.mark.parametrize("text,claims", [
    ("I am submitting this as a charge dispute for the $45 minibar charge.", True),
    ("You will hear back regarding case number [Case Number].", True),
    ("I have logged your request for a 1 PM check-out.", True),
    ("Standard check-in time is 3:00 PM.", False),
])
def test_action_claims(text, claims):
    assert bool(intent.ACTION_CLAIM.search(text)) is claims
