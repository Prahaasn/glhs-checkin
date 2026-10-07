-- Reviewed additive migration for multi-day absence plans.
-- Apply with the provisioning role after 2026-10-07-absence-coverage.sql and
-- before deploying the version that plans several school days at once.
-- Existing single-day entries keep a NULL series_id and behave as before.
BEGIN;
ALTER TABLE school_checkin.teacher_absences ADD COLUMN series_id VARCHAR(36);
CREATE INDEX ix_teacher_absences_series_id ON school_checkin.teacher_absences(series_id);
COMMIT;
