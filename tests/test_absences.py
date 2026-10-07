from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import OfficeUser
from app.security import hash_password
from test_checkin import ADMIN, ONE, client, scan, teacher

DAY = "2026-10-07"


def plan(client, person, substitute=None, day=DAY):
    return client.post("/api/absences", headers=ADMIN,
                       json={"teacher_pk": person["id"], "day": day, "substitute_name": substitute})


def change(client, entry, substitute=None, cancelled=False, headers=ADMIN):
    return client.patch(f"/api/absences/{entry['id']}", headers=headers,
                        json={"version": entry["version"], "substitute_name": substitute, "cancelled": cancelled})


def test_planned_coverage_never_invents_or_reverses_attendance(client):
    person = teacher(client)
    entry = plan(client, person, "Pat Lee").json()
    assert entry["presence"] == "unrecorded"
    assert client.get("/api/events", headers=ADMIN).json() == []
    assert len(client.get("/api/teachers", headers=ADMIN).json()) == 1
    assert scan(client, person["badge_code"]).status_code == 200
    data = client.get(f"/api/absences?day={DAY}", headers=ADMIN).json()
    assert data["planned"] == data["covered"] == 1 and data["unassigned"] == 0
    assert data["entries"][0]["presence"] == "in"
    assert change(client, entry, "Another Substitute").status_code == 200
    assert client.get("/api/teachers", headers=ADMIN).json()[0]["presence"] == "in"
    assert len(client.get("/api/events", headers=ADMIN).json()) == 1


def test_date_filter_and_unassigned_coverage_use_the_school_day(client, monkeypatch):
    monkeypatch.setattr("app.absences.school_today", lambda: date(2026, 10, 7))
    person = teacher(client)
    assert plan(client, person, "   ").json()["substitute_name"] is None
    assert plan(client, person, "Pat Lee", "2026-10-08").status_code == 201
    today = client.get("/api/absences", headers=ADMIN).json()
    assert today["day"] == today["today"] == DAY
    assert today["planned"] == today["unassigned"] == 1 and today["covered"] == 0
    assert client.get("/api/absences?day=2026-10-09", headers=ADMIN).json()["entries"] == []


def test_named_office_can_reassign_cancel_restore_and_review_audit(client):
    person = teacher(client)
    with Session(client.app.state.engine) as session:
        session.add(OfficeUser(username="desk", display_name="Front Desk", password_hash=hash_password("office testing password")))
        session.commit()
    assert client.post("/api/office-session", json={"username": "desk", "password": "office testing password"}).status_code == 200
    entry = client.post("/api/absences", json={"teacher_pk": person["id"], "day": DAY, "substitute_name": " Pat Lee "}).json()
    assert entry["substitute_name"] == "Pat Lee" and entry["updated_by"] == "Front Desk"
    entry = change(client, entry, "Jordan Gray", headers={}).json()
    entry = change(client, entry, "Jordan Gray", cancelled=True, headers={}).json()
    assert client.get(f"/api/absences?day={DAY}").json()["planned"] == 0
    cancelled = client.get(f"/api/absences?day={DAY}&include_cancelled=true").json()
    assert cancelled["entries"][0]["cancelled"] and cancelled["covered"] == 0
    entry = change(client, entry, "Jordan Gray", headers={}).json()
    assert entry["version"] == 4 and not entry["cancelled"]
    changes = client.get(f"/api/absences/{entry['id']}/changes").json()
    assert [item["action"] for item in changes] == ["restored", "cancelled", "updated", "created"]
    assert all(item["actor"] == "Front Desk" for item in changes)
    assert client.get("/api/events").json() == []


def test_station_cannot_read_or_manage_planned_coverage(client):
    person = teacher(client)
    entry = plan(client, person).json()
    assert client.get("/api/absences", headers=ONE).status_code == 401
    assert client.post("/api/absences", headers=ONE, json={"teacher_pk": person["id"], "day": DAY, "substitute_name": None}).status_code == 401
    assert change(client, entry, headers=ONE).status_code == 401
    assert client.get(f"/api/absences/{entry['id']}/changes", headers=ONE).status_code == 401


def test_duplicate_date_invalid_fields_and_inactive_staff_are_rejected(client):
    person = teacher(client)
    entry = plan(client, person).json()
    assert plan(client, person).status_code == 409
    for field, value in [("day", "bad-date"), ("teacher_pk", 0), ("substitute_name", "x"*121), ("substitute_name", "Pat\nLee")]:
        payload = {"teacher_pk": person["id"], "day": DAY, "substitute_name": None, field: value}
        assert client.post("/api/absences", headers=ADMIN, json=payload).status_code == 422
    entry = change(client, entry, cancelled=True).json()
    assert plan(client, person).status_code == 409
    assert client.patch(f"/api/teachers/{person['id']}", headers=ADMIN).status_code == 200
    assert change(client, entry).status_code == 409
    assert plan(client, person, day="2026-10-08").status_code == 409
    assert plan(client, {"id": 99999}).status_code == 404
    assert client.get("/api/absences/99999/changes", headers=ADMIN).status_code == 404


def test_two_offices_cannot_silently_overwrite_the_same_absence(client):
    entry = plan(client, teacher(client), "Initial Substitute").json()
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda name: change(client, entry, name), ["Pat Lee", "Jordan Gray"]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    changes = client.get(f"/api/absences/{entry['id']}/changes", headers=ADMIN).json()
    assert len(changes) == 2 and changes[0]["version"] == 2
    unchanged = client.get(f"/api/absences?day={DAY}", headers=ADMIN).json()["entries"][0]
    assert change(client, unchanged, unchanged["substitute_name"]).json()["version"] == 2
    assert len(client.get(f"/api/absences/{entry['id']}/changes", headers=ADMIN).json()) == 2


def test_simultaneous_planning_creates_one_entry_and_one_audit_change(client):
    person = teacher(client)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: plan(client, person, "Pat Lee"), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    entries = client.get(f"/api/absences?day={DAY}", headers=ADMIN).json()["entries"]
    assert len(entries) == 1
    assert len(client.get(f"/api/absences/{entries[0]['id']}/changes", headers=ADMIN).json()) == 1


def test_postgres_migration_preserves_existing_scans_and_supports_coverage(client):
    engine = client.app.state.engine
    if engine.dialect.name != "postgresql":
        pytest.skip("The explicit hosted migration targets PostgreSQL; SQLite bootstraps locally.")
    person = teacher(client)
    assert scan(client, person["badge_code"]).status_code == 200
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE school_checkin.absence_changes, school_checkin.teacher_absences"))
    migration = Path(__file__).resolve().parents[1] / "docs/migrations/2026-10-07-absence-coverage.sql"
    raw = engine.raw_connection()
    try:
        driver = raw.driver_connection
        driver.autocommit = True
        with driver.cursor() as cursor:
            cursor.execute(migration.read_text(), prepare=False)
        driver.autocommit = False
    finally:
        raw.close()
    assert client.get("/api/teachers", headers=ADMIN).json()[0]["presence"] == "in"
    assert len(client.get("/api/events", headers=ADMIN).json()) == 1
    entry = plan(client, person, "Pat Lee").json()
    assert entry["presence"] == "in" and entry["substitute_name"] == "Pat Lee"
    assert change(client, entry, "Jordan Gray").status_code == 200
    assert len(client.get(f"/api/absences/{entry['id']}/changes", headers=ADMIN).json()) == 2
