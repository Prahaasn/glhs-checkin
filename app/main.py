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
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session

from app.models import AccessSession, Base, OfficeSession, OfficeUser, ScanEvent, Teacher
from app.security import BodyLimitMiddleware, FailureLimiter, verify_password

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
    reason: str = Field(min_length=3, max_length=240, pattern=r"^\S(?:.*\S)?$")


class LoginInput(BaseModel):
    role: Literal["admin", "station"]
    access_key: str = Field(min_length=1, max_length=256)


class OfficeLoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=256)


def create_app(database_url=None, admin_key=None, station_keys=None):
    url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/checkin.db")
    admin = admin_key or os.getenv("ADMIN_KEY")
    stations = station_keys or {"front-1": os.getenv("STATION_1_KEY"), "front-2": os.getenv("STATION_2_KEY")}
    if not admin or any(not key for key in stations.values()):
        raise RuntimeError("Set ADMIN_KEY, STATION_1_KEY, and STATION_2_KEY before starting.")
    if len(set([admin, *stations.values()])) != len(stations) + 1:
        raise RuntimeError("Administrator and station keys must all be different.")
    if database_url is None and any(len(key) < 32 for key in [admin, *stations.values()]):
        raise RuntimeError("Configured access keys must contain at least 32 characters. Generate them with app.setup keys.")
    sqlite = url.startswith("sqlite")
    if not sqlite and not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Use SQLite or a postgresql+psycopg:// database URL.")
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
    limiter = FailureLimiter()
    badge_limiter = FailureLimiter(limit=30)
    default_hosts = "127.0.0.1,localhost,[::1]" + (",testserver" if database_url else "")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("ALLOWED_HOSTS", default_hosts).split(","))
    app.add_middleware(BodyLimitMiddleware)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def security_headers(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != str(request.base_url).rstrip("/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Cross-origin writes are not allowed."}, status_code=403, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        from fastapi.responses import JSONResponse
        # Validation errors must never echo access keys or badge tokens.
        return JSONResponse({"detail": "Invalid request. Check the supplied fields."}, status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Database temporarily unavailable. Retry the same scan request."}, status_code=503)

    def client_id(request):
        # Do not trust user-supplied X-Forwarded-For headers.
        return request.client.host if request.client else "unknown"

    def session_identity(request):
        token = request.cookies.get("checkin_session", "")
        if not token:
            return None
        with Session(engine) as session:
            found = session.get(AccessSession, badge_hash(token))
            if found and found.expires_at > int(time.time()):
                identity = {"role": found.role, "station": found.station, "expires_at": found.expires_at}
                office_session = session.get(OfficeSession, found.token_hash)
                if office_session:
                    user = session.get(OfficeUser, office_session.user_id)
                    if not user or not user.active:
                        return None
                    identity["display_name"] = user.display_name
                    identity["user_id"] = user.id
                return identity
        return None

    def issue_session(request, role, station=None, user=None):
        token = secrets.token_urlsafe(32)
        token_hash = badge_hash(token)
        expires = int(time.time()) + (1800 if role == "admin" else 43200)
        with Session(engine) as session:
            session.execute(delete(OfficeSession).where(OfficeSession.token_hash.in_(
                select(AccessSession.token_hash).where(AccessSession.expires_at <= int(time.time())))))
            session.execute(delete(AccessSession).where(AccessSession.expires_at <= int(time.time())))
            previous = request.cookies.get("checkin_session")
            if previous:
                session.execute(delete(OfficeSession).where(OfficeSession.token_hash == badge_hash(previous)))
                session.execute(delete(AccessSession).where(AccessSession.token_hash == badge_hash(previous)))
            session.add(AccessSession(token_hash=token_hash, role=role, station=station, expires_at=expires))
            if user:
                session.add(OfficeSession(token_hash=token_hash, user_id=user.id))
            session.commit()
        from fastapi.responses import JSONResponse
        identity = {"role": role, "station": station, "expires_at": expires}
        if user:
            identity["display_name"] = user.display_name
        response = JSONResponse(identity)
        response.set_cookie("checkin_session", token, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=expires-int(time.time()), path="/api")
        return response

    def auth_admin(request: Request, x_admin_key: str = Header(default="")):
        identity = session_identity(request) if not x_admin_key else None
        if identity and identity["role"] == "admin":
            return identity.get("user_id")
        address = client_id(request)
        limiter.check(address)
        if not x_admin_key or not hmac.compare_digest(x_admin_key.encode(), admin.encode()):
            limiter.failed(address)
            raise HTTPException(401, "Administrator sign-in required.")
        return None

    def auth_station(request: Request, x_station_key: str = Header(default="")):
        identity = session_identity(request) if not x_station_key else None
        if identity and identity["role"] == "station":
            return identity["station"]
        address = client_id(request)
        limiter.check(address)
        for name, key in stations.items():
            if x_station_key and hmac.compare_digest(x_station_key.encode(), key.encode()):
                return name
        limiter.failed(address)
        raise HTTPException(401, "Station sign-in required.")

    @app.post("/api/session")
    def login(payload: LoginInput, request: Request):
        address = client_id(request)
        limiter.check(address)
        station = None
        valid = payload.role == "admin" and hmac.compare_digest(payload.access_key.encode(), admin.encode())
        if payload.role == "station":
            for name, key in stations.items():
                if hmac.compare_digest(payload.access_key.encode(), key.encode()):
                    valid, station = True, name
                    break
        if not valid:
            limiter.failed(address)
            raise HTTPException(401, "Access key not recognized.")
        return issue_session(request, payload.role, station)

    @app.post("/api/office-session")
    def office_login(payload: OfficeLoginInput, request: Request):
        address = client_id(request)
        limiter.check(address)
        with Session(engine) as session:
            user = session.scalar(select(OfficeUser).where(OfficeUser.username == payload.username.strip().lower()))
            if not user or not user.active or not verify_password(payload.password, user.password_hash):
                limiter.failed(address)
                raise HTTPException(401, "Username or password not recognized.")
            return issue_session(request, "admin", user=user)

    @app.get("/api/session")
    def current_session(request: Request):
        identity = session_identity(request)
        if not identity:
            raise HTTPException(401, "Sign-in required.")
        return identity

    @app.delete("/api/session")
    def logout(request: Request):
        with Session(engine) as session:
            session.execute(delete(OfficeSession).where(OfficeSession.token_hash == badge_hash(request.cookies.get("checkin_session", ""))))
            session.execute(delete(AccessSession).where(AccessSession.token_hash == badge_hash(request.cookies.get("checkin_session", ""))))
            session.commit()
        from fastapi.responses import JSONResponse
        response = JSONResponse({"locked": True})
        response.delete_cookie("checkin_session", path="/api", httponly=True, samesite="strict")
        return response

    def db():
        with Session(engine) as session:
            yield session

    def teacher_view(t):
        return {"id": t.id, "teacher_id": t.teacher_id, "name": t.name, "active": t.active,
                "inside": None if t.last_seen is None else t.inside, "last_seen": t.last_seen,
                "presence": "unrecorded" if t.last_seen is None else ("in" if t.inside else "out")}

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
        changed = teacher.last_seen is None or teacher.inside != (direction == "in")
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
        badge_limiter.check(station)
        try:
            return record(session, select(Teacher).where(Teacher.badge_hash == badge_hash(payload.code)),
                          payload.direction, payload.request_id, station)
        except HTTPException as error:
            if error.status_code == 404:
                badge_limiter.failed(station)
            raise

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
            view["inside"] = entry.direction == "in" if entry else None
            view["last_seen"] = entry.occurred_at if entry else None
            view["presence"] = entry.direction if entry else "unrecorded"
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

    @app.post("/api/teachers/{pk}/correction")
    def correction(pk: int, payload: CorrectionInput, actor=Depends(auth_admin), session: Session = Depends(db)):
        return record(session, select(Teacher).where(Teacher.id == pk), payload.direction,
                      payload.request_id, f"office:{actor}" if actor is not None else "office", payload.reason)

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
        entries = list(session.execute(query))
        actor_ids = {int(e.station.split(":")[1]) for e, _ in entries
                     if e.station.startswith("office:") and e.station[7:].isdigit()}
        actors = {user.id: user.display_name for user in session.scalars(select(OfficeUser).where(OfficeUser.id.in_(actor_ids)))} if actor_ids else {}
        def label(station):
            if station.startswith("office:") and station[7:].isdigit():
                return "Office · " + actors.get(int(station[7:]), "Former user")
            return station
        return [{"id": e.id, "name": t.name, "teacher_id": t.teacher_id, "direction": e.direction,
                 "station": label(e.station), "occurred_at": e.occurred_at, "changed": e.changed, "reason": e.reason}
                for e, t in entries]

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
