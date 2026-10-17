-- Fresh hosted database only. Keep separate from upgrades for existing databases.
-- Fails rather than modifying an existing schema or role.

-- Tables compiled from app/models.py at d2d4d5d. Apply once as the provisioning account.

-- The runtime role starts NOLOGIN; its password is configured privately after provisioning.

CREATE ROLE glhs_checkin_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 10;

CREATE SCHEMA school_checkin;

REVOKE ALL ON SCHEMA school_checkin FROM PUBLIC, anon, authenticated;

GRANT USAGE ON SCHEMA school_checkin TO glhs_checkin_app;

ALTER ROLE glhs_checkin_app SET search_path = school_checkin;

CREATE TABLE school_checkin.access_sessions (
	token_hash VARCHAR(64) NOT NULL,
	role VARCHAR(8) NOT NULL,
	station VARCHAR(32),
	expires_at INTEGER NOT NULL,
	PRIMARY KEY (token_hash)
);

CREATE INDEX ix_school_checkin_access_sessions_expires_at ON school_checkin.access_sessions (expires_at);

CREATE TABLE school_checkin.office_users (
	id SERIAL NOT NULL,
	username VARCHAR(40) NOT NULL,
	display_name VARCHAR(80) NOT NULL,
	password_hash VARCHAR(160) NOT NULL,
	active BOOLEAN NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (username)
);

CREATE TABLE school_checkin.teachers (
	id SERIAL NOT NULL,
	teacher_id VARCHAR(80) NOT NULL,
	name VARCHAR(120) NOT NULL,
	badge_hash VARCHAR(64) NOT NULL,
	created_at INTEGER NOT NULL,
	active BOOLEAN NOT NULL,
	inside BOOLEAN NOT NULL,
	last_seen INTEGER,
	badge_issued_at INTEGER,
	PRIMARY KEY (id),
	UNIQUE (teacher_id),
	UNIQUE (badge_hash)
);

CREATE TABLE school_checkin.office_sessions (
	token_hash VARCHAR(64) NOT NULL,
	user_id INTEGER NOT NULL,
	PRIMARY KEY (token_hash),
	FOREIGN KEY(user_id) REFERENCES school_checkin.office_users (id)
);

CREATE INDEX ix_school_checkin_office_sessions_user_id ON school_checkin.office_sessions (user_id);

CREATE TABLE school_checkin.scan_events (
	id SERIAL NOT NULL,
	teacher_pk INTEGER NOT NULL,
	request_id VARCHAR(36) NOT NULL,
	direction VARCHAR(3) NOT NULL,
	station VARCHAR(32) NOT NULL,
	occurred_at INTEGER NOT NULL,
	changed BOOLEAN NOT NULL,
	reason VARCHAR(240),
	PRIMARY KEY (id),
	FOREIGN KEY(teacher_pk) REFERENCES school_checkin.teachers (id),
	UNIQUE (request_id)
);

CREATE INDEX ix_school_checkin_scan_events_occurred_at ON school_checkin.scan_events (occurred_at);

CREATE INDEX ix_school_checkin_scan_events_teacher_pk ON school_checkin.scan_events (teacher_pk);

CREATE TABLE school_checkin.teacher_absences (
	id SERIAL NOT NULL,
	teacher_pk INTEGER NOT NULL,
	day DATE NOT NULL,
	substitute_name VARCHAR(120),
	cancelled BOOLEAN NOT NULL,
	version INTEGER NOT NULL,
	updated_at INTEGER NOT NULL,
	updated_by INTEGER,
	series_id VARCHAR(36),
	PRIMARY KEY (id),
	FOREIGN KEY(updated_by) REFERENCES school_checkin.office_users (id),
	FOREIGN KEY(teacher_pk) REFERENCES school_checkin.teachers (id),
	UNIQUE (teacher_pk, day)
);

CREATE INDEX ix_school_checkin_teacher_absences_day ON school_checkin.teacher_absences (day);

CREATE INDEX ix_school_checkin_teacher_absences_series_id ON school_checkin.teacher_absences (series_id);

CREATE INDEX ix_school_checkin_teacher_absences_teacher_pk ON school_checkin.teacher_absences (teacher_pk);

CREATE TABLE school_checkin.absence_changes (
	id SERIAL NOT NULL,
	absence_pk INTEGER NOT NULL,
	version INTEGER NOT NULL,
	action VARCHAR(12) NOT NULL,
	substitute_name VARCHAR(120),
	cancelled BOOLEAN NOT NULL,
	occurred_at INTEGER NOT NULL,
	actor_user_id INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY(absence_pk) REFERENCES school_checkin.teacher_absences (id),
	FOREIGN KEY(actor_user_id) REFERENCES school_checkin.office_users (id),
	UNIQUE (absence_pk, version)
);

CREATE INDEX ix_school_checkin_absence_changes_absence_pk ON school_checkin.absence_changes (absence_pk);

ALTER TABLE school_checkin.teachers ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_runtime ON school_checkin.teachers TO glhs_checkin_app USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON school_checkin.teachers TO glhs_checkin_app;

ALTER TABLE school_checkin.scan_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_runtime ON school_checkin.scan_events TO glhs_checkin_app USING (true) WITH CHECK (true);

GRANT SELECT, INSERT ON school_checkin.scan_events TO glhs_checkin_app;

ALTER TABLE school_checkin.office_users ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_runtime ON school_checkin.office_users TO glhs_checkin_app USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON school_checkin.office_users TO glhs_checkin_app;

ALTER TABLE school_checkin.access_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_runtime ON school_checkin.access_sessions TO glhs_checkin_app USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, DELETE ON school_checkin.access_sessions TO glhs_checkin_app;

ALTER TABLE school_checkin.office_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_runtime ON school_checkin.office_sessions TO glhs_checkin_app USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, DELETE ON school_checkin.office_sessions TO glhs_checkin_app;

ALTER TABLE school_checkin.teacher_absences ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_runtime ON school_checkin.teacher_absences TO glhs_checkin_app USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON school_checkin.teacher_absences TO glhs_checkin_app;

ALTER TABLE school_checkin.absence_changes ENABLE ROW LEVEL SECURITY;

CREATE POLICY app_runtime ON school_checkin.absence_changes TO glhs_checkin_app USING (true) WITH CHECK (true);

GRANT SELECT, INSERT ON school_checkin.absence_changes TO glhs_checkin_app;

REVOKE ALL ON ALL TABLES IN SCHEMA school_checkin FROM PUBLIC, anon, authenticated;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA school_checkin FROM PUBLIC, anon, authenticated;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA school_checkin TO glhs_checkin_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA school_checkin REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;

ALTER DEFAULT PRIVILEGES IN SCHEMA school_checkin REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
