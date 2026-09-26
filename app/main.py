import csv
import hashlib
import hmac
import io
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

import qrcode
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session

from app.models import Base, ScanEvent, Teacher

STATIC = Path(__file__).parent / "static"


def badge_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


class TeacherInput(BaseModel):
    teacher_id: str = Field(min_length=1, max_length=80, pattern=r"^\S(?:.*\S)?$")
    name: str = Field(min_length=1, max_length=120, pattern=r"^\S(?:.*\S)?$")


class ScanInput(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    direction: Literal["in", "out"]
    request_id: UUID


class CorrectionInput(BaseModel):
    direction: Literal["in", "out"]
    request_id: UUID
    reason: str = Field(min_length=3, max_length=240)


def create_app(database_url=None, admin_key=None, station_keys=None):
    url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/checkin.db")
    admin = admin_key or os.getenv("ADMIN_KEY")
    stations = station_keys or {"front-1": os.getenv("STATION_1_KEY"), "front-2": os.getenv("STATION_2_KEY")}
    if not admin or any(not key for key in stations.values()):
        raise RuntimeError("Set ADMIN_KEY, STATION_1_KEY, and STATION_2_KEY before starting.")
    if len(set([admin, *stations.values()])) != len(stations) + 1:
        raise RuntimeError("Administrator and station keys must all be different.")
    sqlite = url.startswith("sqlite")
    if sqlite and url == "sqlite:///./data/checkin.db":
        Path("data").mkdir(exist_ok=True)
    kwargs = {"connect_args": {"check_same_thread": False, "timeout": 15}} if sqlite else {
        "connect_args": {"options": "-csearch_path=school_checkin", "prepare_threshold": None}}
    engine = create_engine(url, pool_pre_ping=True, **kwargs)
    if sqlite:
        @event.listens_for(engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    @asynccontextmanager
    async def lifespan(_):
        # Local bootstrap only. Hosted databases require the explicit provisioning command.
        if sqlite:
            Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="GLHS Staff Check-in", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'"
        return response

    def auth_admin(x_admin_key: str = Header(default="")):
        if not hmac.compare_digest(x_admin_key.encode(), admin.encode()):
            raise HTTPException(401, "Administrator sign-in required.")

    def auth_station(x_station_key: str = Header(default="")):
        for name, key in stations.items():
            if hmac.compare_digest(x_station_key.encode(), key.encode()):
                return name
        raise HTTPException(401, "Station sign-in required.")

    def db():
        with Session(engine) as session:
            yield session

    def teacher_view(t):
        return {"id": t.id, "teacher_id": t.teacher_id, "name": t.name, "active": t.active,
                "inside": t.inside, "last_seen": t.last_seen}

    def scan_result(e, teacher):
        return {"name": teacher.name, "inside": e.direction == "in", "changed": e.changed,
                "direction": e.direction, "occurred_at": e.occurred_at,
                "message": ("Checked " if e.changed else "Already ") + e.direction}

    def record(session, teacher_query, direction, request_id, station, reason=None):
        # Serialize the entire read/state-change/audit transaction across both stations.
        if sqlite:
            session.execute(text("BEGIN IMMEDIATE"))
        teacher = session.scalar(teacher_query.with_for_update())
        if teacher is None or not teacher.active:
            raise HTTPException(404, "Badge not recognized. Please see the front office.")
        previous = session.scalar(select(ScanEvent).where(ScanEvent.request_id == str(request_id)))
        if previous:
            if (previous.teacher_pk, previous.direction, previous.station, previous.reason) != (teacher.id, direction, station, reason):
                raise HTTPException(409, "Request ID already used for another scan.")
            return scan_result(previous, teacher)
        changed = teacher.inside != (direction == "in")
        now = int(time.time())
        if changed:
            teacher.inside = direction == "in"
            teacher.last_seen = now
        entry = ScanEvent(teacher_pk=teacher.id, request_id=str(request_id), direction=direction,
                          station=station, occurred_at=now, changed=changed, reason=reason)
        session.add(entry)
        from sqlalchemy.exc import IntegrityError
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Request ID already used for another scan.")
        return scan_result(entry, teacher)

    @app.get("/")
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health(session: Session = Depends(db)):
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/api/station")
    def station_info(station=Depends(auth_station)):
        return {"station": station}

    @app.post("/api/scans")
    def scan(payload: ScanInput, station=Depends(auth_station), session: Session = Depends(db)):
        return record(session, select(Teacher).where(Teacher.badge_hash == badge_hash(payload.code)),
                      payload.direction, payload.request_id, station)

    @app.get("/api/teachers", dependencies=[Depends(auth_admin)])
    def teachers(session: Session = Depends(db)):
        return [teacher_view(t) for t in session.scalars(select(Teacher).order_by(Teacher.name))]

    @app.get("/api/presence", dependencies=[Depends(auth_admin)])
    def presence(at: int, session: Session = Depends(db)):
        if at > int(time.time()):
            raise HTTPException(400, "Choose a time in the past or return to live.")
        snapshots = {}
        query = select(ScanEvent).where(ScanEvent.occurred_at <= at, ScanEvent.changed == True).order_by(ScanEvent.occurred_at, ScanEvent.id)
        for entry in session.scalars(query):
            snapshots[entry.teacher_pk] = entry
        result = []
        for teacher in session.scalars(select(Teacher).where(Teacher.created_at <= at).order_by(Teacher.name)):
            view = teacher_view(teacher)
            entry = snapshots.get(teacher.id)
            view["inside"] = bool(entry and entry.direction == "in")
            view["last_seen"] = entry.occurred_at if entry else None
            result.append(view)
        return result

    @app.post("/api/teachers", dependencies=[Depends(auth_admin)], status_code=201)
    def add_teacher(payload: TeacherInput, session: Session = Depends(db)):
        from sqlalchemy.exc import IntegrityError
        code = secrets.token_urlsafe(24)
        teacher = Teacher(teacher_id=payload.teacher_id, name=payload.name, badge_hash=badge_hash(code))
        session.add(teacher)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "Teacher ID already exists.")
        return {**teacher_view(teacher), "badge_code": code}

    def locked_teacher(session, pk):
        if sqlite:
            session.execute(text("BEGIN IMMEDIATE"))
        return session.scalar(select(Teacher).where(Teacher.id == pk).with_for_update())

    @app.post("/api/teachers/{pk}/badge", dependencies=[Depends(auth_admin)])
    def replace_badge(pk: int, session: Session = Depends(db)):
        teacher = locked_teacher(session, pk)
        if not teacher or not teacher.active:
            raise HTTPException(404, "Active teacher not found.")
        code = secrets.token_urlsafe(24)
        teacher.badge_hash = badge_hash(code)
        session.commit()
        return {"badge_code": code, "name": teacher.name}

    @app.patch("/api/teachers/{pk}", dependencies=[Depends(auth_admin)])
    def deactivate(pk: int, session: Session = Depends(db)):
        teacher = locked_teacher(session, pk)
        if not teacher:
            raise HTTPException(404, "Teacher not found.")
        if teacher.inside:
            raise HTTPException(409, "Record a check-out or office correction before deactivating.")
        teacher.active = False
        session.commit()
        return teacher_view(teacher)

    @app.post("/api/teachers/{pk}/correction", dependencies=[Depends(auth_admin)])
    def correction(pk: int, payload: CorrectionInput, session: Session = Depends(db)):
        return record(session, select(Teacher).where(Teacher.id == pk), payload.direction,
                      payload.request_id, "office", payload.reason)

    @app.post("/api/badge-image", dependencies=[Depends(auth_admin)])
    def badge_image(payload: ScanInput):
        buffer = io.BytesIO()
        qrcode.make(payload.code).save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")

    def events_query(session, since=None, until=None, limit=None):
        query = select(ScanEvent, Teacher).join(Teacher).order_by(ScanEvent.occurred_at.desc(), ScanEvent.id.desc())
        if since is not None:
            query = query.where(ScanEvent.occurred_at >= since)
        if until is not None:
            query = query.where(ScanEvent.occurred_at < until)
        if limit:
            query = query.limit(limit)
        return [{"id": e.id, "name": t.name, "teacher_id": t.teacher_id, "direction": e.direction,
                 "station": e.station, "occurred_at": e.occurred_at, "changed": e.changed, "reason": e.reason}
                for e, t in session.execute(query)]

    @app.get("/api/events", dependencies=[Depends(auth_admin)])
    def events(since: int | None = None, until: int | None = None, session: Session = Depends(db)):
        return events_query(session, since, until, 200)

    @app.get("/api/export", dependencies=[Depends(auth_admin)])
    def export(since: int | None = None, until: int | None = None, session: Session = Depends(db)):
        from datetime import datetime, timezone
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Teacher ID", "Name", "Direction", "Station", "Time (UTC)", "Changed status", "Correction reason"])
        def safe(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
        for e in events_query(session, since, until):
            writer.writerow([safe(e["teacher_id"]), safe(e["name"]), e["direction"], e["station"],
                             datetime.fromtimestamp(e["occurred_at"], timezone.utc).isoformat(), e["changed"], safe(e["reason"])])
        return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="staff-checkins.csv"'})

    return app
