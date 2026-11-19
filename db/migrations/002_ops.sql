-- 002_ops.sql — operational state: room-night inventory, holds, cases, requests, telemetry.
SET LOCAL ROLE solstice_owner;

-- ---------------------------------------------------------------------------
-- Inventory: one row per property × room type × night. The CHECK constraint is
-- the last line of defence against overbooking; the functions below are the first.
-- fillfactor leaves room for HOT updates on the hot counters.
-- ---------------------------------------------------------------------------
CREATE TABLE ops.inventory_nights (
  property_code  text NOT NULL,
  room_type      text NOT NULL,
  stay_date      date NOT NULL,
  capacity       int  NOT NULL CHECK (capacity >= 0),
  sold           int  NOT NULL DEFAULT 0 CHECK (sold >= 0),
  held           int  NOT NULL DEFAULT 0 CHECK (held >= 0),
  PRIMARY KEY (property_code, room_type, stay_date),
  FOREIGN KEY (property_code, room_type) REFERENCES core.property_room_types,
  CONSTRAINT no_overbooking CHECK (sold + held <= capacity)
) WITH (fillfactor = 80);

CREATE TABLE ops.holds (
  hold_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind             text NOT NULL CHECK (kind IN ('stay', 'group')),
  property_code    text NOT NULL,
  room_type        text NOT NULL,
  check_in         date NOT NULL,
  check_out        date NOT NULL,
  rooms            int  NOT NULL CHECK (rooms > 0),
  nightly_rate     numeric(10,2),
  status           text NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'converted', 'released', 'expired')),
  expires_at       timestamptz NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  guest_id         text,
  session_id       text,
  inquiry_id       text,
  reservation_id   text,
  idempotency_key  text UNIQUE,
  quote            jsonb NOT NULL DEFAULT '{}',
  CHECK (check_out > check_in)
);
CREATE INDEX holds_active_expiry_idx ON ops.holds (expires_at) WHERE status = 'active';

CREATE SEQUENCE ops.reservation_seq START 56001;
CREATE SEQUENCE ops.inquiry_seq START 3001;   -- ids for inquiries arriving by email intake

-- Lock a property/room-type date range in a deterministic order (prevents deadlocks).
CREATE FUNCTION ops._lock_nights(p_property text, p_room_type text, p_in date, p_out date)
RETURNS int LANGUAGE sql AS $$
  WITH locked AS (
    SELECT 1 FROM ops.inventory_nights
     WHERE property_code = p_property AND room_type = p_room_type
       AND stay_date >= p_in AND stay_date < p_out
     ORDER BY stay_date
     FOR UPDATE)
  SELECT count(*)::int FROM locked;
$$;

-- Atomically reserve inventory for a hold. Raises 'insufficient_inventory' if any night
-- would exceed capacity. Idempotent on p_idempotency_key (safe for client retries).
CREATE FUNCTION ops.place_hold(
  p_kind text, p_property text, p_room_type text, p_check_in date, p_check_out date,
  p_rooms int, p_ttl interval, p_idempotency_key text DEFAULT NULL,
  p_guest_id text DEFAULT NULL, p_session_id text DEFAULT NULL, p_inquiry_id text DEFAULT NULL,
  p_nightly_rate numeric DEFAULT NULL, p_quote jsonb DEFAULT '{}')
RETURNS ops.holds LANGUAGE plpgsql AS $$
DECLARE
  v_hold   ops.holds;
  v_nights int := p_check_out - p_check_in;
  v_short  date;
BEGIN
  IF p_idempotency_key IS NOT NULL THEN
    SELECT * INTO v_hold FROM ops.holds WHERE idempotency_key = p_idempotency_key;
    IF FOUND THEN RETURN v_hold; END IF;
  END IF;
  IF v_nights <= 0 OR p_rooms <= 0 THEN
    RAISE EXCEPTION 'invalid_request' USING ERRCODE = '22023';
  END IF;

  IF ops._lock_nights(p_property, p_room_type, p_check_in, p_check_out) <> v_nights THEN
    RAISE EXCEPTION 'no_inventory_calendar' USING ERRCODE = 'P0002';
  END IF;

  SELECT min(stay_date) INTO v_short FROM ops.inventory_nights
   WHERE property_code = p_property AND room_type = p_room_type
     AND stay_date >= p_check_in AND stay_date < p_check_out
     AND sold + held + p_rooms > capacity;
  IF v_short IS NOT NULL THEN
    RAISE EXCEPTION 'insufficient_inventory' USING ERRCODE = 'P0001', DETAIL = v_short::text;
  END IF;

  UPDATE ops.inventory_nights SET held = held + p_rooms
   WHERE property_code = p_property AND room_type = p_room_type
     AND stay_date >= p_check_in AND stay_date < p_check_out;

  INSERT INTO ops.holds (kind, property_code, room_type, check_in, check_out, rooms, nightly_rate,
                         expires_at, guest_id, session_id, inquiry_id, idempotency_key, quote)
  VALUES (p_kind, p_property, p_room_type, p_check_in, p_check_out, p_rooms, p_nightly_rate,
          now() + p_ttl, p_guest_id, p_session_id, p_inquiry_id, p_idempotency_key, p_quote)
  RETURNING * INTO v_hold;
  RETURN v_hold;
