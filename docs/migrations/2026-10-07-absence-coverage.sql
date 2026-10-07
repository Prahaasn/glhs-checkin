-- Reviewed additive migration for an existing private school_checkin schema.
-- Apply with the provisioning role, before deploying absence coverage.
-- Existing teachers and office_users tables must already exist.
BEGIN;
CREATE TABLE school_checkin.teacher_absences (
    id SERIAL PRIMARY KEY,
    teacher_pk INTEGER NOT NULL REFERENCES school_checkin.teachers(id),
    day DATE NOT NULL,
    substitute_name VARCHAR(120),
    cancelled BOOLEAN NOT NULL,
    version INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    updated_by INTEGER REFERENCES school_checkin.office_users(id),
    UNIQUE (teacher_pk, day)
);
CREATE INDEX ix_teacher_absences_teacher_pk ON school_checkin.teacher_absences(teacher_pk);
CREATE INDEX ix_teacher_absences_day ON school_checkin.teacher_absences(day);
CREATE TABLE school_checkin.absence_changes (
    id SERIAL PRIMARY KEY,
    absence_pk INTEGER NOT NULL REFERENCES school_checkin.teacher_absences(id),
    version INTEGER NOT NULL,
    action VARCHAR(12) NOT NULL,
    substitute_name VARCHAR(120),
    cancelled BOOLEAN NOT NULL,
    occurred_at INTEGER NOT NULL,
    actor_user_id INTEGER REFERENCES school_checkin.office_users(id),
    UNIQUE (absence_pk, version)
);
CREATE INDEX ix_absence_changes_absence_pk ON school_checkin.absence_changes(absence_pk);
REVOKE ALL ON school_checkin.teacher_absences, school_checkin.absence_changes FROM PUBLIC;
REVOKE ALL ON SEQUENCE school_checkin.teacher_absences_id_seq, school_checkin.absence_changes_id_seq FROM PUBLIC;
DO $$
DECLARE role_name TEXT;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON school_checkin.teacher_absences, school_checkin.absence_changes FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON SEQUENCE school_checkin.teacher_absences_id_seq, school_checkin.absence_changes_id_seq FROM %I', role_name);
        END IF;
    END LOOP;
END $$;
COMMIT;
