-- 003_agent_surface.sql — the agent's entire view of the world.
-- Views run with owner privileges, so solstice_agent never needs (or gets) access to core.*.
SET LOCAL ROLE solstice_owner;

CREATE FUNCTION agent.mask_email(p text) RETURNS text IMMUTABLE LANGUAGE sql AS $$
  SELECT CASE WHEN p IS NULL OR position('@' IN p) = 0 THEN NULL
              ELSE left(p, 1) || '***@' || split_part(p, '@', 2) END
$$;

CREATE FUNCTION agent.mask_phone(p text) RETURNS text IMMUTABLE LANGUAGE sql AS $$
  SELECT CASE WHEN p IS NULL OR length(regexp_replace(p, '\D', '', 'g')) < 4 THEN NULL
              ELSE '***-***-' || right(regexp_replace(p, '\D', '', 'g'), 4) END
$$;

CREATE VIEW agent.v_properties AS
SELECT property_code, property_name, city, state, market_type, total_rooms, accessible_rooms,
       meeting_space_sqft, max_meeting_capacity, group_auto_approve_max_rooms,
       max_discount_auto_approve_pct, general_manager, notes, latitude, longitude
  FROM core.properties;

CREATE VIEW agent.v_room_types AS
SELECT property_code, room_type, room_class, room_count, base_rate
  FROM core.property_room_types;

CREATE VIEW agent.v_blackouts AS SELECT * FROM core.property_blackouts;
CREATE VIEW agent.v_property_rules AS
SELECT rule_id, property_code, rule_type, severity, params, description FROM core.property_rules;

-- Guests: no full last name, masked contact details, no marketing flags.
CREATE VIEW agent.v_guests AS
SELECT guest_id, first_name, left(last_name, 1) || '.' AS last_initial,
       agent.mask_email(email) AS email_masked, agent.mask_phone(phone) AS phone_masked,
       loyalty_tier, loyalty_points, member_since
  FROM core.guests;

-- Reservations: card data collapses to a boolean. internal_notes are exposed as
-- staff_guidance (the agent must follow them but never quote them; enforced in code).
CREATE VIEW agent.v_reservations AS
SELECT r.reservation_id, r.guest_id, r.property_code, p.property_name, p.city, p.state,
       r.check_in, r.check_out, r.room_type, r.rate_plan, r.nightly_rate, r.total_nights,
       r.status, (r.payment_last4 IS NOT NULL) AS card_on_file,
       r.special_requests, r.internal_notes AS staff_guidance, r.cancelled_at
  FROM core.reservations r JOIN core.properties p USING (property_code);

CREATE VIEW agent.v_policy_sections AS SELECT section_no, title, body FROM core.policy_sections;

CREATE VIEW agent.v_group_inquiries AS
SELECT inquiry_id, date_received, received_via, company_name, contact_name,
       agent.mask_email(contact_email) AS contact_email_masked,
       agent.mask_phone(contact_phone) AS contact_phone_masked,
       (contact_phone IS NOT NULL AND contact_phone <> '') AS has_phone,
       event_type, preferred_property_code, alternate_property_ok, arrival_date, departure_date,
       nights, rooms_requested_raw, rooms_requested, rooms_approximate, room_type_preference,
       requested_discount_pct, stated_budget_per_night, meeting_space_needed,
       meeting_capacity_needed, special_requests, raw_text, created_at
  FROM core.group_inquiries;

-- Per-night availability, net of sold rooms and active holds.
CREATE VIEW agent.v_inventory AS
SELECT property_code, room_type, stay_date, capacity, sold, held,
       capacity - sold - held AS available
  FROM ops.inventory_nights;

-- ---------------------------------------------------------------------------
-- Functions (SECURITY DEFINER = run as owner, with a pinned search_path).
-- ---------------------------------------------------------------------------

