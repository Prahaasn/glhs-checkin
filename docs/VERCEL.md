# Hosted check-in app

Open https://glhs-checkin.vercel.app on each Windows scanner computer or office
computer. Vercel serves the existing FastAPI app, browser screens, and API at the
same HTTPS origin. Supabase stores the private `school_checkin` database. The
Mac does not need to run for this hosted configuration to work.

## Deployment configuration

`pyproject.toml` selects `app.hosted:app`. The hosted entrypoint refuses SQLite,
requires `sslmode=verify-full`, validates the database CA certificate, and writes
that public certificate to a temporary runtime file. It then uses the existing
app factory, including its production key validation and host allowlist.

The Vercel project is `glhs-checkin` under `prahaas-7509s-projects`, in `iad1`.
Production environment variables are managed privately in Vercel:

- `DATABASE_URL`: restricted `glhs_checkin_app` role through Supabase's IPv4
  transaction pooler on port 6543, with `sslmode=verify-full` and a connection timeout.
- `SUPABASE_CA_CERT`: the project's database CA certificate in PEM form.
- `ADMIN_KEY`, `STATION_1_KEY`, `STATION_2_KEY`: distinct existing server keys.
- `ALLOWED_HOSTS`: `glhs-checkin.vercel.app`. The platform's exact `VERCEL_URL`
  is also allowed so a staged production deployment can be verified.

No database credentials go to frontend code. The upload allowlist includes only
application code/static files, the dependency manifests, and deployment config.
Local `.env`, data, databases, tests, and account handoff files are excluded.
There is no Git autodeployment; deploy reviewed changes explicitly.

```sh
vercel deploy --prod --skip-domain --scope prahaas-7509s-projects
# Verify the resulting deployment, then promote that exact URL:
vercel promote DEPLOYMENT_URL --scope prahaas-7509s-projects
```

Vercel instances use one persistent database connection plus one overflow
connection; office sign-in briefly needs two sessions. Supabase transaction
pooling releases database connections after each transaction. Prepared statements
remain disabled. The role's global ten-connection limit remains intact; saturation
returns a retryable 503. This is different from the local single-process
five-plus-three session-pool configuration, which remains unchanged.
The role's provisioned `search_path` is `school_checkin`.

## Sign-in and verification

Office staff use a named username and password. Each scanner uses its own station
key. Station 1 records arrivals and station 2 records departures in this revision.
The office and scanner sessions use HttpOnly, Secure, SameSite=Strict cookies
restricted to `/api`. Server-side sessions persist in Supabase between invocations.

Verify `/api/health`, office sign-in/read/logout, both station sign-ins, station
isolation from office routes, rejection of unrecognized badge codes, and rejection
of cross-origin writes. Never run the pytest fixtures against the hosted database.
Staff/scan history remain empty until the approved roster and badges are prepared.
Physical scanner/print testing and school approval remain before operational use.

## Limits and recovery

This is a connected pilot, not a claim of a completed school rollout. Failure
rate limits are per warm Python instance, not a distributed account lockout.
Observe latency and database capacity under the actual two-station workload.
The app has no automatic hosted backup setup or school holiday calendar.

If a deployment is faulty, promote a previous verified deployment. Promoting the
initial frontend-only deployment restores the login screen but disables its API.
Application rollback never deletes Supabase records. Revoke compromised station
keys in Vercel and redeploy; disable office users or reset their passwords through
the existing private administrative setup commands. Reverting database providers
requires a separate reviewed data export; do not silently fall back to SQLite.

References: [Vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi),
[Supabase connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres).
