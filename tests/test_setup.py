"""Setup checklist and batch badge issuance, using fictional staff only."""
import secrets
import string

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.badges import MAX_BATCH, code128_modules, qr_rows
from app.main import create_app
from app.models import Base, OfficeUser
from app.roster import SOURCE_URL, import_directory
from app.security import hash_password
from test_checkin import ADMIN, ONE, TWO, client, scan, teacher

KEYS = ("test-admin", {"front-1": "test-one", "front-2": "test-two"})


def imported(client, *names):
    """Fictional directory import: names only, no scans, no usable badges."""
    manifest = {"source_url": SOURCE_URL, "expected_total": len(names),
                "staff": [{"directory_id": str(index), "name": name} for index, name in enumerate(names, 100)]}
    import_directory(client.app.state.engine, manifest)
    by_name = {person["name"]: person for person in client.get("/api/teachers", headers=ADMIN).json()}
    return [by_name[name] for name in names]


def setup(client):
    response = client.get("/api/setup", headers=ADMIN)
    assert response.status_code == 200
    data = response.json()
    return data, {item["key"]: item for item in data["steps"]}


def batch(client, people, replace=False):
    return client.post("/api/badges/batch", headers=ADMIN,
                       json={"teacher_pks": [person["id"] for person in people], "replace_existing": replace})


def decode_code128(modules):
    """Independent check against reportlab's Code 128 table: modules back to symbol values."""
    table = pytest.importorskip("reportlab.graphics.barcode.code128")._patterns
    to_modules = lambda pattern: "".join(("1" if letter.isupper() else "0") * (ord(letter.lower()) - 96) for letter in pattern)
    lookup = {to_modules(pattern): value for value, pattern in table.items()}
    body, stop = modules[:-13], modules[-13:]
    assert lookup[stop] == 106 and len(body) % 11 == 0
    return [lookup[body[i:i + 11]] for i in range(0, len(body), 11)] + [106]


@pytest.mark.parametrize("value", [secrets.token_urlsafe(24) for _ in range(5)] + [" ~Az09-_", string.digits * 3])
def test_code128_encodes_subset_b_with_a_valid_checksum(value):
    symbols = decode_code128(code128_modules(value))
    assert symbols[0] == 104 and symbols[-1] == 106
    data, checksum = symbols[1:-2], symbols[-2]
    assert "".join(chr(symbol + 32) for symbol in data) == value
    assert checksum == (104 + sum(position * symbol for position, symbol in enumerate(data, 1))) % 103


def test_code128_rejects_text_it_cannot_encode():
    for value in ("", "café", "line\nbreak"):
        with pytest.raises(ValueError):
            code128_modules(value)


def test_qr_rows_are_square_with_a_quiet_zone_and_finder_patterns():
    rows = qr_rows(secrets.token_urlsafe(24))
    size = len(rows)
    assert size == 37 and all(len(row) == size and set(row) <= {"0", "1"} for row in rows)
    assert set(rows[0] + rows[3] + rows[-1]) == {"0"} and all(row[:4] == "0000" == row[-4:] for row in rows)
    for top, left in ((4, 4), (4, size - 11), (size - 11, 4)):
        assert rows[top][left:left + 7] == "1111111" and rows[top + 6][left:left + 7] == "1111111"


def test_single_badges_carry_printable_patterns_and_a_badge_date(client):
    person = teacher(client)
    assert person["badge_issued_at"] and len(person["qr"]) == 37 and set(person["code128"]) == {"0", "1"}
    replaced = client.post(f"/api/teachers/{person['id']}/badge", headers=ADMIN).json()
    assert replaced["teacher_id"] == "001" and replaced["code128"] == code128_modules(replaced["badge_code"])
    assert scan(client, person["badge_code"]).status_code == 404
    assert scan(client, replaced["badge_code"]).status_code == 200


def test_imported_staff_need_badges_and_one_batch_issues_working_codes(client):
    people = imported(client, "Riley Thompson", "Avery Garcia", "Jamie Wilson")
    assert all(person["badge_issued_at"] is None for person in people)
    data, steps = setup(client)
    assert sorted(data["badges"]["missing"]) == sorted(person["id"] for person in people)
    assert steps["badges"]["status"] == "todo" and steps["badges"]["actions"][0] == {"type": "print_missing", "label": "Print 3 badges"}
    result = batch(client, people)
    assert result.status_code == 200 and result.json()["replaced"] == 0
    issued = result.json()["issued"]
    assert [badge["name"] for badge in issued] == ["Avery Garcia", "Jamie Wilson", "Riley Thompson"]
    for badge in issued:
        assert badge["code128"] == code128_modules(badge["badge_code"]) and badge["qr"] == qr_rows(badge["badge_code"])
        assert scan(client, badge["badge_code"]).json()["name"] == badge["name"]
    data, steps = setup(client)
    assert data["badges"] == {"missing": [], "issued": 3} and steps["badges"]["status"] == "done"
    roster = client.get("/api/teachers", headers=ADMIN).json()
    assert all(person["badge_issued_at"] == result.json()["issued_at"] for person in roster)
    assert "badge_hash" not in str(roster) and "badge_code" not in str(roster)