-- Front-desk style verification: confirmation number + last name, nothing else.
CREATE FUNCTION agent.verify_guest(p_reservation_id text, p_last_name text)
RETURNS TABLE (guest_id text, reservation_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, core AS $$
  SELECT r.guest_id, r.reservation_id
    FROM core.reservations r JOIN core.guests g USING (guest_id)
   WHERE upper(r.reservation_id) = upper(trim(p_reservation_id))
     AND lower(g.last_name) = lower(trim(p_last_name));
$$;

-- Policy retrieval: OR-of-lexemes full text search, ranked. Deterministic, no LLM.
CREATE FUNCTION agent.search_policy(p_query text, p_limit int DEFAULT 2)
RETURNS TABLE (section_no int, title text, body text, rank real)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, core AS $$
DECLARE v_q tsquery;
BEGIN
  SELECT to_tsquery('english', string_agg(lex, ' | '))
    INTO v_q FROM unnest(tsvector_to_array(to_tsvector('english', coalesce(p_query, '')))) AS lex;
  IF v_q IS NULL THEN RETURN; END IF;
  RETURN QUERY
    SELECT s.section_no, s.title, s.body, ts_rank_cd(s.search, v_q, 32)
      FROM core.policy_sections s
     WHERE s.search @@ v_q
     ORDER BY ts_rank_cd(s.search, v_q, 32) DESC, s.section_no
     LIMIT p_limit;
END $$;

CREATE FUNCTION agent.availability(p_property text, p_check_in date, p_check_out date)
RETURNS TABLE (room_type text, room_class smallint, base_rate numeric, min_available int, nights int)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, core, ops AS $$
  SELECT rt.room_type, rt.room_class, rt.base_rate,
         coalesce(min(i.capacity - i.sold - i.held), 0)::int,
         count(i.stay_date)::int
    FROM core.property_room_types rt
    LEFT JOIN ops.inventory_nights i
      ON i.property_code = rt.property_code AND i.room_type = rt.room_type
     AND i.stay_date >= p_check_in AND i.stay_date < p_check_out
   WHERE rt.property_code = p_property
   GROUP BY rt.room_type, rt.room_class, rt.base_rate
   ORDER BY rt.room_class, rt.room_type;
$$;

CREATE FUNCTION agent.place_hold(
  p_kind text, p_property text, p_room_type text, p_check_in date, p_check_out date,
  p_rooms int, p_ttl_minutes int, p_idempotency_key text, p_guest_id text, p_session_id text,
  p_inquiry_id text, p_nightly_rate numeric, p_quote jsonb)
RETURNS ops.holds LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, core, ops AS $$
  SELECT ops.place_hold(p_kind, p_property, p_room_type, p_check_in, p_check_out, p_rooms,
                        make_interval(mins => least(greatest(p_ttl_minutes, 1), 60 * 24 * 7)),
                        p_idempotency_key, p_guest_id, p_session_id, p_inquiry_id,
                        p_nightly_rate, p_quote);
$$;

CREATE FUNCTION agent.release_hold(p_hold_id uuid)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, ops AS $$
  SELECT ops.release_hold(p_hold_id, 'released');
$$;

CREATE FUNCTION agent.convert_hold(p_hold_id uuid, p_guest_id text, p_card_last4 text)
RETURNS ops.holds LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, core, ops AS $$
  SELECT ops.convert_hold(p_hold_id, p_guest_id, p_card_last4);
$$;

CREATE FUNCTION agent.expire_holds() RETURNS int
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, ops AS $$ SELECT ops.expire_holds(); $$;

-- Cancel only a reservation that belongs to the verified guest.
CREATE FUNCTION agent.cancel_reservation(p_reservation_id text, p_guest_id text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, core, ops AS $$
DECLARE v core.reservations;
BEGIN
  PERFORM 1 FROM core.reservations WHERE reservation_id = p_reservation_id AND guest_id = p_guest_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'reservation_not_found' USING ERRCODE = 'P0002'; END IF;
  v := ops.cancel_reservation(p_reservation_id);
  RETURN v.status;
END $$;

-- New guest profile for bookings made through the portal (no loyalty, no card PAN ever).
CREATE FUNCTION agent.upsert_portal_guest(p_first text, p_last text, p_email text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, core AS $$
DECLARE v_id text;
BEGIN
  SELECT guest_id INTO v_id FROM core.guests
   WHERE lower(email) = lower(p_email) AND lower(last_name) = lower(p_last) LIMIT 1;
  IF v_id IS NULL THEN
    v_id := 'G' || (20000 + (SELECT count(*) FROM core.guests))::text;
    INSERT INTO core.guests (guest_id, first_name, last_name, email) VALUES (v_id, p_first, p_last, p_email);
  END IF;
  RETURN v_id;
END $$;

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA agent, ops FROM PUBLIC;

GRANT USAGE ON SCHEMA agent TO solstice_agent, solstice_staff;
GRANT SELECT ON ALL TABLES IN SCHEMA agent TO solstice_agent, solstice_staff;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA agent TO solstice_agent, solstice_staff;

-- The agent may append to operational logs/queues, but never touches inventory directly.
GRANT USAGE ON SCHEMA ops TO solstice_agent;
GRANT SELECT, INSERT ON ops.service_requests, ops.escalations, ops.escalation_messages,
                        ops.group_proposals, ops.funnel_events, ops.turn_metrics,
                        ops.guardrail_events TO solstice_agent;
GRANT UPDATE (hold_ids, status, narrative, trace, latency_ms) ON ops.group_proposals TO solstice_agent;
GRANT SELECT ON ops.holds TO solstice_agent;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO solstice_agent;
GRANT INSERT ON core.group_inquiries TO solstice_agent;
GRANT USAGE ON SCHEMA core TO solstice_agent;

-- Staff: humans may see guest contact details to do their jobs, never card references.
GRANT USAGE ON SCHEMA core, ops TO solstice_staff;
GRANT SELECT ON core.properties, core.property_room_types, core.property_blackouts,
                core.property_rules, core.guests, core.policy_sections, core.group_inquiries,
                core.data_quality_issues TO solstice_staff;
GRANT SELECT (reservation_id, guest_id, property_code, check_in, check_out, room_type, rate_plan,
              nightly_rate, total_nights, status, special_requests, internal_notes, source,
              created_at, cancelled_at) ON core.reservations TO solstice_staff;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO solstice_staff;
GRANT UPDATE (status, assigned_to, resolution_note, resolved_at) ON ops.escalations TO solstice_staff;
GRANT UPDATE (status, decided_by, desk_note, decided_at) ON ops.service_requests TO solstice_staff;
GRANT UPDATE (status, reviewed_by, reviewed_at, review_note, hold_ids) ON ops.group_proposals TO solstice_staff;
GRANT INSERT ON ops.escalation_messages TO solstice_staff;
GRANT INSERT ON ops.funnel_events TO solstice_staff;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO solstice_staff;
