from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.absences import school_today
from app.attention import SCHOOL_ZONE, day_start
from app.main import create_app
from app.models import ScanEvent, Teacher
from test_absences import change, plan
from test_checkin import ADMIN, ONE, TWO, client, scan, teacher


@pytest.fixture(autouse=True)
def school_clock(monkeypatch):
    class SchoolClock(datetime):
        current = datetime.now(SCHOOL_ZONE).replace(hour=12, minute=0, second=0, microsecond=0)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.delenv("ARRIVAL_CUTOFF", raising=False)
    monkeypatch.setattr("app.attention.datetime", SchoolClock)
    monkeypatch.setattr("app.main.time", SimpleNamespace(time=lambda: SchoolClock.current.timestamp()))
    return SchoolClock


def attention(client):
    response = client.get("/api/attention", headers=ADMIN)
    assert response.status_code == 200
    return response.json()


def kinds(data):
    return [entry["kind"] for entry in data["items"]]


def recorded_in_yesterday(client, person):
    """Simulate an arrival scan from an earlier school day with no departure afterwards."""
    earlier = day_start(school_today()) - 6 * 3600
    with Session(client.app.state.engine) as session:
        staff = session.get(Teacher, person["id"])
        staff.inside, staff.last_seen = True, earlier
        session.add(ScanEvent(teacher_pk=staff.id, request_id=str(uuid4()), direction="in",
                              station="front-1", occurred_at=earlier, changed=True))
        session.commit()


def test_today_exceptions_are_listed_in_priority_order_without_writing_records(client):
    today = school_today().isoformat()
    working = teacher(client, "Alex Morgan", "001")
    uncovered = teacher(client, "Jordan Rivera", "002")
    lingering = teacher(client, "Taylor Chen", "003")
    arrived = teacher(client, "Sam Patel", "004")
    missing = teacher(client, "Casey Brooks", "005")
    plan(client, working, "Pat Lee", today)
    plan(client, uncovered, None, today)
    assert scan(client, working["badge_code"]).status_code == 200
    assert scan(client, arrived["badge_code"]).status_code == 200
    recorded_in_yesterday(client, lingering)
    before = client.get("/api/events", headers=ADMIN).json()
    data = attention(client)
    assert data["today"] == today
    assert kinds(data)[:3] == ["planned_out_but_in", "needs_cover_today", "stale_in"]
    conflict = data["items"][0]
    assert conflict["teacher_pk"] == working["id"] and "release Pat Lee" in conflict["detail"]
    assert [action["type"] for action in conflict["actions"]] == ["cancel_absence", "correct"]
    stale = data["items"][2]
    assert stale["actions"] == [{"type": "correct", "label": "Record OUT", "teacher_pk": lingering["id"],
                                 "direction": "out", "reason": "Missed departure scan"}]
    assert data["coverage"] == {"planned": 2, "covered": 1, "unassigned": 1}
    assert {entry["teacher_pk"] for entry in data["planned_today"]} == {working["id"], uncovered["id"]}
    if school_today().weekday() < 5:
        assert data["not_arrived"] == [missing["id"]] and kinds(data)[-1] == "not_arrived"
    else:
        assert data["not_arrived"] == [] and "not_arrived" not in kinds(data)
    assert client.get("/api/events", headers=ADMIN).json() == before
    people = {person["id"]: person for person in client.get("/api/teachers", headers=ADMIN).json()}
    assert people[missing["id"]]["presence"] == "unrecorded" and people[lingering["id"]]["presence"] == "in"


def test_resolving_items_removes_them(client):
    today = school_today().isoformat()
    lingering = teacher(client, "Taylor Chen", "003")
    uncovered = teacher(client, "Jordan Rivera", "002")
    entry = plan(client, uncovered, None, today).json()
    recorded_in_yesterday(client, lingering)
    assert {"stale_in", "needs_cover_today"} <= set(kinds(attention(client)))
    # A repeat arrival scan keeps last_seen from yesterday but proves a scan today.
    repeat = scan(client, lingering["badge_code"]).json()
    assert not repeat["changed"]
    assert change(client, entry, "Pat Lee").status_code == 200
    remaining = kinds(attention(client))
    assert "stale_in" not in remaining and "needs_cover_today" not in remaining


def test_upcoming_gaps_group_by_plan_and_double_bookings_are_flagged(client):
    today = school_today()
    tomorrow = (today + timedelta(days=1)).isoformat()
    away = teacher(client, "Avery Garcia", "006")
    first, second = teacher(client, "Riley Thompson", "007"), teacher(client, "Jamie Wilson", "008")
    plan(client, away, None, tomorrow, school_days=3)
    plan(client, first, "Pat Lee", tomorrow)
    plan(client, second, " pat  lee ", tomorrow)
    data = attention(client)
    upcoming = [entry for entry in data["items"] if entry["kind"] == "needs_cover_upcoming"]
    assert len(upcoming) == 1 and upcoming[0]["title"] == "Avery Garcia needs cover on 3 upcoming school days"
    assert upcoming[0]["actions"][0]["type"] == "edit_cover" and upcoming[0]["day"] == tomorrow
    booked = [entry for entry in data["items"] if entry["kind"] == "double_booked"]
    assert len(booked) == 1 and booked[0]["title"].startswith("Pat Lee is assigned to 2 staff")
    assert booked[0]["actions"] == [{"type": "open_day", "label": "Review day", "day": tomorrow}]
    assert data["coverage"]["planned"] == 0


