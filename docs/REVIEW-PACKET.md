Opened by an AI agent (GPT-6) under Prahaas's supervision.

## What

A local staff check-in pilot replaces the paper workflow with printable QR badges, two authenticated scanner stations, and an office dashboard. Office staff can see current recorded presence, choose a past time, review history, export CSV, replace badges, and correct missed scans with an audit reason.

## Why

Prahaas: "teachers have to check in by siging a sheet of paper in the front of the school" and "we need to build out a cool dashbaord to say whose in teh school and whose not in the school at ac eratin time".

The repository was empty. The missing architecture was a shared source of truth for two front-office computers, rather than independent lists of signatures.

## How

A USB keyboard-mode scanner decodes a QR badge and types its random token into the station form. The browser sends token + explicit IN/OUT + request UUID to FastAPI. SQLAlchemy looks up the token's hash, locks the teacher state, applies the direction, and writes the audit event in one transaction. The office dashboard reads that shared state every five seconds; historical snapshots replay status-changing events through the selected time. Both stations share one server/database.

Read `app/main.py` (API/auth/transaction), `app/models.py` (source of truth), `app/static/app.js` (scanner retry/dashboard), and `README.md` (run/two-station setup). The key concept to own is **explicit direction + atomic state and audit + stable retry ID**: a duplicate scan cannot reverse presence, and a retry cannot create another audit event.

## Done conditions

- [x] Register fictional teacher, generate printable QR image.
- [x] Two authenticated stations share IN/OUT state and history.
- [x] Duplicate scans, concurrent arrivals, and lost-response retries preserve state.
- [x] Office live/past presence, history, and CSV export work through API boundaries.
- [x] Local setup, staged rollout, hosted database instructions, and recovery are documented.

## Behavior to review

Repeated scans are logged without changing state. No automatic overnight reset; missed departures require a later OUT scan or reasoned office correction. Outside includes staff who have never scanned. Historical views use current names and IDs and include staff registered by that time, even if currently inactive. Access is a supervised-pilot key model, not production SSO or individual administrator identities.

## Verification

- `uv run --extra dev pytest -q`: **16 passed**. Covers station sharing, repeated scans, stale response retries after departure, conflicting request IDs, unknown badges, auth isolation, badge revocation, deactivation, audited corrections, historical presence, concurrent station arrivals/retries, CSV escaping/UTC, input/QR validation, security headers, and distinct keys.
- `node --check app/static/app.js`: passed.
- `uv sync --extra dev --locked`: passed.
- Local actual HTTP service and in-app browser: office sign-in, teacher registration (DEMO-009), rendered QR image (370 px natural width), scanner 1 IN, same badge repeat IN, scanner 2 OUT, unknown badge rejection, subsequent valid IN, and shared dashboard recorded state/history verified.
- Desktop light UI rendered at 1280 px; screenshot in `docs/screenshots/dashboard-desktop.png`. A requested 390 px browser viewport override did not take effect in this environment, so mobile rendering remains a manual check.
- Physical scanner input, physical badge printing, and hosted PostgreSQL/Supabase are **not verified**. No real teachers, passwords, badge files, or attendance data are committed. CI status is tracked on the draft PR.
- One dependency deprecation warning from Starlette's HTTPX TestClient; all assertions pass. No baseline test suite existed.

## Collision zones

New API, SQLAlchemy schema, frontend, dependency lock, and initial provisioning command. One implementation branch/worktree; no other agents. Initial schema provisioning is provided; later upgrades need reviewed database migrations. This initial end-to-end app is larger than a normal small bug fix because the source repository was empty.

## Manual checks

Identify scanner model; use its own HID/Enter instructions. Print badges and test actual scan distance/speed and laminated cards. Run both computers against one server. Test server interruption/retry and office correction. Check the narrow layout. Before hosted use: PostgreSQL concurrency, restricted role/schema, HTTPS, backups/restore, school-approved access and retention, and individual office authentication.

## Out of scope

Supabase provisioning/deployment, importing a real staff roster, batch badge printing, existing SQLite migration to PostgreSQL, offline queuing, SSO, fine-grained admin attribution, retention automation, payroll/absence decisions, student tracking, and emergency-accountability guarantees.

## Recovery

Stop the Python server to stop scans; return temporarily to the paper sheet. Back up `data/checkin.db` using SQLite's backup API (or stop the server and copy the entire database safely). Keep `.env` outside Git and access-controlled. Correct a missed scan with an audited office correction; replace a lost badge and print its replacement. To undo the pilot, revert the implementation commit; retain the database/keys until records are intentionally handled. Never delete history as a routine correction.

## Human review / merge

<!-- Self-merge justification: intentionally left for human review; agent must not self-merge. -->
- [x] Documentation updated.
- [x] Focused automated checks pass locally.
- [x] Desktop real surface observed.
- [ ] Physical devices and narrow layouts verified.
- [ ] CI completed and inspected (see PR).
- [ ] Prahaas reads diff and explains the invariant.
- [ ] Prahaas marks ready and merges when appropriate.
