# Integration recommendation

## How a chain like Solstice actually runs today

A 140-hotel upper-midscale group usually runs three core systems, each owned by a different team:

- **Property Management System (PMS):** the property's ledger of who is in which room, folios,
  housekeeping status, and traces/messages between shifts. In this segment that is typically
  Oracle OPERA Cloud (or a brand-mandated PMS for franchised hotels). It exposes APIs and
  business events through Oracle Hospitality Integration Platform (OHIP).
- **Central Reservation System (CRS):** the source of truth for inventory and rates
  across channels (brand.com, call center, OTAs, GDS), e.g. Sabre SynXis. Availability and
  rate questions belong here, not in the PMS.
- **Loyalty/CRM:** member tiers, points and preferences, often a separate SaaS platform
  synced nightly with the PMS.
- Group sales lives in a **Sales & Catering** tool, or, as the brief says, in spreadsheets.

## How I would plug this in

**Phase 0, read-only shadow (weeks 1–4).** Connect to OHIP business events and the CRS
availability API through a small, idempotent integration adapter, and feed the agent's
read model. The agent answers policy and stay questions and drafts group proposals, but
every action lands in a staff queue for one-click approval. We measure containment, accuracy
against staff decisions, and latency against the targets in [latency.md](latency.md).
Nothing writes to a system of record.

**Phase 1, low-risk writes (weeks 5–10).** Turn on writes that already have a safe,
reversible path in the PMS: late-checkout and early-check-in *requests* as PMS traces,
amenity requests, and guaranteed Platinum benefits. Group proposals inside the rules are
auto-sent, with holds created as CRS allocations that expire. Refunds, comps, folio changes
and cancellations stay human, as they are in the PoC.

**Phase 2, bookings (quarter 2).** Direct bookings through the CRS with the payment
provider's hosted fields (PCI scope stays SAQ-A). Booking Rescue offers across sister
properties. Approved group blocks are created in Sales & Catering by the adapter.

Throughout, the PMS remains the system of record. The agent platform owns only what it
creates: holds, cases, requests, proposals and metrics.

## What I'd tell a nervous IT team

- **"It can't touch what it isn't given."** The agent's database user is minted by Vault
  for one hour and can only read masked views. There's no SQL path to card data or raw
  contact details, and it's enforced by Postgres, not by a prompt. You can audit every
  credential issuance in Vault.
- **"It never writes to the folio."** Phase 0 is read-only. Phase 1 writes only requests
  and traces that a human acts on. Money moves only with a named staff member's approval.
- **"Your data doesn't leave for a third-party model."** Gemma runs on infrastructure we
  control (your GCP project or on-prem GPUs). There is no per-token data sharing with a
  model vendor, and the model is pinned, versioned and regression-tested before every upgrade.
- **"When it breaks, it breaks safely."** Every dependency has a degraded mode
  ([architecture.md §2](architecture.md#how-it-degrades-when-something-upstream-fails)).
  Safety messages never depend on the model at all.
- **"You can turn it off per property in seconds."** Feature flags per hotel and per
  capability. The one-tap buttons work without the model.
- **"It's standard plumbing."** Terraform, Vault, Postgres, Cloud Run, OpenTelemetry. No
  bespoke platform to babysit; the integration adapter is the only new moving part, and it
  is idempotent and replayable.

## "Is the AI coming for our jobs?"

The honest answer is about **which hours** of the front-desk job change, so here it is concretely.

Look at the sample data. The repetitive asks (check-in time, pet policy, "can I check out
at 1?", "what are my points?") are minutes of the desk's day, every hour, and the agent
handles them well. The cases that need judgement are the ones the agent is built to
**hand over**: the Platinum guests competing for the last suite, the guest disputing a
minibar charge, the refund past the window, the VIP arriving tonight. The policy reference
itself says "if it doesn't clearly fit, loop in your manager." The agent follows that rule
more consistently than a busy shift can, and **it arrives with the work already done**: the
policy assessment, the 72-hour window math, the comp total, the recommended action, and the
transcript. The associate spends their time on the decision and the relationship, not on
rereading an email chain.

For group sales, the two-day spreadsheet becomes a one-second draft that a person reviews.
The salesperson's job shifts from *building* quotes to *closing* them. Booking Rescue hands
them a confirmable option for most "no"s, so more inquiries become revenue.

What I would commit to with the operations team:

1. **Measure hours, not headcount.** Report the time returned to each property (deflected
   routine contacts × average handle time) and agree up front how it's reinvested: lobby
   presence, guest recognition, upsell conversations. These are the things the brand is
   built on ("people, not folio numbers").
2. **Staff own the escalation rules.** Front-desk leads, not engineers, decide what the agent
   must hand off. Every hand-off carries a feedback button, so the desk tunes the system.
3. **Make the AI accountable to the desk.** The staff console shows every request the agent
   auto-confirmed and why. If a desk lead disagrees with a policy decision, it is one rule
   row to change, and the change is reviewed and versioned like any policy.
4. **Train for the new work.** The roles that grow are the ones the agent can't do: service
   recovery, VIP and group relationships, and supervising the agent's queue.
