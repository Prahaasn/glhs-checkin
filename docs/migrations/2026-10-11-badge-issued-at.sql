-- Reviewed additive migration for the setup checklist and batch badge printing.
-- Apply with the provisioning role after 2026-10-08-absence-series.sql and
-- before deploying the version that records when each badge was issued.
-- Existing staff keep a NULL badge_issued_at ("no badge on record"); any badge
-- they already carry keeps working until the office issues a new one.
BEGIN;
ALTER TABLE school_checkin.teachers ADD COLUMN badge_issued_at INTEGER;
COMMIT;
