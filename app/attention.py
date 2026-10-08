"""Office attention queue: today's exceptions, derived from recorded scans and planned coverage.

Everything here is read-only. Suggested fixes are actions the office still reviews and saves
explicitly; nothing is checked out, corrected, or reassigned automatically.
"""
from datetime import datetime, time as clock, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.absences import day_label, school_today
from app.models import ScanEvent, Teacher, TeacherAbsence

SCHOOL_ZONE = ZoneInfo("America/New_York")
LOOKAHEAD_DAYS = 14


def day_start(day):
    return int(datetime.combine(day, clock(0), SCHOOL_ZONE).timestamp())


def moment(epoch):
    local = datetime.fromtimestamp(epoch, SCHOOL_ZONE)
    return f"{day_label(local.date())}, {local.hour % 12 or 12}:{local.minute:02} {'AM' if local.hour < 12 else 'PM'}"


def plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


def same_name(value):
    return " ".join(value.split()).lower()


def item(kind, tone, title, detail, actions, teacher=None, absence=None, day=None):
    day = day or (absence.day if absence else None)
    return {"id": f"{kind}:{teacher.id if teacher else ''}:{absence.id if absence else ''}:{day or ''}",
            "kind": kind, "tone": tone, "title": title, "detail": detail, "actions": actions,
            "teacher_pk": teacher.id if teacher else None, "absence_id": absence.id if absence else None,
            "day": day.isoformat() if day else None}


def cover_action(absence, kind="edit_cover", label="Assign cover"):
    return {"type": kind, "label": label, "absence_id": absence.id, "day": absence.day.isoformat()}


def correct_action(teacher, label, reason=None):
    return {"type": "correct", "label": label, "teacher_pk": teacher.id, "direction": "out", "reason": reason}


def register_attention(app, db, auth_admin):
    @app.get("/api/attention", dependencies=[Depends(auth_admin)])
    def attention(session: Session = Depends(db)):
        today = school_today()
        start = day_start(today)
        staff = list(session.scalars(select(Teacher).where(Teacher.active == True).order_by(Teacher.name)))
        scanned, arrived = set(), {}
        events = select(ScanEvent.teacher_pk, ScanEvent.direction, ScanEvent.occurred_at).where(ScanEvent.occurred_at >= start)
        for teacher_pk, direction, occurred_at in session.execute(events):
            scanned.add(teacher_pk)
            if direction == "in":
                arrived[teacher_pk] = min(arrived.get(teacher_pk, occurred_at), occurred_at)
        plans = list(session.execute(
            select(TeacherAbsence, Teacher).join(Teacher, Teacher.id == TeacherAbsence.teacher_pk)
            .where(TeacherAbsence.day >= today, TeacherAbsence.day <= today + timedelta(days=LOOKAHEAD_DAYS - 1),
                   TeacherAbsence.cancelled == False, Teacher.active == True)
            .order_by(TeacherAbsence.day, Teacher.name)))
        todays = [(absence, teacher) for absence, teacher in plans if absence.day == today]
        planned_today = {teacher.id for _, teacher in todays}
        items = []

        for absence, teacher in todays:
            if teacher.inside and teacher.id in arrived:
                release = f" and release {absence.substitute_name}" if absence.substitute_name else ""
                items.append(item("planned_out_but_in", "warning", f"{teacher.name} is recorded IN but planned out today",
                                  f"Arrival recorded {moment(arrived[teacher.id])}. If they are working today, cancel the "
                                  f"absence{release}; if the scan was a mistake, correct the status.",
                                  [cover_action(absence, "cancel_absence", "Cancel today's absence"),
                                   correct_action(teacher, "Correct status")], teacher, absence))
        for absence, teacher in todays:
            if not absence.substitute_name:
                items.append(item("needs_cover_today", "action", f"{teacher.name} needs cover today",
                                  "Planned absence with no substitute assigned.", [cover_action(absence)], teacher, absence))
        # A repeat scan today leaves last_seen unchanged, so any scan today clears the stale flag.
        for teacher in sorted((person for person in staff if person.inside and person.last_seen is not None
                               and person.last_seen < start and person.id not in scanned), key=lambda person: person.last_seen):
            since = datetime.fromtimestamp(teacher.last_seen, SCHOOL_ZONE).date()
            items.append(item("stale_in", "warning", f"{teacher.name} is still recorded IN from {day_label(since)}",
                              f"Last status change {moment(teacher.last_seen)}. No departure was recorded after it.",
                              [correct_action(teacher, "Record OUT", "Missed departure scan")], teacher))
        bookings = {}
        for absence, teacher in plans:
            if absence.substitute_name:
                bookings.setdefault((absence.day, same_name(absence.substitute_name)), []).append((absence, teacher))
        for (day, _), group in sorted(bookings.items()):
            if len(group) > 1:
                # Show the tidiest spelling typed for this person, e.g. "Pat Lee" over "pat  lee".
                spelling = max((" ".join(absence.substitute_name.split()) for absence, _ in group),
                               key=lambda name: sum(letter.isupper() for letter in name))
                items.append(item("double_booked", "warning",
                                  f"{spelling} is assigned to {len(group)} staff on {day_label(day)}",
                                  "Covering " + ", ".join(teacher.name for _, teacher in group) + ".",
                                  [{"type": "open_day", "label": "Review day", "day": day.isoformat()}], day=day))
        gaps = {}
        for absence, teacher in plans:
            if absence.day > today and not absence.substitute_name:
                gaps.setdefault(absence.series_id or f"day-{absence.id}", []).append((absence, teacher))
        for group in gaps.values():
            first, teacher = group[0]
            days = [absence.day for absence, _ in group]
            when = day_label(days[0]) if len(days) == 1 else f"{day_label(days[0])} – {day_label(days[-1])}"
            items.append(item("needs_cover_upcoming", "action",
                              f"{teacher.name} needs cover on {plural(len(days), 'upcoming school day')}", when + ".",
                              [cover_action(first)], teacher, first))
        not_arrived = [] if today.weekday() >= 5 else [
            person.id for person in staff
            if person.id not in arrived and person.id not in planned_today and not person.inside]
        if not_arrived:
            items.append(item("not_arrived", "info", f"{plural(len(not_arrived), 'staff member')} with no arrival recorded today",
                              "Not planned out. Some may still arrive; anyone who is out needs an absence planned.",
                              [{"type": "show_not_arrived", "label": "Show list"}], day=today))
        covered = sum(bool(absence.substitute_name) for absence, _ in todays)
        return {"today": today.isoformat(), "day_start": start, "items": items, "not_arrived": not_arrived,
                "planned_today": [{"teacher_pk": teacher.id, "absence_id": absence.id,
                                   "substitute_name": absence.substitute_name} for absence, teacher in todays],
                "coverage": {"planned": len(todays), "covered": covered, "unassigned": len(todays) - covered}}
