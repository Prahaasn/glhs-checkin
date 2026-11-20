from html.parser import HTMLParser
from uuid import uuid4

from fastapi.testclient import TestClient

from app.local_demo import NAMES
from scripts.scanner_preview import HOST, build_preview


class SamplePicker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_picker = False
        self.codes = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "select":
            self.in_picker = attrs.get("id") == "sample-badge"
        if self.in_picker and tag == "option":
            self.codes.append(attrs["value"])

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_picker = False


def test_populated_scanner_uses_station_permissions_and_real_scans(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "unsupported://should-never-be-used")
    with TestClient(build_preview(tmp_path), base_url=f"http://{HOST}") as client:
        assert client.get("/scanner", headers={"host": "example.org"}).status_code == 400
        page = client.get("/scanner")
        assert page.status_code == 200
        picker = SamplePicker()
        picker.feed(page.text)
        assert len(set(picker.codes)) == len(NAMES) == 8
        assert client.get("/preview.js").is_success
        assert client.get("/api/station").json() == {"station": "front-1"}
        assert client.get("/api/teachers").status_code == 401

        def scan(index, direction):
            result = client.post("/api/scans", json={
                "code": picker.codes[index], "direction": direction, "request_id": str(uuid4()),
            })
            result.raise_for_status()
            assert result.json()["name"] == NAMES[index]
            return result.json()["message"]

        assert scan(0, "in") == "Checked in"
        assert scan(0, "in") == "Already in"
        assert scan(0, "out") == "Checked out"
        assert scan(1, "out") == "Already out"
        assert scan(2, "in") == "Already in"
        assert client.delete("/api/session").is_success
        assert client.get("/api/station").status_code == 401
