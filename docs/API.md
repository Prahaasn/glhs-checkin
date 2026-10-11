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
| POST | `/teachers/{id}/badge` | Office | Issue a new badge once; revoke the old token |
| POST | `/badges/batch` | Office | Issue badges for up to 200 staff in one transaction |
| GET | `/setup` | Office | Read-only setup checklist |
| PATCH | `/teachers/{id}` | Office | Deactivate a checked-out teacher |
| POST | `/teachers/{id}/correction` | Office | Correct status with an audit reason |
| POST | `/badge-image` | Office | Generate a PNG QR image (kept for API clients) |
| GET | `/presence?at={epoch}` | Office | Recorded presence at a past Unix timestamp |
| GET | `/events` | Office | Latest 200 audit events |
| GET | `/export` | Office | Full history as CSV, timestamps in UTC |
| GET | `/absences?day=YYYY-MM-DD` | Office | Planned coverage for a school date; defaults to today in Eastern time |
| GET | `/absences/range?start=…&end=…` | Office | Active planned absences grouped by date for up to 62 days |
| POST | `/absences` | Office | Plan one or more school days for a teacher |
| PATCH | `/absences/{id}` | Office | Assign/reassign cover, cancel, or restore one day or this day and later days, with version checking |
| GET | `/absences/{id}/changes` | Office | Latest 50 coverage changes with office actor |
| GET | `/substitutes` | Office | Substitute names used on active plans in the last year, newest first |
| GET | `/attention` | Office | Today's exceptions with suggested reviewed actions (read-only) |

`/events` and `/export` accept optional `since` (inclusive) and `until` (exclusive) Unix timestamps. Database primary key `id` and school-provided `teacher_id` are different fields; path routes use the primary key. Teacher IDs are strings, so leading zeroes are preserved. Deactivating an office user in the database invalidates their existing cookie on the next request.

## Register a teacher

`POST /teachers`:

```json
{"teacher_id":"T-001","name":"Example Teacher"}
```

Response: HTTP 201 with `id`, `teacher_id`, `name`, `active`, `inside`, `last_seen`, `presence`, `badge_issued_at`, `badge_code`, `qr`, and `code128`. The server stores only the badge code's SHA-256 hash and the issue time. Print the returned code immediately, or issue a new badge later. Duplicate teacher IDs return 409.

`qr` is the QR symbol (medium error correction, 4-module quiet zone) as rows of `1` (dark) and `0` (light). `code128` is the Code 128 subset B symbol, start through stop, as bar (`1`) and space (`0`) modules without quiet zones; leave at least 10 light modules on each side when drawing it. Both encode `badge_code` exactly. `POST /teachers/{id}/badge` returns `id`, `name`, `teacher_id`, `badge_code`, `qr`, and `code128` for active staff.

`badge_issued_at` (Unix seconds, or null) records when the office last issued a usable badge. Imported directory staff (`DIR-` IDs) are null, "no badge on record", until the office issues one. Upgrading an earlier database fills in staff added on the office screen or in a demo with their creation time, because they received a usable badge then.

## Issue badges in a batch

`POST /badges/batch` accepts `teacher_pks` (1–200 distinct database IDs) and `reviewed_badges`, an object mapping each selected ID to the `badge_issued_at` the office reviewed (omitted or null means "no badge on record"). It locks those staff and either issues every badge or none. It returns 409, issuing nothing, if anyone selected is missing or inactive, or if anyone's current `badge_issued_at` differs from what was reviewed. That works like an absence version check: a screen that is out of date, for example because another desk issued a badge meanwhile, cannot revoke a badge the office never saw. A success returns `issued` (sorted by name, each with `id`, `name`, `teacher_id`, `badge_code`, `qr`, and `code128`), `replaced` (how many working badges were revoked), and `issued_at`.

Codes are returned only in this response and are not stored. If the response is lost, the new badges exist but their codes cannot be recovered: issue those badges again, which replaces them.

## Setup checklist

`GET /setup` is read-only. `steps` lists `office`, `roster`, `badges`, `stations`, `test_scan`, and `network`, each with `status` (`done`, `todo`, `warning`, or `info`), `title`, `detail`, display `lines`, `help` entries (`text` and an optional server `command`), and `actions` (`page` opens a screen, `print_missing` and `print` open batch printing). `remaining` counts `todo` and `warning` steps. The response also includes `staff` counts, `badges.missing` (active staff IDs with no badge on record), active `office_users`, each station's `signed_in_until` session expiry, `last_scan_at`, and `scanned_today` (Eastern school day), and whether the request used HTTPS or the server accepts non-loopback hosts (`lan`). It never returns keys, passwords, or badge codes.

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

