-- 001_core.sql — system-of-record tables (stand-in for PMS / CRS / CRM exports).
SET LOCAL ROLE solstice_owner;

CREATE SCHEMA core;   -- source-of-truth copies of Solstice data (contains raw PII)
CREATE SCHEMA ops;    -- operational state owned by this platform (holds, cases, metrics)
CREATE SCHEMA agent;  -- the ONLY surface the agent runtime can reach: masked views + functions
CREATE SCHEMA eval;   -- answer keys for offline evaluation; never granted to the agent

CREATE TABLE core.properties (
  property_code                  text PRIMARY KEY,
  property_name                  text NOT NULL,
  city                           text NOT NULL,
  state                          text NOT NULL,
  market_type                    text NOT NULL,
  total_rooms                    int  NOT NULL CHECK (total_rooms > 0),
  accessible_rooms               int  NOT NULL DEFAULT 0,
  meeting_space_sqft             int,
  max_meeting_capacity           int,
  group_auto_approve_max_rooms   int  NOT NULL CHECK (group_auto_approve_max_rooms > 0),
  max_discount_auto_approve_pct  numeric(5,2) NOT NULL CHECK (max_discount_auto_approve_pct BETWEEN 0 AND 100),
  general_manager                text,
  notes                          text,
  latitude                       double precision,
  longitude                      double precision
);

-- Room classes: 1 = Standard / Accessible, 2 = Deluxe, 3 = Suite (used for upgrade ladders).
CREATE TABLE core.property_room_types (
  property_code  text NOT NULL REFERENCES core.properties ON DELETE CASCADE,
  room_type      text NOT NULL,
  room_class     smallint NOT NULL CHECK (room_class BETWEEN 1 AND 3),
  room_count     int NOT NULL CHECK (room_count >= 0),
  base_rate      numeric(10,2) CHECK (base_rate IS NULL OR base_rate > 0),  -- NULL = quarantined / unknown
  rate_source    text NOT NULL,
  PRIMARY KEY (property_code, room_type)
);

CREATE TABLE core.property_blackouts (
  property_code  text NOT NULL REFERENCES core.properties ON DELETE CASCADE,
  start_date     date NOT NULL,
  end_date       date NOT NULL,          -- inclusive
  reason         text,
  PRIMARY KEY (property_code, start_date),
  CHECK (end_date >= start_date)
);

-- Structured rules extracted (human-reviewed) from the free-text property notes.
-- The agent never interprets notes at runtime; it applies these rows.
CREATE TABLE core.property_rules (
  rule_id        serial PRIMARY KEY,
  property_code  text NOT NULL REFERENCES core.properties ON DELETE CASCADE,
  rule_type      text NOT NULL CHECK (rule_type IN (
                   'lead_time', 'seasonal_discount_cap', 'weekend_preference',
                   'seasonal_rate_advisory', 'youth_insurance_required',
                   'route_over_rooms', 'selling_point')),
  severity       text NOT NULL CHECK (severity IN ('hard', 'review', 'condition', 'advisory')),
  params         jsonb NOT NULL DEFAULT '{}',
  description    text NOT NULL,
  source_text    text NOT NULL            -- verbatim note the rule was derived from
);

CREATE TABLE core.guests (
  guest_id          text PRIMARY KEY,
  first_name        text NOT NULL,
  last_name         text NOT NULL,
  email             text,
  phone             text,
  loyalty_tier      text NOT NULL DEFAULT 'None'
                    CHECK (loyalty_tier IN ('None', 'Silver', 'Gold', 'Platinum')),
  loyalty_points    int NOT NULL DEFAULT 0,
  member_since      int,
  marketing_opt_in  boolean NOT NULL DEFAULT false
);

CREATE TABLE core.reservations (
  reservation_id     text PRIMARY KEY,
  guest_id           text NOT NULL REFERENCES core.guests,
  property_code      text NOT NULL REFERENCES core.properties,
  check_in           date NOT NULL,
  check_out          date NOT NULL,
  room_type          text NOT NULL,
  rate_plan          text NOT NULL,
  nightly_rate       numeric(10,2) NOT NULL CHECK (nightly_rate >= 0),
  total_nights       int NOT NULL,
  status             text NOT NULL CHECK (status IN
                       ('Confirmed', 'Checked-in', 'Checked-out', 'Cancelled', 'No-show')),
  payment_last4      text,                -- tokenized card reference only; never a PAN
  special_requests   text,
  internal_notes     text,
  source             text NOT NULL DEFAULT 'pms_export',
  created_at         timestamptz NOT NULL DEFAULT now(),
  cancelled_at       timestamptz,
  CHECK (check_out > check_in)
);
CREATE INDEX reservations_guest_idx ON core.reservations (guest_id);
CREATE INDEX reservations_stay_idx  ON core.reservations (property_code, check_in, check_out);

CREATE TABLE core.policy_sections (
  section_no  int PRIMARY KEY,
  title       text NOT NULL,
  body        text NOT NULL,
  keywords    text NOT NULL DEFAULT '',   -- curated synonyms ("dog" → pets) to help retrieval
  search      tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', title), 'A') ||
                setweight(to_tsvector('english', keywords), 'A') ||
                setweight(to_tsvector('english', body), 'B')) STORED
);
CREATE INDEX policy_sections_search_idx ON core.policy_sections USING gin (search);

CREATE TABLE core.group_inquiries (
  inquiry_id               text PRIMARY KEY,
  date_received            date NOT NULL,
  received_via             text NOT NULL DEFAULT 'web_portal',  -- web_portal | email
  company_name             text,
  contact_name             text,
  contact_email            text,
  contact_phone            text,
  event_type               text,
  preferred_property_code  text REFERENCES core.properties,
  alternate_property_ok    boolean,
  arrival_date             date,
  departure_date           date,
  nights                   int,
  rooms_requested_raw      text,
  rooms_requested          int,
  rooms_approximate        boolean NOT NULL DEFAULT false,
  room_type_preference     text,
  requested_discount_pct   numeric(5,2),
  stated_budget_per_night  numeric(10,2),
  meeting_space_needed     boolean,
  meeting_capacity_needed  int,
  special_requests         text,
  raw_text                 text,          -- original email body for email intake
  created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE core.data_quality_issues (
  issue_id     serial PRIMARY KEY,
  source_file  text NOT NULL,
  record_key   text NOT NULL,
  field        text NOT NULL,
  raw_value    text,
  issue        text NOT NULL,
  action       text NOT NULL,
  detected_at  timestamptz NOT NULL DEFAULT now()
);

-- The inquiries CSV ships a "notes" column that is reviewer commentary ("good test of whether
-- the candidate's agent..."). It is an answer key, so it lives here and the agent never sees it.
CREATE TABLE eval.group_inquiry_expectations (
  inquiry_id  text PRIMARY KEY,
  expected    text NOT NULL
);