def test_cancelled_plans_inactive_staff_and_stations_are_excluded(client):
    today = school_today().isoformat()
    leaving = teacher(client, "Former Staff", "009")
    cancelled = teacher(client, "Jordan Rivera", "002")
    plan(client, leaving, None, today)
    change(client, plan(client, cancelled, None, today).json(), cancelled=True)
    assert client.patch(f"/api/teachers/{leaving['id']}", headers=ADMIN).status_code == 200
    data = attention(client)
    assert "needs_cover_today" not in kinds(data) and data["coverage"]["planned"] == 0
    assert leaving["id"] not in data["not_arrived"]
    assert client.get("/api/attention", headers=ONE).status_code == 401
    assert client.get("/api/attention", headers=TWO).status_code == 401
    assert client.get("/api/attention").status_code == 401


@pytest.mark.parametrize("instant,active", [
    ("2026-10-19T11:29:59+00:00", False),  # 7:29:59 Eastern during daylight time
    ("2026-10-19T11:30:00+00:00", True),
    ("2026-12-07T12:29:59+00:00", False),  # Same local cutoff during standard time
    ("2026-12-07T12:30:00+00:00", True),
    ("2026-10-17T12:00:00+00:00", False),  # Saturday
    ("2026-10-18T12:00:00+00:00", False),  # Sunday
])
def test_morning_review_opens_at_730_eastern_on_weekdays(client, school_clock, instant, active):
    school_clock.current = datetime.fromisoformat(instant)
    missing = teacher(client)
    data = attention(client)
    assert data["arrival_cutoff"] == "07:30"
    assert data["arrival_check_active"] is active
    assert data["not_arrived"] == ([missing["id"]] if active else [])
    assert ("not_arrived" in kinds(data)) is active
    if active:
        assert "not checked in today" in data["items"][-1]["title"]


def test_before_cutoff_only_the_morning_list_is_suppressed(client, school_clock):
    school_clock.current = datetime(2026, 10, 19, 7, 15, tzinfo=SCHOOL_ZONE)
    missing = teacher(client)
    away = teacher(client, "Jordan Rivera", "002")
    plan(client, away, None, "2026-10-19")
    data = attention(client)
    assert kinds(data) == ["needs_cover_today"]
    assert data["not_arrived"] == []
    assert data["coverage"]["unassigned"] == 1
    assert client.get("/api/teachers", headers=ADMIN).json()[0]["presence"] == "unrecorded"
    assert client.get("/api/events", headers=ADMIN).json() == []


def test_late_arrival_departure_and_return_keep_current_presence_and_morning_review_separate(client, school_clock):
    school_clock.current = datetime(2026, 10, 19, 7, 30, tzinfo=SCHOOL_ZONE)
    person = teacher(client)
    assert attention(client)["not_arrived"] == [person["id"]]
    for hour, direction, station in [(9, "in", ONE), (12, "out", TWO), (13, "in", ONE), (16, "out", TWO)]:
        school_clock.current = school_clock.current.replace(hour=hour)
        result = scan(client, person["badge_code"], direction, station)
        assert result.status_code == 200 and result.json()["changed"]
        assert attention(client)["not_arrived"] == []
        assert "not_arrived" not in kinds(attention(client))
        current = client.get("/api/teachers", headers=ADMIN).json()[0]
        assert current["presence"] == direction
    history = client.get("/api/events", headers=ADMIN).json()
    assert [event["direction"] for event in history] == ["out", "in", "out", "in"]
    # A new weekday reviews arrivals again; yesterday's check-ins don't satisfy today.
    school_clock.current = datetime(2026, 10, 20, 7, 30, tzinfo=SCHOOL_ZONE)
    assert attention(client)["not_arrived"] == [person["id"]]


def test_arrival_before_cutoff_still_counts_after_an_early_departure(client, school_clock):
    school_clock.current = datetime(2026, 10, 19, 7, 0, tzinfo=SCHOOL_ZONE)
    person = teacher(client)
    assert scan(client, person["badge_code"]).status_code == 200
    school_clock.current = school_clock.current.replace(minute=15)
    assert scan(client, person["badge_code"], "out", TWO).status_code == 200
    school_clock.current = school_clock.current.replace(minute=30)
    assert attention(client)["arrival_check_active"]
    assert attention(client)["not_arrived"] == []


def test_configured_cutoff_is_used_for_morning_review(tmp_path, monkeypatch, school_clock):
    monkeypatch.setenv("ARRIVAL_CUTOFF", "08:00")
    app = create_app(f"sqlite:///{tmp_path / 'cutoff.db'}", "test-admin", {"front-1": "test-one", "front-2": "test-two"})
    with TestClient(app) as browser:
        person = teacher(browser)
        school_clock.current = datetime(2026, 10, 19, 7, 59, tzinfo=SCHOOL_ZONE)
        assert attention(browser)["not_arrived"] == []
        school_clock.current = school_clock.current.replace(hour=8, minute=0)
        data = attention(browser)
        assert data["arrival_cutoff"] == "08:00" and data["not_arrived"] == [person["id"]]


@pytest.mark.parametrize("value", ["7:30", "25:00", "07:60", "07:30+00:00"])
def test_invalid_arrival_cutoff_is_rejected_at_startup(tmp_path, monkeypatch, value):
    monkeypatch.setenv("ARRIVAL_CUTOFF", value)
    with pytest.raises(RuntimeError, match="ARRIVAL_CUTOFF"):
        create_app(f"sqlite:///{tmp_path / 'invalid.db'}", "test-admin", {"front-1": "test-one", "front-2": "test-two"})
