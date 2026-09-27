Opened by an AI agent (GPT-6) under Prahaas's supervision.

## What

A local staff badge check-in pilot now supports the complete official Green Level directory import, a searchable/paged presence dashboard, and separate Inside, Outside, and Not recorded states. Two station computers use one SQLAlchemy database; the office can issue QR badges, see current/past recorded presence, export history, and make reasoned corrections.

The local school dataset contains **141 staff**, all initially Not recorded, with **zero attendance events**. The real roster and database are excluded from the public repository. The original fictional demo database is separately preserved.

## Why

Prahaas: "go through green level higihschool staff directory and put a.l the staffa nmes in" and "saftey is a huge thing it needs to be super safe".

The initial pilot had no roster import, counted never-scanned staff as Outside, kept raw access keys in browser sessionStorage, and lacked request/auth throttling. These gaps could create a false picture of presence and expose credentials on a shared computer.

## How

The official directory importer verifies school identity, sequential page ranges, a stable total, and unique directory IDs before an atomic import. It follows Finalsite's actual element pagination rather than static page URLs. Existing records/badges/state are preserved; mismatched IDs/names abort. `DIR-…` IDs are public-directory identifiers, not employee IDs. Imported people have no usable badge until explicitly issued by the office.

A scanner decodes a QR token; the browser submits explicit IN/OUT with a stable request UUID. SQLAlchemy locks the teacher record and saves status/history in one transaction. The first scan establishes a known state; no scan means Not recorded. Browser clients exchange enrollment keys for expiring hashed database sessions using HttpOnly SameSite=Strict cookies (Secure over HTTPS). Raw keys are removed from browser storage. Pending scan payload/UUID survives a tab reload until confirmed.

Read `app/main.py` (sessions/auth and scan transaction), `app/roster.py` (source/import invariants), `app/security.py` (throttling/body limit), and `tests/test_checkin.py` (same API boundary under SQLite/PostgreSQL). The concept to own: **directory membership establishes a roster entry; only a recorded scan or office correction establishes recorded presence**.

## Observable done conditions

- [x] All 141 official directory entries verified and loaded locally; no contacts or real roster in public Git.
- [x] Search/paging and Inside/Outside/Not recorded counts work without inventing presence.
- [x] Session expiry/revocation, station isolation, input privacy, request limits, and scan/retry invariants have regression coverage.
- [x] Real desktop browser exercises registration/scans, roster paging/search, default station OUT, outage/reload/retry, and stale display.
- [x] Branch pushed to the existing draft PR; CI status recorded below after completion.

## Behavior changes

No-scan teachers display Not recorded instead of Outside; the API exposes inside=null for this unknown state. Office corrections require an explicit IN/OUT choice. The first OUT scan establishes an OUT observation. Station 2 defaults to OUT; direction is remembered per station/tab. The dashboard marks failed refreshes Stale and shows dates on older last changes. Office sessions expire in 30 minutes; stations in 12 hours. Logging out revokes the database session; closing a tab alone does not. Active sessions survive a server restart.

Repeated IN/OUT does not reverse status. Network failures do not show success. Pending requests retain their UUID across reload for safe retry. Historical views use current staff names/IDs. No automatic midnight checkout: forgotten scans still require physical/office verification.

## Verification

- `TEST_DATABASE_URL=<local PostgreSQL test database> uv run --extra dev pytest -q`: **68 passed**, one dependency TestClient deprecation warning. Same API cases run on SQLite and PostgreSQL 16, including simultaneous arrivals/retries.
- Tests cover directory completeness/wrong school/duplicate IDs/unsafe pagination, atomic/dry/idempotent imports, unrecorded state, session role isolation/expiry/restart/revocation, Secure/HttpOnly/SameSite cookies, throttling, host/origin checks, chunked body caps, generic validation/database errors, badge revocation, corrections, histories, and CSV escaping.
- `node --check app/static/app.js` and `git diff --check`: passed.
- Independently read all 16 official pages in the in-app browser and HTTP fetcher: **141 unique IDs and normalized names matched**, final page 136–141. Dry-run added 141 with rollback; actual import added 141; repeat import skipped all 141. School database: 141 teachers / 141 no scan / 0 events.
- Real browser: school roster counters 0 Inside / 0 Outside / 141 Not recorded; search for the principal and next/previous paging verified. No real staff scans were fabricated.
- Isolated fictional browser/database: station 2 defaults OUT; stopped server → scan showed failure; restarted and reloaded → previous request offered for retry; retry confirmed; repeat OUT stayed OUT; Lock returned to sign-in. Stale display, clean logout, and current preview verification recorded during final checks.
- Current desktop light UI verified at 1280 and 1600 px. Public screenshot uses fictional staff only. Narrow viewport overrides did not apply in this in-app browser; narrow layouts remain a manual check.
- GitHub CI now provisions isolated PostgreSQL 16 and runs both database variants. Final run results are recorded on the PR body.
- Hosted Supabase, actual scanner/printed badge behavior, HTTPS deployment, individual office SSO, and school sign-off are **not verified**.

## Collision zones

New app/API/frontend/schema/dependency lock and roster importer. Added `access_sessions` table; existing teacher columns are unchanged. SQLite startup adds this table. Existing hosted pilots must rerun additive provisioning or use an explicit reviewed migration. One implementation branch/worktree and no parallel agents. The initial application is larger than a routine patch because the repository began empty.

## Manual checks / remaining limits

Test both physical scanners and real printed cards. Configure exact trusted hosts, HTTPS, restricted database role/private schema, distributed limiting if scaling beyond one worker, backups/restore, approved access/retention and individual office identities. Reconcile public directory IDs with school-issued IDs and actual current staff. Copied badges and missed scans cannot prove physical presence; use school-approved emergency procedures.

The failed-attempt limiter is bounded but process-local. Header API keys remain supported for trusted integrations. An office key is shared and therefore does not give individual correction attribution. Offline operation blocks scans instead of queuing them. A healthy backend cannot identify an unscanned departure.

## Out of scope

Live deployment/Supabase provisioning; employee ID reconciliation; bulk badge issuance; SSO/per-person audit identities; school-approved retention/backup automation; offline queuing; payroll/absence decisions; student tracking; emergency-accountability guarantees. No claims of zero security issues or production certification.

## Recovery

Stop the server and return to the paper workflow. Preserve `data/school.db`, the separate demo database, and `.env` outside Git; use SQLite's backup API or stop the server before copying. Revert the implementation branch to disable the app; retain records until the school decides retention. Imports can be dry-run first and never rotate existing badges, deactivate staff, or create attendance. Correct missed scans through audited office corrections; replace lost badges. If Lock cannot reach the server, keep the computer secured and retry after recovery—closing a tab does not prove revocation.

## Human ready / merge gate

<!-- Self-merge justification: intentionally left for human review; do not self-merge. -->
- [x] Docs, local tests, and desktop behavior verified.
- [ ] Final CI completed and inspected (recorded on PR when complete).
- [ ] Actual scanners, printing, hosted boundary, and narrow layouts verified.
- [ ] Prahaas reviews the four files and explains recorded vs physical presence.
- [ ] Prahaas marks ready and merges when appropriate.
