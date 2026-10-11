-- Reviewed additive migration for the setup checklist and batch badge printing.
-- Apply with the provisioning role after 2026-10-08-absence-series.sql and
-- before deploying the version that records when each badge was issued.
-- Staff added on the office screen or in a demo received a usable badge when
-- created, so they are backfilled with their creation time. Imported directory
-- staff (DIR-) received none and keep NULL ("no badge on record"); a badge an
-- imported person was given later keeps working until the office issues a new one.
BEGIN;
ALTER TABLE school_checkin.teachers ADD COLUMN badge_issued_at INTEGER;
UPDATE school_checkin.teachers SET badge_issued_at = created_at WHERE teacher_id NOT LIKE 'DIR-%';
COMMIT;