END $$;

-- Move a hold's rooms from held → sold. For stay holds, mint a reservation.
CREATE FUNCTION ops.convert_hold(p_hold_id uuid, p_guest_id text, p_card_last4 text)
RETURNS ops.holds LANGUAGE plpgsql AS $$
DECLARE
  v_hold ops.holds;
  v_res  text;
BEGIN
  SELECT * INTO v_hold FROM ops.holds WHERE hold_id = p_hold_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'hold_not_found' USING ERRCODE = 'P0002'; END IF;
  IF v_hold.status = 'converted' THEN RETURN v_hold; END IF;           -- idempotent
  IF v_hold.status <> 'active' OR v_hold.expires_at < now() THEN
    RAISE EXCEPTION 'hold_expired' USING ERRCODE = 'P0001';
  END IF;

  PERFORM ops._lock_nights(v_hold.property_code, v_hold.room_type, v_hold.check_in, v_hold.check_out);
  UPDATE ops.inventory_nights SET held = held - v_hold.rooms, sold = sold + v_hold.rooms
   WHERE property_code = v_hold.property_code AND room_type = v_hold.room_type
     AND stay_date >= v_hold.check_in AND stay_date < v_hold.check_out;

  IF v_hold.kind = 'stay' THEN
    v_res := 'R' || nextval('ops.reservation_seq');
    INSERT INTO core.reservations (reservation_id, guest_id, property_code, check_in, check_out,
                                   room_type, rate_plan, nightly_rate, total_nights, status,
                                   payment_last4, source)
    VALUES (v_res, p_guest_id, v_hold.property_code, v_hold.check_in, v_hold.check_out,
            v_hold.room_type, 'Best Available Rate', v_hold.nightly_rate,
            v_hold.check_out - v_hold.check_in, 'Confirmed', p_card_last4, 'agent_booking');
  END IF;

  UPDATE ops.holds SET status = 'converted', reservation_id = v_res, guest_id = coalesce(p_guest_id, guest_id)
   WHERE hold_id = p_hold_id RETURNING * INTO v_hold;
  RETURN v_hold;
END $$;

CREATE FUNCTION ops.release_hold(p_hold_id uuid, p_status text DEFAULT 'released')
RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE v_hold ops.holds;
BEGIN
  SELECT * INTO v_hold FROM ops.holds WHERE hold_id = p_hold_id FOR UPDATE;
  IF NOT FOUND OR v_hold.status <> 'active' THEN RETURN false; END IF;
  PERFORM ops._lock_nights(v_hold.property_code, v_hold.room_type, v_hold.check_in, v_hold.check_out);
  UPDATE ops.inventory_nights SET held = held - v_hold.rooms
   WHERE property_code = v_hold.property_code AND room_type = v_hold.room_type
     AND stay_date >= v_hold.check_in AND stay_date < v_hold.check_out;
  UPDATE ops.holds SET status = p_status WHERE hold_id = p_hold_id;
  RETURN true;
END $$;

-- Sweeper (run every few seconds by the agent service). Expired holds keep counting
-- as held until swept, so availability is conservative, never optimistic.
CREATE FUNCTION ops.expire_holds() RETURNS int LANGUAGE plpgsql AS $$
DECLARE r record; n int := 0;
BEGIN
  FOR r IN SELECT hold_id FROM ops.holds
            WHERE status = 'active' AND expires_at < now()
            ORDER BY hold_id FOR UPDATE SKIP LOCKED LOOP
    PERFORM ops.release_hold(r.hold_id, 'expired');
    n := n + 1;
  END LOOP;
  RETURN n;
END $$;

-- Cancelling a confirmed stay returns its nights to inventory.
CREATE FUNCTION ops.cancel_reservation(p_reservation_id text)
RETURNS core.reservations LANGUAGE plpgsql AS $$
DECLARE v core.reservations;
BEGIN
  SELECT * INTO v FROM core.reservations WHERE reservation_id = p_reservation_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'reservation_not_found' USING ERRCODE = 'P0002'; END IF;
  IF v.status <> 'Confirmed' THEN RAISE EXCEPTION 'not_cancellable' USING ERRCODE = 'P0001'; END IF;
  PERFORM ops._lock_nights(v.property_code, v.room_type, v.check_in, v.check_out);
  UPDATE ops.inventory_nights SET sold = greatest(sold - 1, 0)
   WHERE property_code = v.property_code AND room_type = v.room_type
     AND stay_date >= v.check_in AND stay_date < v.check_out;
  UPDATE core.reservations SET status = 'Cancelled', cancelled_at = now()
   WHERE reservation_id = p_reservation_id RETURNING * INTO v;
  RETURN v;
