# Demo script

## Business conversation (product owner), ~15 min

| # | Show | Say |
|---|---|---|
| 1 | Home → **Manage my stay** → demo guest *Chen (Platinum)* | "Guests sign in exactly as at the desk: confirmation number and last name." |
| 2 | Ask: *"Can I get a late checkout at 2pm? Any chance of a suite?"* | 2 PM is **confirmed** instantly (Platinum guarantee, Policy 6); the suite is **sent to the desk** because it depends on same-day inventory. The agent knows the difference between a guarantee and a request. |
| 3 | Sign in as *Moreau*, tap **Late check-out 1 PM** | Same request without the AI: the buttons keep working even if the model is down. |
| 4 | **Book a stay** → Phoenix, two nights → **Hold 15 min** → **Complete booking** (4242…) | A booking from chat or search in under a minute. Card details never pass through the chat. |
| 5 | Sign in as *Kalinski*: *"It was noisy in June, I want a refund."* | It doesn't promise money and doesn't dead-end: it explains the 72-hour rule, offers goodwill points, and opens case ESC-… with the assessment done. |
| 6 | **Staff → Queue → that case** | The manager sees the whole conversation, the policy math and a recommended action. Reply → the guest sees it in their chat. |
| 7 | **Groups** → *Fill a sample wedding* → Get my proposal | About a second: priced, rooms held for 72 h. "Two days becomes two seconds; sales reviews instead of builds." |
| 8 | **Staff → Group sales** → run INQ-2002 (40 rooms, 22% off) | Flagged for GM review (block over 35, discount over 15%), with a Booking Rescue option sales can confirm **today**: 35 rooms at the 15% ceiling, plus sister properties for the overflow. One click approves and holds the inventory. |
| 9 | **Staff → Metrics** | Funnel (conversations → holds → bookings), containment, latency vs target, data issues caught at ingestion (Providence's −$395 suite rate). |

Questions to expect: *"What if it's wrong?"* → guardrails page + numeric grounding. *"Will it
replace my desk?"* → [integration-recommendation.md](integration-recommendation.md#is-the-ai-coming-for-our-jobs).
*"Can we start small?"* → Phase 0 read-only shadow mode.

## Technical conversation (director of engineering), ~20 min

1. **Architecture**: `/staff/architecture`: future state, degradation, turn sequence, data boundaries.
2. **Turn internals**: toggle *Agent internals* in chat: router hint → tool → card → latency/path.
   Then walk `api.py` (`send_message`): redact → triage → router → runner → guardrails.
3. **Least privilege**: `003_agent_surface.sql`, `pytest -k raw_pii`; in Postgres,
   `SELECT usename, valuntil FROM pg_user WHERE usename LIKE 'v-%'` (Vault dynamic users).
4. **Overbooking**: `ops.place_hold`, `pytest -k overbooking` (40 concurrent → exactly 15).
5. **Model engineering**: [ADR-0006](adr/0006-model-configuration.md) A/B table. Run
   `uv run python scripts/run_transcripts.py` live and read the latencies.
6. **Degradation**: `docker stop solstice-ollama` (container mode) or stop host Ollama →
   chat answers in limited mode within 20 s; restart → recovers.
7. **Group engine vs the answer key**: `pytest tests/test_group_rules.py -v`, and the five
   violations the answer key missed.

## "Change something live": likely asks and where

| Ask | Change | Verify |
|---|---|---|
| "Let Gold members auto-confirm 1 PM checkout" | `rules/stay.late_checkout`: add a `tier == "Gold" and req <= 13:00 → confirmed` branch with `decided_by="policy:gold_late_checkout"` | `pytest -k late_checkout` (update the parametrize row); chat as a Gold guest (R55006 Webb) |
| "Raise Tampa's discount ceiling to 18%" | Edit `solstice-data/solstice-properties.csv` → `uv run solstice-migrate --reseed` (or `UPDATE core.properties`; the catalog refreshes within 5 min) | Re-run INQ-2002 in Group sales: the discount flag clears, block size still flagged |
| "Add a rule: no youth groups on Nashville weekends" | Add a `PROPERTY_RULES["SOL-NSH"]` entry + a check in `rules/group.evaluate` | New test in `test_group_rules.py` |
| "Shorten stay holds to 10 minutes" | `SOLSTICE_STAY_HOLD_TTL_MINUTES=10` | Hold card countdown |
| "Add a new tool, e.g. restaurant hours" | Function in `tools/concierge_tools.py` + `CONCIERGE_TOOLS` + a `TOOL_LABELS` entry; data in Postgres; optional router intent in `rules/intent.py` | Ask in chat with internals on |
| "Use a bigger model" | `SOLSTICE_MODEL=gemma4:e4b` (already pulled) | `run_transcripts.py`: compare accuracy and latency |
| "Stop budget-match discounts" | `SOLSTICE_BUDGET_MATCH=false` | INQ-2001 shows only "As requested" |
| "Escalate any mention of 'chargeback' immediately" | Add to the `legal` or `dispute` triage regex in `rules/escalation.py` | `pytest -k triage` |
