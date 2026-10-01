# Backend API

Base URL for local development: `http://127.0.0.1:8317/api`.

Office browsers POST `/office-session` with a named `username` and `password`; scanner browsers POST `/session` with `role: station` and `access_key`. Both receive an HttpOnly cookie. GET `/session` checks identity/expiry; DELETE `/session` revokes it. Office sessions last 30 minutes and station sessions 12 hours. The cookie is Secure on HTTPS. An administrator provisions named office accounts with `python -m app.setup add-user`; there is no public signup route. Trusted command-line integrations can still use headers: office routes require `X-Admin-Key`. Scanner routes require `X-Station-Key`, using the specific device's generated key. Keep keys in local `.env`; none are distributed in this repository. A station cannot list teachers, read attendance history, export records, or manage badges.

| Method | Route | Access | Behavior |
| --- | --- | --- | --- |
| GET | `/health` | Public | Database connectivity check |
| POST | `/office-session` | Public sign-in | Exchange a named office login for a session cookie |
| GET | `/station` | Station | Identify the authenticated station |
| POST | `/scans` | Station | Record explicit IN/OUT |
| GET | `/teachers` | Office | Current roster and recorded presence |
| POST | `/teachers` | Office | Register teacher and return a new badge token once |
| POST | `/teachers/{id}/badge` | Office | Replace badge; revoke old token |
| PATCH | `/teachers/{id}` | Office | Deactivate a checked-out teacher |
| POST | `/teachers/{id}/correction` | Office | Correct status with an audit reason |
| POST | `/badge-image` | Office | Generate a PNG QR image |
| GET | `/presence?at={epoch}` | Office | Recorded presence at a past Unix timestamp |
| GET | `/events` | Office | Latest 200 audit events |
| GET | `/export` | Office | Full history as CSV, timestamps in UTC |

`/events` and `/export` accept optional `since` (inclusive) and `until` (exclusive) Unix timestamps. Database primary key `id` and school-provided `teacher_id` are different fields; path routes use the primary key. Teacher IDs are strings, so leading zeroes are preserved. Deactivating an office user in the database invalidates their existing cookie on the next request.

## Register a teacher

`POST /teachers`:

```json
{"teacher_id":"T-001","name":"Example Teacher"}
```

Response: HTTP 201 with `id`, `teacher_id`, `name`, `active`, `inside`, `last_seen`, `presence`, and `badge_code`. The server stores only the badge code's SHA-256 hash. Print the returned code immediately, or replace the badge later. Duplicate teacher IDs return 409.

## Scan a badge

`POST /scans`:

```json
{
  "code":"the-token-from-the-printed-badge",
  "direction":"in",
  "request_id":"86b671ab-2e1c-4fca-8b66-3c1be8200257"
}
```

Generate a new UUID for each physical scan. The example UUID is illustrative; do not reuse it for new scans. The station identity comes from the authenticated key, not the request body.

Successful response fields: `name`, `inside`, `changed`, `direction`, `occurred_at`, and `message`. Times are server-generated Unix seconds. An IN scan for someone already inside returns `changed: false` and is recorded as a repeat. OUT follows the same rule.

If the response is lost or a server/network error makes the outcome uncertain, retry with **the same request UUID and payload**. The backend returns the original recorded result without changing current status again. That result describes the original scan, even if the teacher subsequently scanned in the opposite direction. Reusing a UUID for a different teacher, direction, station, or correction reason returns 409.

Unknown or inactive badges return 404. Authentication errors return 401. Invalid request fields return 422. The `presence` field is `in`, `out`, or `unrecorded`; `inside` is null when unrecorded and otherwise a boolean; an imported/new teacher is unrecorded until a scan or correction establishes status. The first OUT observation records a known OUT status.

A successful scanner beep alone does not prove server acceptance; require the application confirmation.

## QR rendering and corrections

`POST /badge-image` currently accepts the scan-shaped payload above and returns `image/png`; the direction and UUID are validated but no scan is recorded. The registration screen handles this automatically.

`POST /teachers/{id}/correction` accepts `direction`, a fresh `request_id`, and a `reason` of 3–240 characters. Corrections use the same atomic state/event transaction. Corrections made through named office sessions include that account's display name in the activity log; legacy administrator-key corrections show as `office`.

## Storage and rollout

SQLAlchemy stores teacher state and audit events in one database transaction. SQLite serializes writers; PostgreSQL locks each teacher row. The hosted path uses a private `school_checkin` schema and requires explicit provisioning. The API suite runs against both SQLite and local PostgreSQL 16, including in GitHub CI. Hosted Supabase and physical hardware remain separate verification steps. See [Supabase setup](SUPABASE.md).