END $$;

-- ---------------------------------------------------------------------------
-- Guest service requests (late checkout, early check-in, amenities, upgrades)
-- ---------------------------------------------------------------------------
CREATE SEQUENCE ops.request_seq START 3001;
CREATE TABLE ops.service_requests (
  request_id      text PRIMARY KEY DEFAULT 'REQ-' || nextval('ops.request_seq'),
  kind            text NOT NULL,
  reservation_id  text NOT NULL,
  guest_id        text NOT NULL,
  property_code   text NOT NULL,
  details         jsonb NOT NULL DEFAULT '{}',
  status          text NOT NULL CHECK (status IN ('confirmed', 'pending_desk', 'approved', 'declined')),
  decided_by      text,                  -- 'policy:<rule>' when auto-decided, staff id otherwise
  desk_note       text,
  session_id      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  decided_at      timestamptz
);
CREATE INDEX service_requests_status_idx ON ops.service_requests (status, created_at);

-- ---------------------------------------------------------------------------
-- Escalations: the hand-off packet. A human picks it up with full context.
-- ---------------------------------------------------------------------------
CREATE SEQUENCE ops.escalation_seq START 1001;
CREATE TABLE ops.escalations (
  case_id             text PRIMARY KEY DEFAULT 'ESC-' || nextval('ops.escalation_seq'),
  created_at          timestamptz NOT NULL DEFAULT now(),
  category            text NOT NULL,
  severity            text NOT NULL CHECK (severity IN ('immediate', 'same_day', 'standard')),
  route_to            text NOT NULL,
  property_code       text,
  guest_id            text,
  reservation_id      text,
  guest_ask           text NOT NULL,
  summary             text NOT NULL,
  agent_assessment    jsonb NOT NULL DEFAULT '{}',
  policy_refs         int[] NOT NULL DEFAULT '{}',
  recommended_action  text,
  transcript          jsonb NOT NULL DEFAULT '[]',
  status              text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved')),
  assigned_to         text,
  resolution_note     text,
  sla_due_at          timestamptz NOT NULL,
  resolved_at         timestamptz,
  session_id          text
);
CREATE INDEX escalations_open_idx ON ops.escalations (status, severity, sla_due_at);

CREATE TABLE ops.escalation_messages (
  message_id  bigserial PRIMARY KEY,
  case_id     text NOT NULL REFERENCES ops.escalations,
  author      text NOT NULL CHECK (author IN ('staff', 'guest', 'system')),
  author_name text,
  body        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Group proposals produced by the group-booking workflow.
-- ---------------------------------------------------------------------------
CREATE SEQUENCE ops.proposal_seq START 7001;
CREATE TABLE ops.group_proposals (
  proposal_id   text PRIMARY KEY DEFAULT 'GP-' || nextval('ops.proposal_seq'),
  inquiry_id    text NOT NULL,
  status        text NOT NULL CHECK (status IN
                  ('auto_approved', 'needs_review', 'needs_clarification', 'approved', 'sent', 'declined')),
  priority      text NOT NULL DEFAULT 'normal' CHECK (priority IN ('urgent', 'normal')),
  decision      jsonb NOT NULL,          -- full structured output of the rules engine
  narrative     text,                    -- LLM-written cover note (numerically validated)
  trace         jsonb NOT NULL DEFAULT '[]',
  hold_ids      uuid[] NOT NULL DEFAULT '{}',
  latency_ms    int,
  created_at    timestamptz NOT NULL DEFAULT now(),
  reviewed_by   text,
  reviewed_at   timestamptz,
  review_note   text
);
CREATE INDEX group_proposals_inquiry_idx ON ops.group_proposals (inquiry_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Telemetry: conversion funnel, per-turn latency, guardrail activations.
-- ---------------------------------------------------------------------------
CREATE TABLE ops.funnel_events (
  event_id       bigserial PRIMARY KEY,
  at             timestamptz NOT NULL DEFAULT now(),
  session_id     text,
  channel        text NOT NULL,          -- concierge | quick_action | group | booking
  event          text NOT NULL,
  property_code  text,
  value_usd      numeric(12,2),
  meta           jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX funnel_events_at_idx ON ops.funnel_events (event, at);

CREATE TABLE ops.turn_metrics (
  turn_id     bigserial PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  session_id  text,
  agent       text NOT NULL,
  latency_ms  int NOT NULL,
  llm_calls   int NOT NULL DEFAULT 0,
  tool_calls  text[] NOT NULL DEFAULT '{}',
  path        text NOT NULL DEFAULT 'llm',   -- llm | triage_bypass | degraded | quick_action
  model       text
);

CREATE TABLE ops.guardrail_events (
  event_id    bigserial PRIMARY KEY,
  at          timestamptz NOT NULL DEFAULT now(),
  session_id  text,
  kind        text NOT NULL,
  detail      jsonb NOT NULL DEFAULT '{}'
);
