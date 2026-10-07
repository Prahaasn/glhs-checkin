# Daily front-office workflow

The product should let an office team prepare the day, see recorded presence and
substitute coverage, handle exceptions, and review what happened. The scanner
should be a focused tool that confirms one arrival or departure at a time.

## Current architecture and friction

One FastAPI server and SQLAlchemy database own staff, badges, sessions, and scan
history. Office users can manage staff and corrections; station users can scan
but cannot read the office roster. Browser screens share the existing API.

- Setup requires terminal commands and copied enrollment keys.
- Overview now shows recorded presence and today's planned coverage summary;
  Absences & cover supports whole school dates and substitute names.
- Staff & badges supports one person at a time; replacement immediately revokes
  the old token, so printing is an important step.
- Office corrections use browser prompts rather than an explicit review form.
- Activity shows recent scans but offers little help investigating an exception.
- Offline/stale states exist, but recovery instructions and readiness need a
  clearer place in the daily workflow.

## Proposed daily journey

| Moment | Office job | Observable outcome |
| --- | --- | --- |
| Prepare | Confirm roster, logins, badges, stations, and network | Staff know how to start and recover |
| Plan coverage | Record who is scheduled out and who covers them | Today's absences show assigned or unassigned substitutes |
| Arrive | Staff scan at the arrival station | Confirmed scan appears on the office dashboard |
| Monitor | Search presence and coverage together | Unknown presence stays distinct from planned absence |
| Handle exceptions | Correct a missed scan, replace a badge, change coverage | Explicit action, review, confirmation, and history |
| Depart and review | Scan OUT; inspect activity and unresolved coverage | The office can explain the day's records |

Scheduling an absence does not create an attendance scan. A teacher can be
scheduled out while recorded IN; the office should see both and resolve the
disagreement. A named substitute is a coverage assignment, not proof that the
substitute arrived or an automatic badge/account.

## Small sequence of PRs

1. **Repeatable rehearsal:** isolated fresh demo, printable codes, launcher, and
   verification. This makes subsequent product review reproducible.
2. **Absences and substitute coverage (implemented):** office records an absence for a school
   date, assigns or changes a substitute, cancels an absence, and sees today's
   coverage. Preserve scan history and role isolation.
3. **Exception handling:** replace browser prompts with accessible forms that
   clearly show the staff member, explicit status, reason, and final action.
4. **Setup and badge workflow:** guided readiness and printing/replacement;
   evaluate batch issuance without retaining real badge tokens unnecessarily.
5. **Overview and activity:** make presence, coverage gaps, stale data, and recent
   changes easy to act on; verify desk and narrow layouts.

Each implementation needs a rendered review and a testable user outcome. Keep
the existing calm visual style and shared server as the starting point. Avoid a
framework rewrite before the daily workflows work.

## Decisions to settle in product review

- Substitute names per absence are implemented; decide whether a reusable
  substitute directory is needed next.
- Whole school dates first; later, partial-day coverage and multiple assignments.
- Who can edit coverage and whether additional read-only office roles are needed.
- Whether substitutes later need badges and recorded attendance of their own.
- School ownership of access, retention, backups, and missed-scan procedures.

Physical emergency headcounts remain governed by school procedures. The platform
must describe recorded presence and planned coverage accurately.
