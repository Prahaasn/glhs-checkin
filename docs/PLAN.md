# Task brief and rollout plan

**Outcome:** replace the front-office paper sign-in sheet with teacher badges, fast scanner check-in/out, and a shared presence dashboard.

**Observed:** paper signatures do not provide a timely shared view of arrivals and departures. This repository began empty.

**Constraints:** SQLAlchemy backend; two existing scanners/computers; local-first; Supabase connection later; names/teacher IDs behind office authentication; no real staff data in GitHub.

**Done conditions:** (1) office can register a teacher and print a unique QR; (2) both stations write shared IN/OUT history; (3) repeats/retries/concurrent scans preserve correct state; (4) office can see live and historical presence and export CSV; (5) local run instructions and tested recovery paths exist.

## Stage 1: local pilot (this implementation)

One Python server owns the roster, badge lookup, timestamps, presence state, and scan history. Browsers send opaque badge codes, direction, and request UUID. The scanner does the barcode decoding; the backend does the teacher lookup. Use fictional data and keyboard simulations first.

## Stage 2: scanner rehearsal

Identify the exact Zebra model on its label. Confirm HID keyboard mode and Enter suffix with its own manual. Print two test badges at actual badge size, test laminated cards at realistic distances, and compare scanner confirmation with the visible application result. Open both stations; test arrival on one and departure on the other, repeats, unknown badges, server interruption/retry, and a forgotten check-out correction. Measure queue throughput and adjust print size/station placement.

## Stage 3: hosted pilot

Connect SQLAlchemy to Supabase PostgreSQL in a private schema. Deploy the Python app behind HTTPS. Re-run concurrency tests against the hosted database and test both real front-office computers. Add individual office accounts/SSO and revocable device enrollment instead of shared office keys before expanding beyond a supervised pilot. Agree with the school on roster ownership, access, retention, backups/restores, and scan correction responsibilities. Confirm the display wording clearly describes recorded presence.

## Stage 4: school rollout

Import the approved roster and batch-print badges in a separate task. Set retention and backup automation; drill restore and lost-badge replacement. Agree on a missed-scan process and support owner. Offline queuing, payroll calculations, automatic absence decisions, emergency-accountability certification, and student tracking are outside this pilot.
