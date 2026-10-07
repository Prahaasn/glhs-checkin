from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import date
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Base, OfficeUser, Teacher
from app.security import hash_password
from test_checkin import ADMIN, ONE, client, scan, teacher

DAY = "2026-10-07"
THURSDAY = "2026-10-08"


def plan(client, person, substitute=None, day=DAY, school_days=None):
    payload = {"teacher_pk": person["id"], "day": day, "substitute_name": substitute}
    if school_days is not None:
        payload["school_days"] = school_days
    return client.post("/api/absences", headers=ADMIN, json=payload)


def change(client, entry, substitute=None, cancelled=False, headers=ADMIN, later=None):
    payload = {"version": entry["version"], "substitute_name": substitute, "cancelled": cancelled}
    if later is not None:
        payload |= {"scope": "following", "versions": {str(day["id"]): day["version"] for day in later}}
    return client.patch(f"/api/absences/{entry['id']}", headers=headers, json=payload)


def on(client, day, cancelled=False):
    query = f"/api/absences?day={day}" + ("&include_cancelled=true" if cancelled else "")
    return client.get(query, headers=ADMIN).json()["entries"]


def later_days(entry):
    return [day for day in entry["series"]["days"] if day["day"] > entry["day"] and day["cancelled"] == entry["cancelled"]]


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
    # Reviewed migrations apply in filename order to a database that predates coverage.
    migrations = sorted((Path(__file__).resolve().parents[1] / "docs/migrations").glob("*.sql"))
    assert [path.name for path in migrations] == ["2026-10-07-absence-coverage.sql", "2026-10-08-absence-series.sql"]
    raw = engine.raw_connection()
    try:
        driver = raw.driver_connection
        driver.autocommit = True
        with driver.cursor() as cursor:
            for migration in migrations:
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
    series = plan(client, person, day=THURSDAY, school_days=3).json()
    assert len(series["series"]["days"]) == 3


def test_restore_waits_for_deactivation_and_rechecks_committed_staff_state(client):
    engine = client.app.state.engine
    if engine.dialect.name != "postgresql":
        pytest.skip("SQLite serializes all writers; this exercises PostgreSQL row-lock contention.")
    person = teacher(client)
    entry = change(client, plan(client, person).json(), cancelled=True).json()
    attempted_read = Event()

    def observe_read(connection, cursor, statement, parameters, context, executemany):
        if "select" in statement.lower() and "teachers" in statement.lower():
            attempted_read.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(engine) as deactivation:
            deactivation.get(Teacher, person["id"]).active = False
            deactivation.flush()  # Hold the same teacher-row write lock as deactivation.
            event.listen(engine, "before_cursor_execute", observe_read)
            future = executor.submit(change, client, entry)
            try:
                assert attempted_read.wait(5), "Restore did not reach the teacher read"
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.5)
            finally:
                deactivation.commit()
                event.remove(engine, "before_cursor_execute", observe_read)
        assert future.result(timeout=5).status_code == 409
    assert not client.get("/api/teachers", headers=ADMIN).json()[0]["active"]
    plans = client.get(f"/api/absences?day={DAY}&include_cancelled=true", headers=ADMIN).json()
    assert plans["entries"][0]["cancelled"] and plans["planned"] == 0


def test_school_days_skip_weekends_and_form_one_plan_without_scans(client):
    person = teacher(client)
    entry = plan(client, person, "Pat Lee", THURSDAY, school_days=4).json()
    assert [day["day"] for day in entry["series"]["days"]] == ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"]
    assert entry["series"]["position"] == 1 and entry["series"]["total"] == 4
    assert on(client, "2026-10-10") == [] and on(client, "2026-10-11") == []
    monday = on(client, "2026-10-12")[0]
    assert monday["series_id"] == entry["series_id"] and monday["series"]["position"] == 3
    upcoming = client.get("/api/absences/range?start=2026-10-07&end=2026-10-20", headers=ADMIN).json()
    assert [day["day"] for day in upcoming["days"]] == ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"]
    assert upcoming["planned"] == upcoming["covered"] == 4 and upcoming["unassigned"] == 0
    assert "days" not in upcoming["days"][0]["entries"][0]["series"]
    assert all(len(client.get(f"/api/absences/{day['id']}/changes", headers=ADMIN).json()) == 1
               for day in entry["series"]["days"])
    assert client.get("/api/events", headers=ADMIN).json() == []
    assert client.get("/api/teachers", headers=ADMIN).json()[0]["presence"] == "unrecorded"


def test_single_day_and_weekend_start_keep_the_chosen_date(client):
    person = teacher(client)
    single = plan(client, person, day="2026-10-10").json()
    assert single["day"] == "2026-10-10" and single["series_id"] is None and single["series"] is None
    weekend_start = plan(client, person, day="2026-10-11", school_days=2).json()
    assert [day["day"] for day in weekend_start["series"]["days"]] == ["2026-10-11", "2026-10-12"]


def test_overlapping_plan_is_rejected_without_partial_days(client):
    person = teacher(client)
    assert plan(client, person, day="2026-10-12").status_code == 201
    response = plan(client, person, day=THURSDAY, school_days=4)
    assert response.status_code == 409 and "Mon Oct 12" in response.json()["detail"]
    assert on(client, THURSDAY) == [] and on(client, "2026-10-09") == []
    other = teacher(client, "Jordan Rivera", "002")
    assert plan(client, other, day=THURSDAY, school_days=4).status_code == 201