def test_batch_needs_reviewed_replacement_and_never_issues_part_of_a_batch(client):
    carrying = teacher(client, "Alex Morgan", "001")
    waiting, = imported(client, "Sam Patel")
    refused = batch(client, [carrying, waiting])
    assert refused.status_code == 409 and "Alex Morgan already has a badge" in refused.json()["detail"]
    assert scan(client, carrying["badge_code"]).status_code == 200
    assert setup(client)[0]["badges"]["missing"] == [waiting["id"]]
    replaced = batch(client, [carrying, waiting], replace=True).json()
    assert replaced["replaced"] == 1
    assert scan(client, carrying["badge_code"]).status_code == 404
    codes = {badge["name"]: badge["badge_code"] for badge in replaced["issued"]}
    leaving = teacher(client, "Casey Brooks", "002")
    assert client.patch(f"/api/teachers/{leaving['id']}", headers=ADMIN).status_code == 200
    for people in ([waiting, leaving], [waiting, {"id": 99999}]):
        response = batch(client, people, replace=True)
        assert response.status_code == 409 and "no badges were issued" in response.json()["detail"]
    assert scan(client, codes["Sam Patel"]).status_code == 200


def test_batch_validates_its_selection(client):
    person = teacher(client)
    for payload in ({"teacher_pks": []}, {"teacher_pks": [person["id"], person["id"]]},
                    {"teacher_pks": list(range(1, MAX_BATCH + 2))}, {"teacher_pks": "all"},
                    {"teacher_pks": [10**30]}, {"teacher_pks": [0]}):
        response = client.post("/api/badges/batch", headers=ADMIN, json=payload)
        assert response.status_code == 422 and "Invalid request" in response.json()["detail"]


def test_station_and_signed_out_browsers_cannot_issue_badges_or_read_setup(client):
    person = teacher(client)
    for headers in (ONE, {}):
        assert client.get("/api/setup", headers=headers).status_code == 401
        assert client.post("/api/badges/batch", headers=headers, json={"teacher_pks": [person["id"]], "replace_existing": True}).status_code == 401
    assert scan(client, person["badge_code"]).status_code == 200


def test_checklist_follows_logins_staff_station_sign_ins_and_scans_today(client):
    data, steps = setup(client)
    assert [item["key"] for item in data["steps"]] == ["office", "roster", "badges", "stations", "test_scan", "network"]
    assert {key: item["status"] for key, item in steps.items()} == {
        "office": "todo", "roster": "todo", "badges": "todo", "stations": "todo", "test_scan": "todo", "network": "info"}
    assert data["remaining"] == 5 and data["lan"] is False and data["https"] is False
    with Session(client.app.state.engine) as session:
        session.add(OfficeUser(username="desk", display_name="Front Desk", password_hash=hash_password("fictional-pass-123")))
        session.commit()
    person = teacher(client)
    for key in ("test-one", "test-two"):
        assert client.post("/api/session", json={"role": "station", "access_key": key}).status_code == 200
        client.cookies.clear()  # Each station is its own browser; a second sign-in here would revoke the first.
    data, steps = setup(client)
    assert steps["office"]["status"] == "done" and "Add a second" in steps["office"]["detail"]
    assert steps["stations"]["status"] == "done" and all("signed in until" in line for line in steps["stations"]["lines"])
    assert steps["test_scan"]["status"] == "todo"
    scan(client, person["badge_code"], "in", ONE)
    steps = setup(client)[1]
    assert steps["test_scan"]["detail"] == "No scan recorded today at the departure station."
    scan(client, person["badge_code"], "out", TWO)
    data, steps = setup(client)
    assert steps["test_scan"]["status"] == "done" and data["remaining"] == 0
    assert "test-one" not in str(data) and "test-two" not in str(data) and "test-admin" not in str(data)


def test_checklist_warns_about_plain_http_on_a_network_and_accepts_https(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'lan.db'}", *KEYS, allowed_hosts=["testserver", "192.168.1.20"])
    with TestClient(app) as lan:
        data, steps = setup(lan)
        assert data["lan"] is True and steps["network"]["status"] == "warning"
    with TestClient(app, base_url="https://testserver") as secure:
        assert setup(secure)[1]["network"]["status"] == "done"


def test_imports_on_an_older_local_database_add_the_badge_column(tmp_path):
    url = f"sqlite:///{tmp_path / 'earlier.db'}"
    app = create_app(url, *KEYS)
    engine = app.state.engine
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE teachers DROP COLUMN badge_issued_at")
        connection.exec_driver_sql("INSERT INTO teachers (teacher_id, name, badge_hash, created_at, active, inside) "
                                   "VALUES ('T-1', 'Jordan Rivera', 'hash', 1, 1, 0)")
    # The command-line import runs without the server's startup hook.
    assert import_directory(engine, {"source_url": SOURCE_URL, "expected_total": 1,
                                     "staff": [{"directory_id": "7", "name": "Taylor Chen"}]})["added"] == 1
    with TestClient(app) as upgraded:
        data, _ = setup(upgraded)
        assert data["staff"]["active"] == 2 and len(data["badges"]["missing"]) == 2
