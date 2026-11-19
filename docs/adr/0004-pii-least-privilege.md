# ADR-0004: PII never unmasked in anything the agent can see

**Status:** accepted · **Phase:** data

## Decision
Defense in depth, with enforcement in the database rather than the prompt:

1. **Schemas.** `core` (raw PII, system-of-record copy), `ops` (operational state), `agent`
   (the only surface the LLM runtime can reach), `eval` (answer keys; the agent has no access).
2. **Roles.** `solstice_agent` can SELECT masked views (`l***@example.com`,
   `***-***-0148`, `card_on_file: true`) and EXECUTE narrow SECURITY DEFINER functions with
   pinned `search_path`. `solstice_staff` reads contact details but never card references.
   Login users are minted by Vault (ADR-0005).
3. **Input redaction** before the model, logs or DB: Luhn-validated card numbers, CVV, SSN, email, phone.
4. **Payment isolation.** Card entry only in checkout; the BFF keeps last-4 (production: hosted fields).
5. **Internal notes** are visible to the agent as guidance but blocked from replies (7-word
   overlap check), and stripped from the guest-facing profile API.
6. **Session-scoped tools.** No tool takes a guest ID.

## Consequences
- Proven by tests: the agent role gets `InsufficientPrivilege` on `core.guests`,
  `core.reservations.payment_last4`, `eval.*` and direct inventory updates.
- Email intake redacts contact details before extraction, and code re-extracts them with
  regex, so the LLM never sees them.