`POST /badge-image` accepts the scan-shaped payload above and returns `image/png`; the direction and UUID are validated but no scan is recorded. The office screens no longer use it: they draw badges from the patterns returned when a badge is issued, so a code never travels back to the server.

`POST /teachers/{id}/correction` accepts `direction`, a fresh `request_id`, and a `reason` of 3–240 characters. Corrections use the same atomic state/event transaction. Corrections made through named office sessions include that account's display name in the activity log; legacy administrator-key corrections show as `office`.

## Planned absences and substitute coverage

POST `/absences` accepts `teacher_pk` (database ID), `day` (ISO first school
date), optional `school_days` (1–90, default 1), and `substitute_name` (null or
up to 120 characters). Blank names become null. The plan covers `day` plus the
following weekdays, so five days from Thursday ends the next Wednesday. Days
planned together share a `series_id`; each day is still its own entry with its
own cover, version, and history. Only active staff can receive a new plan. If
any requested day already has an entry for that teacher, including a cancelled
one, the whole request returns 409 naming the dates and no day is created.

PATCH `/absences/{id}` requires the entry's current `version`, `cancelled`
(boolean), and `substitute_name`. A stale version returns 409 rather than
overwriting another office user's changes. Staff/date remain fixed; cancel and
create the correct date when rescheduling. No-op saves leave the version and
history unchanged. Cancelled entries can be restored for active staff.

To change the rest of a multi-day plan, add `scope: "following"` and `versions`,
an object mapping each later entry ID to the version the office reviewed. The
later entries are this plan's days after this one that share this day's
cancelled state: active days when assigning cover or cancelling, cancelled days
when restoring. If the set or any version differs, nothing is saved and the
response is 409. Cover edits copy the new substitute name to those later days;
cancelling or restoring them keeps each day's own substitute. The response adds
`changed_days`. Every changed day receives its own audit change.

GET `/absences` returns `day`, `today`, `entries`, `planned`, `covered`, and
`unassigned`. Add `include_cancelled=true` to include cancelled rows; counts
still exclude them. Entries include the office actor, change timestamp, version,
and the teacher's **current** recorded presence, even when viewing another
school date. Multi-day entries add `series` with `position`, `total`,
`first_day`, `last_day`, active `planned` days, and each day's `id`, `day`,
`version`, `cancelled`, and `substitute_name`. `/absences/range` returns the same
entries without the per-day list, grouped under `days` with per-date and overall
counts. Coverage history is separate from scan history and CSV exports.
All coverage routes reject station access. An assignment creates no substitute
account, badge, or attendance scan. A lost save response should be resolved by
refreshing the date before retrying.

## Attention queue

GET `/attention` is read-only. It returns `today`, `day_start` (Eastern midnight
as a Unix timestamp), `items`, `not_arrived` (active staff IDs with no IN scan or
correction today, no plan for today, and not recorded IN; empty on weekends),
`planned_today`, and today's `coverage` counts. Items, in order:

| `kind` | When |
| --- | --- |
| `planned_out_but_in` | Planned out today and recorded IN with an IN scan today |
| `needs_cover_today` | Planned out today with no substitute |
| `stale_in` | Recorded IN since before today with no scan of any kind today |
| `double_booked` | One substitute name (case/space-insensitive) on two plans the same day, within 14 days |
| `needs_cover_upcoming` | Later days without a substitute within 14 days, one item per plan |
| `not_arrived` | Summary of `not_arrived` (informational) |

Each item has a `tone` (`warning`, `action`, `info`), a `title`, a `detail`, and
`actions` the office reviews before anything is saved: `edit_cover` and
`cancel_absence` open that absence's dialog, `correct` opens a correction with a
suggested direction and reason, `open_day` opens a coverage date, and
`show_not_arrived` filters the roster. Inactive staff and cancelled plans are
excluded. The queue never checks anyone out or reassigns cover automatically.

## Storage and rollout

SQLAlchemy stores teacher state and audit events in one database transaction. SQLite serializes writers; PostgreSQL locks each teacher row. The hosted path uses a private `school_checkin` schema and requires explicit provisioning. The API suite runs against both SQLite and local PostgreSQL 16, including in GitHub CI. Hosted Supabase and physical hardware remain separate verification steps. See [Supabase setup](SUPABASE.md).
