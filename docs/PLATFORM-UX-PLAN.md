# Daily front-office workflow

The product should let an office team prepare the day, see recorded presence and
substitute coverage, handle exceptions, and review what happened. The scanner
should be a focused tool that confirms one arrival or departure at a time.

## Current architecture and friction

One FastAPI server and SQLAlchemy database own staff, badges, sessions, and scan
history. Office users can manage staff and corrections; station users can scan
but cannot read the office roster. Browser screens share the existing API.

- Setup requires terminal commands and copied enrollment keys.
- Overview shows recorded presence, a Needs attention queue, and today's
  coverage; Absences & cover plans one or more school days with substitutes.
- Staff & badges supports one person at a time; replacement immediately revokes
  the old token, so printing is an important step.
- Office corrections, badge replacement, and deactivation use review dialogs.
- Activity can be searched, filtered by type, and narrowed to one day.
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
2. **Absences and substitute coverage (implemented):** office records an absence for one
   or more school days, assigns or changes a substitute for a day or the rest of
   the plan, cancels an absence, and sees today's and the next two weeks' coverage.
   Preserve scan history and role isolation.
3. **Exception handling (implemented):** review dialogs show the staff member,
   recorded status, explicit IN/OUT, reason, and final action; corrections retry
   with the same request ID like scans.
4. **Setup and badge workflow:** guided readiness and printing/replacement;
   evaluate batch issuance without retaining real badge tokens unnecessarily.
5. **Overview and activity (implemented):** the Needs attention queue lists cover
   gaps, planned-out staff recorded IN, staff still IN from an earlier day,
   double-booked substitutes, upcoming gaps, and staff with no arrival today, each
   with a reviewed fix. The roster tags planned-out staff; Activity filters by
   type and day. Nothing in the queue writes records on its own.

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
