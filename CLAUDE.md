# GLHS Staff Presence — working instructions

Read README.md, docs/CLAUDE-HANDOFF.md, and docs/PLATFORM-UX-PLAN.md before acting.
The handoff is a dated snapshot; verify Git/PR state rather than assuming its
branch, CI, or merge information is still current.

## Product and architecture

This is Green Level's local front-office staff-presence pilot. One FastAPI
server and SQLAlchemy database serve the office and both scanner stations.
SQLite is local; hosted PostgreSQL requires explicit private-schema provisioning.
The browser uses plain HTML/CSS/JavaScript and existing APIs; follow those
patterns before introducing another framework.

- app/main.py owns authentication, staff/badges, scans, corrections, and exports.
- app/absences.py owns office-only planned absences and substitute coverage.
- app/models.py owns the persisted state and audit tables.
- app/static/ owns the office and station screens.
- app/local_demo.py creates isolated fictional rehearsals and printable badges.

Recorded presence has three states: IN, OUT, and Not recorded. A planned absence
never creates or reverses a scan. A substitute name records an assignment;
it does not prove arrival or create a substitute badge/account.
Preserve atomic state/history, station isolation, scan request-UUID retries,
and absence version checks. Never count never-scanned staff as OUT.

## Operating rules

Prahaas owns product tradeoffs, human review, ready state, and merge. Inspect
status, branch, remotes, worktrees, and current PRs first. Preserve existing work;
never switch a shared checkout's branch or push main. Use an isolated worktree
and a codex/ branch for a material new behavior. One implementation task at a time.

Keep .env, data/, databases, issued tokens, passwords, and real roster files
local and out of logs/commits. Do not use a real database for demo or test setup.
Browser work uses the Codex in-app browser; do not connect to or control Chrome
or another external browser without an explicit current user request.

Verify focused regressions, the relevant full suite, JavaScript syntax, and
observable product behavior. Use the existing light theme at desk/narrow sizes
for UI work. If the approved browser is unavailable, identify the UI checks
that remain instead of claiming they ran.

Teach one important invariant in plain language. Every implementation gets a
draft PR, CI watched to completion, and a review packet with exact test results,
collision zones, manual checks, out-of-scope findings, rollback, and 2–4 files
to review. Ready/merge requires Prahaas's explicit current authorization. The shared review templates on this
Mac live in Documents/Obsidian Vault/agent-bridge/templates/.

For local setup and commands, follow START-HERE.md and docs/LOCAL-DEMO.md.
