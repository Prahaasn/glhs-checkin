# GLHS platform handoff to Claude

State verified by Codex on October 7, 2026. Recheck live GitHub state before
decisions; this document records verified Git/testing facts, not hosted readiness.

## Requested outcome

Prahaas asked for the real codebase running locally, scannable test barcodes,
PRs with the work pushed, improvements across the whole daily office workflow,
and an admin place to record a teacher's absence and who substitutes for them.
He then asked for a folder/project he can open in Claude.

## Folder and Git state

The prepared local folder is /Users/prahaas/Documents/GLHS-Staff-Presence.
It is an isolated Git worktree with the complete source from the merged features,
plus these Claude instructions and launcher. It shares repository history with
the original GLHScheckinSystem checkout; retain that original repository.
The original shared checkout stays on main with its work preserved.

Remote: https://github.com/Prahaasn/glhs-checkin

| Work | PR | Verified merged commit / handoff branch | Base |
| --- | --- | --- | --- |
| Fresh scanner demo | [#3](https://github.com/Prahaasn/glhs-checkin/pull/3) | 9950d1e (merged) | main |
| Absences and cover | [#4](https://github.com/Prahaasn/glhs-checkin/pull/4) | 7943382 (merged, includes review fixes) | main |
| Claude project handoff | [#5](https://github.com/Prahaasn/glhs-checkin/pull/5) | codex/claude-project | main |

The two feature PRs merged in that order after review and green CI. This
document and launcher are part of #5; verify its latest state on GitHub.
Future stacked PRs must be retargeted/refreshed after their parent merges, with
checks rerun. Ready/merge requires explicit current authorization from Prahaas.
Do not edit an already-open feature branch from another
checkout. Start a new isolated branch/worktree for the next product behavior.

## What works and where

Fresh rehearsal: app/local_demo.py creates a separate SQLite database, named
office login, separate station keys, zero-scan fictional roster, private files,
launcher, and Code128/QR badge sheet. Restarting resumes that demo's history.
Existing school .env, roster, and database were preserved.

Office: Overview, Staff & badges, Activity, and Absences & cover. Plans are
unique per teacher/school date, with optional substitute name, unassigned counts,
edit/cancel/restore, and office-actor history. Today's overview excludes other
dates. Dates use Eastern time. Recorded now always means current scan status.

Data path: TeacherAbsence plus AbsenceChange store planned coverage. Teacher
and ScanEvent store recorded attendance. A coverage write and its audit change
commit together, without writing attendance. Stale versions return 409 rather
than overwriting another office's change. Station accounts cannot read/manage
office coverage. Teacher rows lock before absence rows, so restore waits for a
pending deactivation and checks committed staff state. The API/module uses the
existing authentication/session boundary.

Coverage and its staff selector refresh independently of activity history.
Changing date clears old actionable rows while the next request is pending.
Ending a session resets date/cancelled filters. A delayed save response owns only
its original dialog, so it cannot close or overwrite a newer form.

## Verification already observed

- #3 CI: 79 passed on SQLite and PostgreSQL 16.
- #4 final CI: 95 passed, 2 expected skips, 1 existing Starlette/httpx TestClient
  warning. Skips are SQLite instances of PostgreSQL-only migration and restore
  contention checks; both PostgreSQL instances passed.
- Latest application local suite: 55 passed, 2 PostgreSQL-only skips.
- All 6 Node UI regression checks passed; all 6 fail on the earlier UI scripts.
  These exercise pending/failed history, session defaults, date-view clearing,
  and ownership of late success/error responses.
- Both JavaScript syntax checks and diff whitespace checks passed.
- In-app browser: assigned/unassigned plans, reassignment, cancellation/restore,
  named audit, future-date filtering, today's summary, logout clearing, and real
  API-backed keyboard-style IN/OUT scans. Rendered at 1440x900 and 390x844.
- A two-page generated badge sheet decoded as eight QR and eight Code128 symbols,
  all matching the eight fictional badge tokens.
- CodeRabbit reviewed #3 with no actionable findings and #4 with five edge-case
  findings, all fixed and resolved. Its review of the final fix commit was rate
  limited; no fresh independent approval of that fix is claimed.
- The installed Python dependency audit found no known vulnerabilities.

Use the verification commands in README.md. Run browser checks with fictional
data. Keep UI scanning, printed physical scanner tests, and hosted deployment
verification distinct. Supabase, physical hardware, and deployment remain
unverified. Existing PostgreSQL pilots need the reviewed additive SQL migration
in docs/migrations/ before running the coverage app; preserve the added tables
and audit data when reverting the application commit.

## Remaining whole-workflow work

The daily journey is prepare → plan cover → arrive → monitor → handle exceptions
→ depart/review. Continue from docs/PLATFORM-UX-PLAN.md, one behavior at a time:

1. Replace missed-scan correction prompts with a reviewable staff/status/reason
   dialog and clear confirmation/error recovery.
2. Guide roster, office/station setup, badge printing/replacement, and readiness.
3. Make stale status, coverage gaps, and recent activity easier to act on.

Current scope is whole school dates and substitute names entered per absence.
Reusable substitute profiles, partial days/ranges, class periods, substitute
badges/attendance, and notifications need product decisions. Explain choices to
Prahaas before expanding behavior or access. The existing source is the starting
point; no framework rewrite or real-data import is needed to review the workflow.
