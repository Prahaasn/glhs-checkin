# GLHS Staff Presence

![Backend checks](https://github.com/Prahaasn/glhs-checkin/actions/workflows/check.yml/badge.svg?branch=codex%2Fschool-checkin)

A local school front-office pilot: two barcode scanner stations, printable teacher QR badges, and an office dashboard. Python **FastAPI + SQLAlchemy**, SQLite locally, PostgreSQL/Supabase later. All sample teachers are fictional.

![Staff presence dashboard using fictional teachers](docs/screenshots/dashboard-desktop.png)

## Backend

The backend owns teacher registration, QR badge lookup, station authentication, arrival/departure transactions, presence history, and CSV exports. Both scanner computers connect to this one API. See the [API reference](docs/API.md) for routes, request examples, and retry behavior.

## Run locally

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/). Then:

```sh
uv sync --extra dev --locked
uv run python -m app.setup keys
uv run --env-file .env python -m app.setup demo
uv run --env-file .env uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8317
```

Open http://127.0.0.1:8317. Open `.env` **locally** to find the generated keys; never commit or share that file. The office dashboard uses `ADMIN_KEY`. Each scanner computer signs in as **Scanner station** with its own `STATION_1_KEY` or `STATION_2_KEY`. The browser exchanges the key for an expiring HttpOnly, SameSite=Strict cookie; raw access keys are not kept in browser storage. Office sessions expire after 30 minutes and station sessions after 12 hours. Locking revokes the session on the server. `demo` is optional; omit it when starting an empty roster. The demo badge codes live only in ignored `data/demo-badges.json`.

Teachers & badges → enter name and teacher ID → Add teacher → print the QR badge. The QR contains a random token, not the teacher's name/ID. Only its SHA-256 hash is saved. Replacing a badge revokes the old one; print the replacement immediately.

## Two computers, one source of truth

Run **one server**; both front computers open that same server URL. Do not run a separate SQLite database on each computer. Station 1 defaults to IN and station 2 defaults to OUT; either station can change direction. Direction is remembered per tab. USB scanners should use **HID Keyboard** mode with an **Enter suffix**. Focus the badge input, scan, and wait for the on-screen confirmation. A scanner's beep only means it read the badge, not that the server saved it.

For a supervised LAN pilot, set `ALLOWED_HOSTS` to the exact school-approved hostname or LAN IP and listen with `--host 0.0.0.0`; both computers use its LAN address and port 8317. Plain HTTP exposes keys/attendance to the network; use a school-approved HTTPS reverse proxy before real teacher data or routine operation. Keep the SQLite file on the server's local disk, not a network share. Supabase will host the database; a Python server is still needed to serve the app and API.

## Behavior

- Explicit IN/OUT avoids accidental toggling. Repeated IN stays IN and is logged as a repeat.
- Server timestamps and an append-only scan history support current and historical presence.
- Dashboard refreshes every five seconds and identifies failed refreshes as potentially stale.
- Network retries keep the original request ID; an already saved scan is not saved twice. An ambiguous failed scan blocks new scans until retried.
- Both stations serialize updates to the same teacher: SQLite uses `BEGIN IMMEDIATE`; PostgreSQL locks the teacher row.
- Office corrections require a reason and enter the audit history. No automatic midnight checkout: overnight presence stays recorded until corrected or scanned out.
- Deactivation requires an OUT state and disables the badge. Historical snapshots include teachers registered at that time, even if now inactive; current names and teacher IDs are used.
- History displays the latest 200 events; CSV exports all history with UTC timestamps and spreadsheet formula protection.
- Presence means **recorded status**, not guaranteed physical presence. No-scan staff have a separate Not recorded status; a missed departure can leave someone inside.

## Load the official Green Level roster locally

```sh
uv run python -m app.roster fetch-directory
uv run --env-file .env python -m app.roster import-directory --dry-run
uv run --env-file .env python -m app.roster import-directory
```

The verified directory snapshot contained **141 staff across 16 pages** on September 26, 2026. This includes support staff, not just classroom teachers. The roster stays inside ignored `data/`, never the public repo. `DIR-…` identifiers come from public directory records; they are **not school employee ID numbers**. Imports create no attendance events and no usable badges: office staff issue badges afterward. Re-imports preserve existing state/badges and do not deactivate anyone. See [roster details](docs/ROSTER.md) and [security boundaries](docs/SAFETY.md).

## Verify

```sh
uv run --extra dev pytest -q
# Optional: set TEST_DATABASE_URL to a local PostgreSQL database ending in _test
# to run the same API cases against both SQLite and PostgreSQL.
node --check app/static/app.js
```

See [implementation plan](docs/PLAN.md), [Supabase setup](docs/SUPABASE.md), and [review packet](docs/REVIEW-PACKET.md). This is a local pilot, not a deployed school system. Hardware scan/print testing and school approval remain before use with real staff.
