# Planned absences and coverage

> **Outcome:** Office staff can plan who is out, name their substitute, and see
> unresolved cover without changing recorded attendance.
> **Observed:** The original platform stored staff, scans, and corrections but
> had no planned absence or substitute assignment.
> **Constraints:** One shared server, office-only access, Eastern school dates,
> preserved scan history, and no substitute attendance inferred from a name.
> **Done when:** Plans can be created for a date, assigned or left unassigned,
> edited/cancelled/restored with office history, and reviewed alongside current
> recorded status; competing edits cannot silently overwrite one another.

1. Sign in as Office staff and open **Absences & cover**.
2. Select a school date. **Plan absence** asks for an active staff member and
   optional substitute name. Leave the name blank when cover is still needed.
3. Review Planned absences, Substitute assigned, and Needs cover. The overview
   summarizes today's coverage. Recorded now always shows the teacher's current
   scan status, including when reviewing a past or future date.
4. **Edit cover** assigns, replaces, or clears a substitute. Teacher/date stay
   fixed; to reschedule, cancel and plan the correct date.
5. **Cancel** asks for review and keeps the entry and history. Use **Show
   cancelled** and **Restore** to recover it. Cancelled entries do not count in
   totals, and inactive staff cannot have plans restored.
6. **History** shows the latest 50 changes and the named office account. Trusted
   legacy administrator-key writes are identified as Office API. All changes
   remain in the database; scan activity and its CSV remain separate.

One teacher has one entry per school date. The version checked on save prevents
an office user from silently replacing someone else's more recent change. A
conflict asks you to close and reopen the entry. If a connection drops during a
save, refresh the date to check whether it was saved before retrying.

The source of truth is TeacherAbsence plus its append-only AbsenceChange rows.
Both save in one transaction. SQLite serializes writers; PostgreSQL locks the
teacher before the absence row, so restore checks wait for a pending
deactivation. Coverage changes never write Teacher.inside, Teacher.last_seen, or
ScanEvent. Naming a substitute creates no login, badge, or substitute attendance.
Only office accounts and the administrator API can use coverage routes.

The first version covers whole school dates with names entered on each plan.
Partial days, date ranges, a reusable substitute directory, substitute check-in,
notifications, and class/period assignments remain future product decisions.
For PostgreSQL rollout and recovery, see [Supabase setup](SUPABASE.md).
