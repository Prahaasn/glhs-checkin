import json
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.local_demo import create_demo, demo_app
from app.models import OfficeUser
from app.security import verify_password


def settings(directory):
    return dict(line.split("=", 1) for line in (directory / "demo.env").read_text().splitlines())


def test_demo_starts_unknown_and_issued_cards_work_without_touching_school_data(tmp_path, monkeypatch):
    school = tmp_path / "school.db"
    school.write_bytes(b"existing school database")
    original_env = tmp_path / ".env"
    original_env.write_text("DATABASE_URL=school configuration\n")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{school}")
    monkeypatch.setenv("ADMIN_KEY", "unrelated key")
    directory = create_demo(tmp_path)
    config = settings(directory)
    app = demo_app(tmp_path, directory)
    badges = json.loads((directory / "badges.json").read_text())
    password = (directory / "office-login.txt").read_text().split("Password: ", 1)[1].strip()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/office-session", json={"username": "demo", "password": password}).status_code == 200
        roster = client.get("/api/teachers").json()
        assert len(roster) == 8 and all(row["presence"] == "unrecorded" for row in roster)
        assert client.get("/api/events").json() == []
        for badge in badges:
            response = client.post("/api/scans", headers={"X-Station-Key": config["STATION_1_KEY"]},
                                   json={"code": badge["code"], "direction": "in", "request_id": str(uuid4())})
            assert response.status_code == 200 and response.json()["name"] == badge["name"]
        assert all(row["presence"] == "in" for row in client.get("/api/teachers").json())
    assert school.read_bytes() == b"existing school database"
    assert original_env.read_text() == "DATABASE_URL=school configuration\n"
    assert (directory / "staff-badges.pdf").read_bytes().startswith(b"%PDF-")
    with Session(app.state.engine) as session:
        stored = session.scalar(select(OfficeUser)).password_hash
        assert verify_password(password, stored) and password not in stored


def test_another_demo_preserves_existing_badges_scans_and_credentials(tmp_path):
    first = create_demo(tmp_path)
    config = settings(first)
    badge_file = (first / "badges.json").read_bytes()
    credentials = (first / "office-login.txt").read_bytes()
    badge = json.loads(badge_file)[0]
    with TestClient(demo_app(tmp_path, first), base_url="http://127.0.0.1") as client:
        assert client.post("/api/scans", headers={"X-Station-Key": config["STATION_1_KEY"]},
                           json={"code": badge["code"], "direction": "in", "request_id": str(uuid4())}).status_code == 200
    second = create_demo(tmp_path)
    assert first != second
    assert (first / "badges.json").read_bytes() == badge_file
    assert (first / "office-login.txt").read_bytes() == credentials
    with TestClient(demo_app(tmp_path, first), base_url="http://127.0.0.1") as client:
        assert len(client.get("/api/events", headers={"X-Admin-Key": config["ADMIN_KEY"]}).json()) == 1


def test_demo_artifacts_are_private(tmp_path):
    directory = create_demo(tmp_path, port=8330)
    assert os.stat(directory).st_mode & 0o777 == 0o700
    for file in directory.iterdir():
        assert os.stat(file).st_mode & 0o777 == (0o700 if file.name == "start.command" else 0o600)
    assert "--port 8330" in (directory / "start.command").read_text()


def test_demo_rejects_data_symlinks_and_invalid_port(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "data").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError):
        create_demo(tmp_path)
    assert list(elsewhere.iterdir()) == []
    with pytest.raises(ValueError):
        create_demo(tmp_path, port=0)


def test_demo_server_rejects_a_redirected_database(tmp_path):
    directory = create_demo(tmp_path)
    env = directory / "demo.env"
    env.write_text(env.read_text().replace(str(directory / "demo.db"), str(tmp_path / "school.db")))
    with pytest.raises(ValueError, match="own local database"):
        demo_app(tmp_path, directory)
    assert not (tmp_path / "school.db").exists()


def test_demo_server_ignores_inherited_host_and_database_configuration(tmp_path, monkeypatch):
    directory = create_demo(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://invalid")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    with TestClient(demo_app(tmp_path, directory), base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health", headers={"Host": "untrusted.example"}).status_code == 400
    assert os.environ["ALLOWED_HOSTS"] == "*"