def test_following_days_take_new_cover_and_return_early_cancels_the_rest(client):
    person = teacher(client)
    first = plan(client, person, day=THURSDAY, school_days=4).json()
    friday = on(client, "2026-10-09")[0]
    updated = change(client, friday, "Pat Lee", later=later_days(friday)).json()
    assert updated["changed_days"] == 3 and updated["substitute_name"] == "Pat Lee"
    assert on(client, THURSDAY)[0]["substitute_name"] is None
    assert [on(client, day)[0]["substitute_name"] for day in ("2026-10-12", "2026-10-13")] == ["Pat Lee", "Pat Lee"]
    assert [item["action"] for item in client.get(f"/api/absences/{first['id']}/changes", headers=ADMIN).json()] == ["created"]
    monday = on(client, "2026-10-12")[0]
    cancelled = change(client, monday, "Pat Lee", cancelled=True, later=later_days(monday)).json()
    assert cancelled["changed_days"] == 2 and cancelled["series"]["planned"] == 2
    assert on(client, "2026-10-12") == [] and on(client, "2026-10-13") == []
    monday = on(client, "2026-10-12", cancelled=True)[0]
    restored = change(client, monday, "Pat Lee", later=later_days(monday)).json()
    assert restored["changed_days"] == 2 and len(on(client, "2026-10-13")) == 1
    history = client.get(f"/api/absences/{monday['id']}/changes", headers=ADMIN).json()
    assert [item["action"] for item in history] == ["restored", "cancelled", "updated", "created"]
    assert client.get("/api/events", headers=ADMIN).json() == []


def test_stale_later_day_blocks_the_whole_following_change(client):
    person = teacher(client)
    plan(client, person, day=THURSDAY, school_days=4)
    friday = on(client, "2026-10-09")[0]
    reviewed = later_days(friday)
    tuesday = on(client, "2026-10-13")[0]
    assert change(client, tuesday, "Someone Else").status_code == 200
    response = change(client, friday, "Pat Lee", later=reviewed)
    assert response.status_code == 409 and "later days" in response.json()["detail"]
    assert [on(client, day)[0]["substitute_name"] for day in ("2026-10-09", "2026-10-12", "2026-10-13")] == [None, None, "Someone Else"]
    assert change(client, friday, "Pat Lee", later=reviewed[:1]).status_code == 409
    assert change(client, friday, "Pat Lee", later=later_days(on(client, "2026-10-09")[0])).status_code == 200


def test_school_day_and_range_limits_are_validated(client):
    person = teacher(client)
    for count in (0, 91, "many"):
        assert plan(client, person, school_days=count).status_code == 422
    assert client.get("/api/absences/range?start=2026-10-08&end=2026-10-07", headers=ADMIN).status_code == 400
    assert client.get("/api/absences/range?start=2026-10-01&end=2026-12-31", headers=ADMIN).status_code == 400
    assert client.get("/api/absences/range?start=2026-10-01&end=2026-10-02", headers=ONE).status_code == 401
    assert client.get("/api/substitutes", headers=ONE).status_code == 401


def test_substitute_suggestions_reuse_recent_names(client, monkeypatch):
    monkeypatch.setattr("app.absences.school_today", lambda: date(2026, 10, 7))
    people = [teacher(client, f"Staff {index}", f"00{index}") for index in range(4)]
    plan(client, people[0], "Pat Lee", "2026-10-05")
    plan(client, people[1], "Jordan Gray", "2026-10-09", school_days=2)
    plan(client, people[2], "Pat Lee", "2026-10-06")
    change(client, plan(client, people[3], "Cancelled Name", DAY).json(), "Cancelled Name", cancelled=True)
    suggestions = client.get("/api/substitutes", headers=ADMIN).json()
    assert [item["name"] for item in suggestions] == ["Jordan Gray", "Pat Lee"]
    assert suggestions[0] == {"name": "Jordan Gray", "last_day": "2026-10-12", "assignments": 2}


def test_sqlite_upgrade_adds_plan_column_and_keeps_existing_entries(tmp_path):
    url = f"sqlite:///{tmp_path / 'earlier.db'}"
    app = create_app(url, "test-admin", {"front-1": "test-one", "front-2": "test-two"})
    engine = app.state.engine
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_teacher_absences_series_id")
        connection.exec_driver_sql("ALTER TABLE teacher_absences DROP COLUMN series_id")
        connection.exec_driver_sql("INSERT INTO teachers (teacher_id, name, badge_hash, created_at, active, inside) "
                                   "VALUES ('001', 'Alex Morgan', 'hash', 1, 1, 0)")
        connection.exec_driver_sql("INSERT INTO teacher_absences (teacher_pk, day, substitute_name, cancelled, "
                                   "version, updated_at) VALUES (1, '2026-10-07', 'Pat Lee', 0, 1, 1)")
    with TestClient(app) as upgraded:
        existing = on(upgraded, DAY)[0]
        assert existing["substitute_name"] == "Pat Lee" and existing["series_id"] is None
        assert plan(upgraded, {"id": 1}, day=THURSDAY, school_days=2).status_code == 201
    with TestClient(app) as restarted:
        assert len(on(restarted, THURSDAY)) == 1
