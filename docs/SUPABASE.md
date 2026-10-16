# Local app with a Supabase database

The Python server stays on this Mac at http://127.0.0.1:8317. SQLAlchemy connects
from that server to Supabase PostgreSQL; browsers receive app sessions, never a
database password or service key. The Mac and its internet connection must stay
on for the app to work. This configuration listens only on loopback.

## Connection

Keep the three distinct access keys in the ignored, private `.env`. Add a
`DATABASE_URL` using the **session pooler** details shown in Supabase Connect.
Use the `postgresql+psycopg://` driver and the dedicated app login, not the
project's `postgres` account. The pooler username is `APP_ROLE.PROJECT_REF`.
Session pooling supports this persistent Python server and IPv4 connections.

Download the server root certificate from **Database → Settings → SSL
configuration → Download certificate**. Store it locally, then use both
`sslmode=verify-full` and `sslrootcert` so the connection verifies the server's
identity. URL-encode the password and certificate path as URI components.

```dotenv
DATABASE_URL=postgresql+psycopg://APP_ROLE.PROJECT_REF:ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=verify-full&sslrootcert=ENCODED_ABSOLUTE_CERT_PATH&connect_timeout=10
ALLOWED_HOSTS=127.0.0.1,localhost,[::1]
```

Keep `.env` readable only by its owner (`chmod 600 .env`). Use the actual
project-provided host, region and certificate. Never commit credentials or put
this URL in frontend JavaScript. The app already selects the private
`school_checkin` schema, disables automatic prepared statements for pooler
compatibility, and checks pooled connections before reuse.

Start or restart from the configured checkout:

```sh
uv sync --locked
./'Start local app.command'
```

The launcher loads `.env` and binds to `127.0.0.1:8317`. Stop it with Ctrl+C in
its terminal before starting another copy. Set `GLHS_PORT` if that port is busy.
Office accounts and station keys work as described in the README. No cloud app
hosting is needed for this configuration.

## Fresh database provisioning

The reviewed [initial provisioning SQL](provisioning/20261016162205_hosted_initial_private_schema.sql)
creates all seven current model tables, indexes, a restricted `glhs_checkin_app`
role, grants and RLS policies. It fails if that schema or role already exists.
Apply it once with a separate provisioning account, in one transaction. It is
separate from `docs/migrations/`, which contains upgrades for existing pilots.

The new role starts with `NOLOGIN`. Enable its login and assign a strong generated
password privately through the provisioning connection; keep passwords out of
SQL migration history and shell arguments. Use only that restricted role in the
app's `.env`. Keep the provisioning credential out of the application process.
The older `app.setup init-postgres` command creates tables but does not install
these restricted-role grants or RLS policies; it is not a replacement for this
provisioning file.

The runtime role can read and update the app's operational state and append
history. It cannot create tables, delete staff, or update/delete scan and absence
audit history. RLS allows the trusted backend role; existing office/station
permissions remain enforced by FastAPI. This app does not use Supabase Auth.
`PUBLIC`, `anon`, and `authenticated` have no access to the private schema.
Never add `school_checkin` to the Data API's exposed schemas.

Changing `DATABASE_URL` does not copy a SQLite roster, history or office accounts.
Back up the old `.env` and SQLite file first. Transfer named office accounts only
through a controlled setup step; add staff and issue badges through the office
workflow when ready. The demo command intentionally refuses PostgreSQL. Run
rehearsals with `app.local_demo`, which uses a separate local SQLite database.

## Existing pilot upgrades

Do not apply fresh provisioning to an existing pilot. Back it up and review the
additive SQL in filename order:

- [Absence coverage](migrations/2026-10-07-absence-coverage.sql): adds planned
  absences and their audit history; preserves roster, scans and sessions.
- [Multi-day plans](migrations/2026-10-08-absence-series.sql): adds nullable
  `series_id` and its index. Existing single-day plans retain null series.
- [Badge issue dates](migrations/2026-10-11-badge-issued-at.sql): adds nullable
  `badge_issued_at`; imported directory staff retain “no badge on record.”

Apply upgrades with the provisioning role and review the app role's required
grants. PostgreSQL never upgrades existing columns automatically. To roll back
application code, retain the added tables, columns and history.

## Verification and recovery

Run the Python suite against SQLite and a **disposable local PostgreSQL 16**
database ending in `_test`. Never set `TEST_DATABASE_URL` to Supabase. The
provisioning regression verifies RLS, browser-role isolation, denied audit
rewrites, office/station sessions, attendance retries and coverage writes under
the restricted runtime role; its outer transaction rolls all setup back.

On October 16, 2026, the local app was connected to the GLHS project, its private
schema and certificate-verified session pooler. Live checks covered health,
office/station authentication, office reads, station isolation and logout. The
hosted staff roster/history were left empty; attendance writes were verified on
the disposable local database. Physical scanners, printing and school approval
remain before operational use.

To return to the previous SQLite pilot, stop the app, restore its backed-up
`.env`, and restart from the same checkout. Keep the hosted database intact:
new Supabase records do not automatically copy back to SQLite. Once real records
exist, plan and verify a data export before changing databases.

Sources:

- [Supabase connection methods and certificate verification](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase SQLAlchemy guidance](https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT)
- [Supabase API security](https://supabase.com/docs/guides/api/securing-your-api)
