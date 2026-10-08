from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.absences import school_today
from app.attention import day_start
from app.models import ScanEvent, Teacher
from test_absences import change, plan
from test_checkin import ADMIN, ONE, TWO, client, scan, teacher


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
