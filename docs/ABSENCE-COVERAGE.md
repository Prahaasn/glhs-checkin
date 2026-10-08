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
2. Select a school date. **Plan absence** asks for an active staff member, the
   first day out, how many **school days** they will be out, and an optional
   substitute name. Leave the name blank when cover is still needed. Quick picks
   cover 1–3 days, a week, or two weeks; the preview lists the exact dates.
   Saturdays and Sundays are skipped automatically. Holidays are not known to
   the app, so cancel any planned day that turns out to be a day off. Names
   already used on recent plans are suggested as you type, and the dialog warns
   when that substitute is already covering someone else on one of those days,
   or when the staff member already has an entry that would block the save.
3. Review Planned absences, Substitute assigned, and Needs cover. The overview
   summarizes today's coverage. Recorded now always shows the teacher's current
   scan status, including when reviewing a past or future date.
4. **Edit cover** assigns, replaces, or clears a substitute. Teacher/date stay
   fixed; to reschedule, cancel and plan the correct date. On a multi-day plan,
   choose **Only this day** or **this day and the later days**; changing cover
   defaults to the later days because one substitute usually covers the rest.
   Each row shows its place in the plan, such as Day 2 of 5. A substitute named
   on two plans for the same day is flagged, as is a teacher recorded IN on a
   day they are planned out.
5. **Next 2 weeks** lists active absences by date from the selected day, with
   cover gaps highlighted. **Open day** returns to that date's table; the ‹ and ›
   buttons step between weekdays.
6. **Cancel** asks for review and keeps the entry and history. On a multi-day
   plan it starts with only that day; choose the later days too when someone
   returns early. Use **Show cancelled** and **Restore** to recover it. Cancelled entries do not count in
   totals, and inactive staff cannot have plans restored.
7. **History** shows the latest 50 changes and the named office account. Trusted
   legacy administrator-key writes are identified as Office API. All changes
   remain in the database; scan activity and its CSV remain separate.

One teacher has one entry per school date; a multi-day plan is a set of those
entries sharing a series ID. A plan that overlaps an existing entry is refused
as a whole, so no partial set of days is created. The version checked on save
prevents an office user from silently replacing someone else's more recent
change; a change to later days checks every one of those days' versions. A
conflict asks you to close and reopen the entry. If a connection drops during a
save, refresh the date to check whether it was saved before retrying.

The source of truth is TeacherAbsence plus its append-only AbsenceChange rows.
Both save in one transaction. SQLite serializes writers; PostgreSQL locks the
teacher before the absence row, so restore checks wait for a pending
deactivation. Coverage changes never write Teacher.inside, Teacher.last_seen, or
ScanEvent. Naming a substitute creates no login, badge, or substitute attendance.
Only office accounts and the administrator API can use coverage routes.

Plans cover whole school days, one or more at a time, with names entered on
each plan and suggested from recent plans. Partial days, a school holiday
calendar, a managed substitute directory, substitute check-in, notifications,
and class/period assignments remain future product decisions.
For PostgreSQL rollout and recovery, see [Supabase setup](SUPABASE.md).
