# Supabase connection, later

Supabase is PostgreSQL hosting here. SQLAlchemy connects from the Python server; the browser never receives a database password or Supabase service key. Hosting the database does not host this Python app.

1. Create a school-approved Supabase project when ready. Do not upload real staff data during the local demo.
2. Copy a direct connection or **session pooler** URI from Connect. The session pooler works where direct IPv6 is unavailable. Use the psycopg driver prefix `postgresql+psycopg://` and enforce SSL via `?sslmode=require`. URL-encode special characters in the password. Put the complete URL in local `.env` as `DATABASE_URL`; never in source control. Use only the actual project-provided connection details.
3. This app uses the private `school_checkin` schema via PostgreSQL `search_path`. Never add that schema to the Supabase Data API's exposed schemas. Run explicit provisioning:

   ```sh
   uv run --env-file .env python -m app.setup init-postgres
   ```

   This creates the initial tables and revokes access from PUBLIC, anon, and authenticated. Schema changes after initial provisioning need explicit reviewed migrations; `create_all` does not upgrade existing tables. Production should use a dedicated restricted database role for the application; provisioning should use a separate role.
4. Run the Python app with that URL; register fictional teachers again. This does **not** migrate an existing SQLite roster/history automatically. Retain the local database until a separately tested migration is complete.
5. Before using real staff, verify HTTPS, role isolation, the API access boundaries, private schema exposure, concurrent scans, idempotent retries, backups/restores, and both physical scanners. Current verification covers SQLite and local PostgreSQL 16; no hosted Supabase project has been connected or provisioned. If upgrading a prior pilot database, review and create the additive `office_users` and `office_sessions` tables before starting the new version; this change does not rewrite teacher records.

For an existing PostgreSQL pilot, absence coverage requires the reviewed
[additive migration](migrations/2026-10-07-absence-coverage.sql) before running
the new application. Take a database backup, review the two new tables and
grants, and apply the SQL with the provisioning role in a transaction. It leaves
existing roster, scan events, and sessions intact; it does not grant the
application role new access automatically. Grant that restricted role only the
required table and sequence privileges through the school's provisioning
process. Keep school_checkin outside the exposed Data API schemas. Hosted
Supabase execution remains unverified; CI verifies the migration on PostgreSQL
16 with existing attendance records.

Multi-day plans then require the reviewed
[series migration](migrations/2026-10-08-absence-series.sql), which adds one
nullable `series_id` column and index to `teacher_absences`. Apply migrations in
filename order. Existing single-day entries keep a null series and work as before.
CI applies both migrations in order to a database with existing attendance.

Fresh provisioning through init-postgres creates all model tables. SQLite
locally creates missing tables on startup and adds the nullable `series_id`
column to an earlier local file. PostgreSQL never upgrades columns automatically.
To roll back the app, retain the added tables, column, and coverage history and
revert the application commit; the earlier version ignores `series_id`.

Sources researched for this design:

- [Supabase: Using SQLAlchemy](https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT)
- [Supabase: Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [SQLAlchemy PostgreSQL dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)
- [Zebra USB device types](https://docs.zebra.com/us/en/scanners/general/sm72-ig/usb-interface/usb-parameter-defaults/usb-device-type-.html)
- [Zebra Enter suffix](https://docs.zebra.com/us/en/scanners/general/sm72-ig/user-preferences-and-miscellaneous-options/miscellaneous-scanner-parameters/enter-key.html)

The Zebra examples document the connection approach; use the actual scanner's manual rather than blindly scanning configuration barcodes for a different model.
