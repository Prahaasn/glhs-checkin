"""Office-only planned coverage, separate from recorded attendance."""
import time
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AbsenceChange, OfficeUser, Teacher, TeacherAbsence

MAX_SCHOOL_DAYS = 90
MAX_RANGE_DAYS = 62


def school_today():
    return datetime.now(ZoneInfo("America/New_York")).date()


def plan_dates(start, count):
    """The chosen start date plus the following weekdays, so 5 days from a Monday ends Friday."""
    days, current = [start], start
    while len(days) < count:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days.append(current)
    return days


def day_label(day):
    return f"{day:%a %b} {day.day}"


class SubstituteInput(BaseModel):
    substitute_name: str | None = Field(max_length=120, pattern=r"^[^\x00-\x1f\x7f]*$")

    @field_validator("substitute_name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class AbsenceInput(SubstituteInput):
    teacher_pk: int = Field(gt=0)
    day: date
    school_days: int = Field(1, ge=1, le=MAX_SCHOOL_DAYS)


class AbsenceUpdate(SubstituteInput):
    version: int = Field(gt=0)
    cancelled: bool
    # "following" also changes this plan's later days that share this day's cancelled state.
    scope: Literal["day", "following"] = "day"
    versions: dict[int, int] = Field(default_factory=dict, max_length=MAX_SCHOOL_DAYS)


def view(entry, teacher, actor_name):
    return {"id": entry.id, "teacher_pk": teacher.id, "teacher_id": teacher.teacher_id,
            "name": teacher.name, "active": teacher.active, "day": entry.day.isoformat(),
            "substitute_name": entry.substitute_name, "cancelled": entry.cancelled,
            "version": entry.version, "updated_at": entry.updated_at,
            "updated_by": actor_name or "Office API",
            "presence": "unrecorded" if teacher.last_seen is None else ("in" if teacher.inside else "out"),
            "series_id": entry.series_id, "series": None}


def totals(entries):
    active = [entry for entry in entries if not entry["cancelled"]]
    return {"planned": len(active), "covered": sum(bool(entry["substitute_name"]) for entry in active),
            "unassigned": sum(not entry["substitute_name"] for entry in active)}


def attach_series(session, entries, detail=True):
    """Describe each entry's place in its multi-day plan; detail adds every day's version."""
    ids = {entry["series_id"] for entry in entries if entry["series_id"]}
    if not ids:
        return entries
    grouped = {}
    query = (select(TeacherAbsence.id, TeacherAbsence.series_id, TeacherAbsence.day, TeacherAbsence.version,
                    TeacherAbsence.cancelled, TeacherAbsence.substitute_name)
             .where(TeacherAbsence.series_id.in_(ids)).order_by(TeacherAbsence.day))
    for row in session.execute(query):
        grouped.setdefault(row.series_id, []).append(
            {"id": row.id, "day": row.day.isoformat(), "version": row.version,
             "cancelled": row.cancelled, "substitute_name": row.substitute_name})
    for entry in entries:
        days = grouped.get(entry["series_id"])
        if days:
            position = next(index for index, day in enumerate(days, 1) if day["id"] == entry["id"])
            entry["series"] = {"position": position, "total": len(days), "first_day": days[0]["day"],
                               "last_day": days[-1]["day"],
                               "planned": sum(not day["cancelled"] for day in days)}
            if detail:
                entry["series"]["days"] = days
    return entries


def register_absences(app, sqlite, db, auth_admin):
    def begin_write(session):
        if sqlite:
            session.execute(text("BEGIN IMMEDIATE"))

    def actor_name(session, actor):
        user = session.get(OfficeUser, actor) if actor is not None else None
        return user.display_name if user else None

    def audit(session, entry, actor, action):
        session.add(AbsenceChange(absence_pk=entry.id, version=entry.version, action=action,
                                 substitute_name=entry.substitute_name, cancelled=entry.cancelled,
                                 occurred_at=entry.updated_at, actor_user_id=actor))

    def planned(session, *conditions):
        query = (select(TeacherAbsence, Teacher, OfficeUser.display_name)
                 .join(Teacher, Teacher.id == TeacherAbsence.teacher_pk)
                 .outerjoin(OfficeUser, OfficeUser.id == TeacherAbsence.updated_by)
                 .where(*conditions).order_by(TeacherAbsence.day, Teacher.name))
        return [view(entry, teacher, actor) for entry, teacher, actor in session.execute(query)]

    @app.get("/api/absences", dependencies=[Depends(auth_admin)])
    def list_absences(day: date | None = None, include_cancelled: bool = False, session: Session = Depends(db)):
        day = day or school_today()
        conditions = [TeacherAbsence.day == day]
        if not include_cancelled:
            conditions.append(TeacherAbsence.cancelled == False)
        entries = attach_series(session, planned(session, *conditions))
        return {"day": day.isoformat(), "today": school_today().isoformat(), "entries": entries, **totals(entries)}

    @app.get("/api/absences/range", dependencies=[Depends(auth_admin)])
    def absence_range(start: date, end: date, session: Session = Depends(db)):
        if end < start or (end - start).days >= MAX_RANGE_DAYS:
            raise HTTPException(400, f"Choose a range of 1 to {MAX_RANGE_DAYS} days.")
        entries = attach_series(session, planned(session, TeacherAbsence.day >= start, TeacherAbsence.day <= end,
                                                 TeacherAbsence.cancelled == False), detail=False)
        days = {}
        for entry in entries:
            days.setdefault(entry["day"], []).append(entry)
        return {"start": start.isoformat(), "end": end.isoformat(), "today": school_today().isoformat(),
                **totals(entries),
                "days": [{"day": day, **totals(items), "entries": items} for day, items in days.items()]}

    @app.get("/api/substitutes", dependencies=[Depends(auth_admin)])
    def substitutes(session: Session = Depends(db)):
        # Names already typed on plans, newest first; there is no separate substitute directory.
        last_day = func.max(TeacherAbsence.day)
        query = (select(TeacherAbsence.substitute_name, last_day, func.count())
                 .where(TeacherAbsence.substitute_name.is_not(None), TeacherAbsence.cancelled == False,
                        TeacherAbsence.day >= school_today() - timedelta(days=365))
                 .group_by(TeacherAbsence.substitute_name).order_by(last_day.desc()).limit(100))
        return [{"name": name, "last_day": str(day), "assignments": count}
                for name, day, count in session.execute(query)]

    @app.post("/api/absences", status_code=201)
    def add_absence(payload: AbsenceInput, actor=Depends(auth_admin), session: Session = Depends(db)):
        begin_write(session)
        teacher = session.scalar(select(Teacher).where(Teacher.id == payload.teacher_pk).with_for_update())
        if not teacher:
            raise HTTPException(404, "Staff member not found.")
        if not teacher.active:
            raise HTTPException(409, "Choose an active staff member.")
        days = plan_dates(payload.day, payload.school_days)
        taken = list(session.scalars(select(TeacherAbsence.day).where(
            TeacherAbsence.teacher_pk == teacher.id, TeacherAbsence.day.in_(days)).order_by(TeacherAbsence.day)))
        if taken:
            listed = ", ".join(day_label(day) for day in taken[:4]) + (" and more" if len(taken) > 4 else "")
            raise HTTPException(409, f"{teacher.name} already has an absence entry on {listed}. "
                                     "Edit or restore that entry, or choose different dates.")
        series = str(uuid4()) if len(days) > 1 else None
        now = int(time.time())
        entries = [TeacherAbsence(teacher_pk=teacher.id, day=day, substitute_name=payload.substitute_name,
                                  updated_at=now, updated_by=actor, version=1, cancelled=False, series_id=series)
                   for day in days]
        session.add_all(entries)
        try:
            session.flush()
            for entry in entries:
                audit(session, entry, actor, "created")
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "An absence already exists for this teacher and date. Edit or restore that entry.")
        return attach_series(session, [view(entries[0], teacher, actor_name(session, actor))])[0]

    @app.patch("/api/absences/{pk}")
    def update_absence(pk: int, payload: AbsenceUpdate, actor=Depends(auth_admin), session: Session = Depends(db)):
        begin_write(session)
        teacher_pk = session.scalar(select(TeacherAbsence.teacher_pk).where(TeacherAbsence.id == pk))
        if teacher_pk is None:
            raise HTTPException(404, "Absence not found.")
        # Teacher first, matching scan/deactivation and plan-creation lock order.
        teacher = session.scalar(select(Teacher).where(Teacher.id == teacher_pk).with_for_update())
        entry = session.scalar(select(TeacherAbsence).where(TeacherAbsence.id == pk).with_for_update())
        if not entry:
            raise HTTPException(404, "Absence not found.")
        if entry.version != payload.version:
            raise HTTPException(409, "This absence changed. Close and reopen the entry before saving.")
        later = []
        if payload.scope == "following" and entry.series_id:
            later = list(session.scalars(select(TeacherAbsence).where(
                TeacherAbsence.series_id == entry.series_id, TeacherAbsence.day > entry.day,
                TeacherAbsence.cancelled == entry.cancelled).order_by(TeacherAbsence.day).with_for_update()))
        # Every later day must be exactly the set and versions the office reviewed.
        if {row.id: row.version for row in later} != payload.versions:
            raise HTTPException(409, "Some later days in this absence changed. Close and reopen the entry before saving.")
        if entry.cancelled and not payload.cancelled and not teacher.active:
            raise HTTPException(409, "An inactive staff member's absence cannot be restored.")
        changed, now = 0, int(time.time())
        for row in [entry, *later]:
            if (row.substitute_name, row.cancelled) == (payload.substitute_name, payload.cancelled):
                continue
            action = ("cancelled" if payload.cancelled else "restored") if row.cancelled != payload.cancelled else "updated"
            row.substitute_name, row.cancelled = payload.substitute_name, payload.cancelled
            row.version += 1
            row.updated_at, row.updated_by = now, actor
            audit(session, row, actor, action)
            changed += 1
        if changed:
            session.commit()
        result = view(entry, teacher, actor_name(session, entry.updated_by))
        result["changed_days"] = changed
        return attach_series(session, [result])[0]

    @app.get("/api/absences/{pk}/changes", dependencies=[Depends(auth_admin)])
    def changes(pk: int, session: Session = Depends(db)):
        if not session.get(TeacherAbsence, pk):
            raise HTTPException(404, "Absence not found.")
        query = (select(AbsenceChange, OfficeUser.display_name)
                 .outerjoin(OfficeUser, OfficeUser.id == AbsenceChange.actor_user_id)
                 .where(AbsenceChange.absence_pk == pk).order_by(AbsenceChange.version.desc()).limit(50))
        return [{"version": change.version, "action": change.action, "substitute_name": change.substitute_name,
                 "cancelled": change.cancelled, "occurred_at": change.occurred_at, "actor": actor or "Office API"}
                for change, actor in session.execute(query)]
