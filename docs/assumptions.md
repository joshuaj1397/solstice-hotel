# Assumptions

The brief invites stating assumptions where it's ambiguous. Each one below is also visible in code.

| # | Assumption | Why | Where |
|---|---|---|---|
| 1 | **The business date is 2026-07-12.** Every policy clock (72 h windows, lead times, "upcoming stay") runs against it, not wall time. | The exports are a mid-July 2026 snapshot (last group inquiry received 2026-07-12; the R55006 dispute is dated 07-11). Wall-clock dates (November 2026) would make most sample stays historical. | `SOLSTICE_BUSINESS_DATE` |
| 2 | **Availability = room-type inventory − active reservations in the export − active holds.** No synthetic occupancy is invented. | "Never invent availability." In production this is the CRS. | `ops.inventory_nights` |
| 3 | **Accessible King rooms are priced at the property's standard rate.** | The only data point (R55016, CLT, Accessible King at $189) equals CLT's standard rate. | `migrate.py` |
| 4 | **The free-cancellation cutoff is 72 h before the arrival date at 00:00**, not before the 3 PM check-in time. | That's the only reading consistent with the R55005 note ("cancelled 06-04, 36 hours after the cutoff" for a 06-06 arrival). | `rules/stay.cancellation_quote` |
| 5 | **Loyalty Redemption cancellations aren't covered by the written policy**, so the agent hands off rather than guessing. | Policy 2 names BAR and Corporate; Policy 3 names Advance Purchase. | same |
| 6 | **The inquiries CSV `notes` column is an answer key, not operational data.** It lives in `eval.*`, which the agent's database role cannot read. | It contains reviewer commentary ("good test of whether the candidate's agent…"). | `001_core.sql`, `tests/test_group_rules.py` |
| 7 | **Property notes became structured rules once, with human review**, not by an LLM at runtime. | Rules must be deterministic and auditable; a changed note invalidates its rule. | `migrate.PROPERTY_RULES` |
| 8 | **Seasonal caps apply if *any* night of the stay falls in the window.** Denver: Thu–Sun nights, Dec–Feb. Sacramento: Mon–Fri nights, Jan–May. | Conservative reading: a block containing a capped night is priced at the cap. | `rules/group.effective_ceiling` |
| 9 | **Phoenix's "rates drop ~20% June–Aug" is an advisory to sales, not a price.** | "~20%" isn't a rate; quoting it would be inventing one. | advisory check |
| 10 | **The "Boston-area sister property" isn't in the directory**, so routing overflow to it goes to Group Sales. | Never invent a property. | `route_over_rooms` rule |
| 11 | **Non-Platinum late checkout and all early check-ins are requests the desk confirms.** Only Platinum's 2 PM is auto-confirmed. | Policies 1 and 6 make the others front-desk discretion based on same-day occupancy, which the agent can't see. | `rules/stay.late_checkout` |
| 12 | **Amenity prices (rollaway, champagne) and parking rates aren't in the data**, so the agent says so and logs a request. | Policies 9 and 12 explicitly say not to quote from memory. | `services.AMENITY_CATALOG` |
| 13 | **Taxes aren't computed.** Totals are "before tax" / "plus applicable taxes and fees". | No tax rates in the data. | pricing |
| 14 | **Bad source data is quarantined, not repaired.** The Providence suite rate of −$395 is nulled and logged; R55020's "Checked-in" status for an August arrival is kept but flagged. | The PMS is the source of truth; the agent must not quote garbage. | `core.data_quality_issues` |
| 15 | **Guests verify with confirmation number + last name**, as at a front desk. Two different "Michael Smith"s (G10009/G10010) are never matched by name alone. | Matches front-desk practice and the R55010 note. | `agent.verify_guest` |
| 16 | **The staff console uses a shared passcode in the PoC.** Production uses the hotel's SSO with role-based access. | Out of scope for the PoC. | `StaffGate` |
| 17 | **Card capture is simulated**: the BFF validates the card (Luhn) and keeps only the last four digits. | Production uses provider-hosted fields (PCI SAQ-A). | `api/checkout` |
