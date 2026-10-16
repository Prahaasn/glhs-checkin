"""Exercise hosted grants in a transaction on the guarded local test database."""
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.models import Base, OfficeUser, ScanEvent, Teacher
from app.security import hash_password
from test_checkin import client


def test_fresh_supabase_schema_is_private_and_runtime_cannot_rewrite_history(client, monkeypatch):
    engine = client.app.state.engine
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL roles and RLS require the local PostgreSQL test database")
    url = make_url(str(engine.url))
    assert url.host in {"127.0.0.1", "localhost"} and url.database.endswith("_test")
    migration = Path(__file__).resolve().parents[1] / "docs/provisioning/20261016162205_hosted_initial_private_schema.sql"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            # Preserve the fixture schema; every change, including the new role, rolls back.
            connection.exec_driver_sql("ALTER SCHEMA school_checkin RENAME TO saved_hosted_test")
            for role in ("anon", "authenticated"):
                if not connection.scalar(text("SELECT EXISTS (SELECT FROM pg_roles WHERE rolname=:role)"), {"role": role}):
                    connection.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN")
            connection.exec_driver_sql(migration.read_text())
            tables = connection.execute(text("SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='school_checkin'" )).all()
            assert {name for name, _ in tables} == set(Base.metadata.tables)
            assert all(rls for _, rls in tables)
            for role in ("anon", "authenticated"):
                assert not connection.scalar(text("SELECT has_schema_privilege(:role,'school_checkin','USAGE')"), {"role": role})
            assert connection.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname='glhs_checkin_app'" )).one() == (False, False, False, False, False)
            connection.exec_driver_sql("SET LOCAL ROLE glhs_checkin_app")
            person = connection.execute(insert(Teacher).values(teacher_id="CONNECTION-CHECK", name="Fictional Connection Check", badge_hash="a" * 64).returning(Teacher.id)).scalar_one()
            connection.execute(insert(ScanEvent).values(teacher_pk=person, request_id="00000000-0000-4000-8000-000000000001", direction="in", station="front-1", occurred_at=1, changed=True))
            assert connection.scalar(select(Teacher.name)) == "Fictional Connection Check"
            for statement in ("CREATE TABLE school_checkin.forbidden (id integer)",
                              "UPDATE school_checkin.scan_events SET direction='out'",
                              "DELETE FROM school_checkin.scan_events",
                              "DELETE FROM school_checkin.teachers"):
                with pytest.raises(ProgrammingError, match="permission denied"):
                    with connection.begin_nested():
                        connection.exec_driver_sql(statement)

            # Exercise real API/session writes under these grants, on this local-only
            # transaction. Request commits leave the outer transaction open; its rollback
            # removes every fictional record and restores the original fixture schema.
            monkeypatch.setattr("app.main.Session", lambda _: Session(
                connection, join_transaction_mode="rollback_only"))
            with Session(connection, join_transaction_mode="rollback_only") as session:
                session.add(OfficeUser(username="office", display_name="Office",
                                       password_hash=hash_password("local-only-password")))
                session.commit()
            assert client.post("/api/office-session", json={
                "username": "office", "password": "local-only-password"}).status_code == 200
            added = client.post("/api/teachers", json={"teacher_id": "LOCAL-API", "name": "Fictional API Check"})
            assert added.status_code == 201
            teacher = added.json()
            planned = client.post("/api/absences", json={"teacher_pk": teacher["id"],
                "day": "2026-10-19", "substitute_name": "Fictional Substitute"})
            assert planned.status_code == 201
            absence = planned.json()
            assert client.patch(f"/api/absences/{absence['id']}", json={
                "version": absence["version"], "cancelled": False,
                "substitute_name": "Another Fictional Substitute"}).status_code == 200
            assert len(client.get(f"/api/absences/{absence['id']}/changes").json()) == 2
            assert client.delete("/api/session").status_code == 200
            request_id = str(uuid4())
            assert client.post("/api/session", json={"role": "station", "access_key": "test-one"}).status_code == 200
            payload = {"code": teacher["badge_code"], "direction": "in", "request_id": request_id}
            arrived = client.post("/api/scans", json=payload)
            assert arrived.status_code == 200 and arrived.json()["inside"]
            assert client.post("/api/scans", json=payload).json() == arrived.json()
            assert client.get("/api/teachers").status_code == 401
            assert client.delete("/api/session").status_code == 200
            assert client.post("/api/session", json={"role": "station", "access_key": "test-two"}).status_code == 200
            payload.update(direction="out", request_id=str(uuid4()))
            departed = client.post("/api/scans", json=payload)
            assert departed.status_code == 200 and not departed.json()["inside"]
            assert client.delete("/api/session").status_code == 200
            assert connection.scalar(select(Teacher.inside).where(Teacher.id == teacher["id"])) is False
            assert connection.scalar(text("SELECT count(*) FROM scan_events WHERE teacher_pk=:teacher"),
                                     {"teacher": teacher["id"]}) == 2
        finally:
            transaction.rollback()
