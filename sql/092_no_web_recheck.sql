-- 092: NO_WEB can be re-checked.
--
-- The live probe parked 38 firms as NO_WEB because robots.txt was blocked at the
-- edge or timed out. No policy was read, so no conclusion was possible, and one of
-- those sites answered 200 the next day. P1 no longer moves a lead on those
-- outcomes (decision D-026); the leads already parked need a way back so the
-- mapper can judge them again. NO_WEB -> DISCOVERED is that edge. Every other
-- state's edges are unchanged; NO_WEB is still reached on no domain or on a
-- published robots rule closing the site.

INSERT INTO lead_transition (from_state, to_state)
VALUES ('NO_WEB', 'DISCOVERED')
ON CONFLICT DO NOTHING;
