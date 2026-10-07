"""Office-only planned coverage, separate from recorded attendance."""
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AbsenceChange, OfficeUser, Teacher, TeacherAbsence


def school_today():
    return datetime.now(ZoneInfo("America/New_York")).date()


class SubstituteInput(BaseModel):
    substitute_name: str | None = Field(max_length=120, pattern=r"^[^\x00-\x1f\x7f]*$")

    @field_validator("substitute_name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class AbsenceInput(SubstituteInput):
    teacher_pk: int = Field(gt=0)
    day: date


class AbsenceUpdate(SubstituteInput):
    version: int = Field(gt=0)
    cancelled: bool


def view(entry, teacher, actor_name):
    return {"id": entry.id, "teacher_pk": teacher.id, "teacher_id": teacher.teacher_id,
            "name": teacher.name, "active": teacher.active, "day": entry.day.isoformat(),
            "substitute_name": entry.substitute_name, "cancelled": entry.cancelled,
            "version": entry.version, "updated_at": entry.updated_at,
            "updated_by": actor_name or "Office API",
            "presence": "unrecorded" if teacher.last_seen is None else ("in" if teacher.inside else "out")}


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

    @app.get("/api/absences", dependencies=[Depends(auth_admin)])
    def list_absences(day: date | None = None, include_cancelled: bool = False, session: Session = Depends(db)):
        day = day or school_today()
        query = (select(TeacherAbsence, Teacher, OfficeUser.display_name)
                 .join(Teacher, Teacher.id == TeacherAbsence.teacher_pk)
                 .outerjoin(OfficeUser, OfficeUser.id == TeacherAbsence.updated_by)
                 .where(TeacherAbsence.day == day).order_by(Teacher.name))
        if not include_cancelled:
            query = query.where(TeacherAbsence.cancelled == False)
        entries = [view(entry, teacher, actor) for entry, teacher, actor in session.execute(query)]
        active = [entry for entry in entries if not entry["cancelled"]]
        return {"day": day.isoformat(), "today": school_today().isoformat(), "entries": entries,
                "planned": len(active), "covered": sum(bool(entry["substitute_name"]) for entry in active),
                "unassigned": sum(not entry["substitute_name"] for entry in active)}

    @app.post("/api/absences", status_code=201)
    def add_absence(payload: AbsenceInput, actor=Depends(auth_admin), session: Session = Depends(db)):
        begin_write(session)
        teacher = session.scalar(select(Teacher).where(Teacher.id == payload.teacher_pk).with_for_update())
        if not teacher:
            raise HTTPException(404, "Staff member not found.")
        if not teacher.active:
            raise HTTPException(409, "Choose an active staff member.")
        entry = TeacherAbsence(teacher_pk=teacher.id, day=payload.day,
                               substitute_name=payload.substitute_name, updated_at=int(time.time()),
                               updated_by=actor, version=1, cancelled=False)
        session.add(entry)
        try:
            session.flush()
            audit(session, entry, actor, "created")
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "An absence already exists for this teacher and date. Edit or restore that entry.")
        return view(entry, teacher, actor_name(session, actor))

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
        if entry.cancelled and not payload.cancelled and not teacher.active:
            raise HTTPException(409, "An inactive staff member's absence cannot be restored.")
        if (entry.substitute_name, entry.cancelled) != (payload.substitute_name, payload.cancelled):
            action = ("cancelled" if payload.cancelled else "restored") if entry.cancelled != payload.cancelled else "updated"
            entry.substitute_name, entry.cancelled = payload.substitute_name, payload.cancelled
            entry.version += 1
            entry.updated_at, entry.updated_by = int(time.time()), actor
            audit(session, entry, actor, action)
            session.commit()
        return view(entry, teacher, actor_name(session, entry.updated_by))

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
