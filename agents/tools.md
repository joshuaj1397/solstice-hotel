# Tools & skills

Every tool is a plain async Python function registered with ADK (`FunctionTool` via
`LlmAgent(tools=[...])`). The docstring is the model-facing description. Two rules apply
to all of them:

1. **Identity comes from session state, never from arguments.** No tool accepts a
   `guest_id`. The BFF binds the verified guest to the session, or the guest verifies
   with `find_reservation`. A prompt-injected "show me guest G10010" has nothing to call.
2. **Tools return decisions, not data dumps.** Each result carries `status`,
   `explanation` (plain English the model can relay), and `policy_refs`. The model
   phrases the answer; it never computes it.

Source: [`tools/concierge_tools.py`](../agent-service/src/solstice_agents/tools/concierge_tools.py).
Every tool is wrapped by `_safe()`: an exception becomes
`{"error": "tool_unavailable", ...}`, which tells the model to offer a hand-off rather
than guess.

## Concierge tools

| Tool | Purpose | Deterministic engine | Side effects |
|---|---|---|---|
| `find_reservation(confirmation_number, last_name)` | Front-desk-style verification; binds the session to the guest | `agent.verify_guest()` (SQL) | session state |
| `get_my_stay()` | Stays, loyalty tier, points, tier benefits | `rules/stay.loyalty_benefits` | none |
| `lookup_policy(question)` | Retrieve the 1–2 most relevant policy sections, cited by number | Postgres full-text search (OR-of-lexemes + curated synonyms) | none |
| `property_info(property)` | Location, room types, Best Available base rates, meeting capacity; lists what is *not* in the data (parking rates) | catalog | none |
| `check_availability(city_or_property, check_in, check_out, room_type?)` | Live inventory + BAR quote; includes **Booking Rescue** alternatives when sold out | `agent.availability()` + `rules/rescue.stay_alternatives` | funnel event |
| `hold_room(property_code, room_type, check_in, check_out)` | 15-minute hold so the guest can finish secure checkout | `ops.place_hold()` (row locks + CHECK) | inventory hold |
| `request_stay_change(request, reservation_id?, time?, details?)` | Late check-out, early check-in, upgrade, amenity | `rules/stay.late_checkout / early_checkin / upgrade_request`, amenity catalog | service request (confirmed or pending desk) |
| `cancellation_options(reservation_id?)` | Explains cancellation cost under the rate plan; **does not cancel** (the guest confirms in the UI) | `rules/stay.cancellation_quote` | none |
| `report_problem(issue_type, description, …)` | **Service Recovery Adjudicator** + hand-off | `rules/stay.service_recovery` + escalation matrix | escalation case |
| `escalate_to_staff(reason, category)` | Hand-off with full transcript and context | `rules/escalation.route_for` | escalation case |

### Policy decisions the tools encode (examples)

| Situation | Decision | Why |
|---|---|---|
| Platinum asks for 2 PM checkout | **confirmed** automatically | Policy 6: "guaranteed late check-out until 2:00 PM" |
| Gold or non-member asks for 1 PM | logged, **pending desk** | Policies 1 and 6: subject to same-day availability, front-desk discretion |
| Cancel BAR / Corporate rate > 72 h out | free | Policy 2. The cutoff is 72 h before the arrival *date*, which matches the R55005 note ("36 hours after the cutoff") |
| Cancel Advance Purchase | non-refundable, full stay | Policy 3 |
| Cancel Loyalty Redemption | **requires a human** | Not covered by the written policy, so the tool won't guess |
| Refund 13 days after checkout, not raised during the stay | not eligible; goodwill points; MOD/AGM same day | Policies 5 and 15 |
| Issue raised *during* the stay, followed up later | eligible: the window runs from checkout | Policy 5 "wrinkle" |
| Comp total over $50 per stay (summed) | AGM/GM sign-off | Policy 7 |
| Minibar / folio dispute | AGM review, never adjust the folio | Policy 7 + front-desk note on R55006 |

## Net-new skills (not handed to us in the data)

### 1. Booking Rescue (`rules/rescue.py`)

The data says when to say **no** (blackouts, limits, ceilings, capacity), but not what to
offer instead. Every "no" is a lost reservation unless someone builds the next-best "yes"
while the client is still engaged. Booking Rescue searches, deterministically, in this order:

- **Shifted dates** at the same property (±7/14/21/28 days, same length and weekday pattern)
  that clear blackouts, inventory and lead time
- **Nearby sister properties** that satisfy every hard constraint, ranked by great-circle distance
- **Split / partial blocks** that stay inside auto-approve authority. For example, INQ-2007
  becomes "confirm 15 rooms at Providence now; route 5 to the Boston-area sister property"
- **Off-site venue pairing** when only the meeting room is the blocker (INQ-2005)
- For individual stays, **±1–3 days or the nearest property** when sold out

Options a property can confirm without GM review sort first, so sales can close while the
client is still on the line.

### 2. Service Recovery Adjudicator (`rules/stay.service_recovery`)

It turns Policies 5, 7 and 15 into one decision: eligibility window, the
"mentioned during the stay" rule, per-stay comp aggregation, approval authority, routing,
and a recommended action. The human receives a pre-adjudicated case and closes it in one step.

### 3. Intent router + tool-call repair (`rules/intent.py`)

A measured fix for a small-model failure. Without it, Gemma 4 E2B skipped the needed tool
in 6–10 of 14 turns and sometimes *claimed* actions it hadn't taken ("I am submitting this
as a dispute…"). The router recognizes unambiguous asks and parses arguments in code. The
agent sees a hint, and if it still answers without acting, `after_model_callback` replaces
the reply with exactly that function call. Result: 12/12 correct tool use. See
[ADR-0006](../docs/adr/0006-model-configuration.md).

## Group workflow nodes

See [group-workflow.md](group-workflow.md).

## Deterministic quick actions (same services, no LLM)

`/v1/actions/request`, `/v1/actions/cancel`, `/v1/actions/escalate`, `/v1/holds`,
`/v1/bookings`. The stay-card buttons call the same `services.py` functions as the tools.
The chat and the buttons can never disagree, and the buttons keep working when the model is down.
