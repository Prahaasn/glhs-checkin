# Safety and security boundaries

This is a supervised local pilot. Passing tests does not make a presence application an emergency-accountability system or prove that a teacher is physically on campus.

| Concern | Implemented control | Remaining boundary |
| --- | --- | --- |
| Unknown staff location | Separate Not recorded status; imports never invent attendance | Forgotten scans, badge sharing, and a stale directory need office review |
| Two stations racing or repeated scans | Explicit direction, SQL transaction/row lock, stable retry UUID | Physical scanner workflow still needs testing |
| Failed scan response | Same payload/UUID retry; pending scan survives a tab reload; no success shown before confirmation | Offline scanning is blocked; this is not an offline queue |
| Device access to office records | Separate station/office credentials and server-side role checks | Shared office key does not identify individual administrators |
| Raw keys in browser storage | Expiring HttpOnly SameSite=Strict sessions; logout revokes server record | HTTPS is required outside loopback; never enroll an admin session on an unattended kiosk |
| Guessing keys/badges | Bounded failed-login and unknown-badge throttles; startup requires configured keys of at least 32 characters | Throttles are per process; use one worker for this pilot, distributed limiting before scale |
| Oversized/malicious requests | 8 KiB streamed body cap, trusted-host allowlist, same-origin write checks, validation | Proxy/load balancer must also limit connections, headers, and slow uploads |
| Accidental token disclosure | Validation errors do not echo input; database errors return generic 503; masked scan input | Protect printed badges and local files; a copied QR is still a bearer badge |
| Script/frame attacks | Escaped roster fields, restrictive CSP, frame-ancestors none, nosniff and no-referrer | Review dependency changes and the actual deployment configuration |
| Public repository leaks | Ignored data/.env/database files; synthetic test fixtures and screenshots | Backups, logs, and exports must be school-controlled |
| Misleading live display | Refresh failures explicitly mark Stale; older last-change times include dates | A healthy backend does not detect a forgotten departure |

Before real front-office operation: identify and test both scanners; print and verify actual badges; use school-approved HTTPS and individual office authentication/SSO; approve roster/access/retention ownership; test backups and restore; verify Supabase's private schema and restricted database role; test the deployed boundary and network outage recovery. Physically verify people during emergencies using the school's approved procedures.

The API retains header authentication for trusted command-line integrations. These keys never belong in URLs, public code, browser local/session storage, or screenshots. Sessions persist in the database, so restarting the server does not revoke them; Lock explicitly revokes a session. Closing a tab alone does not revoke its cookie. Rotate compromised enrollment keys and revoke active sessions as a coordinated recovery task.

Use an exact `ALLOWED_HOSTS` allowlist for a LAN/hosted pilot; defaults accept only loopback hostnames. Do not use `*`. Rate limits intentionally do not trust arbitrary X-Forwarded-For headers. If behind a proxy, configure trusted forwarding correctly and keep external rate limits there.
