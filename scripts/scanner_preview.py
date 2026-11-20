"""Run the populated GLHS scanner on loopback with a fresh fictional roster."""
import argparse
import secrets
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
import uvicorn
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.testclient import TestClient

from app.local_demo import NAMES
from app.main import STATIC, create_app

HOST = "glhs-scanner.localhost"


def build_preview(directory):
    admin_key = secrets.token_urlsafe(32)
    station_key = secrets.token_urlsafe(32)
    app = create_app(
        f"sqlite:///{directory / 'preview.db'}", admin_key,
        {"front-1": station_key, "front-2": secrets.token_urlsafe(32)}, [HOST],
    )
    options = []
    with TestClient(app, base_url=f"http://{HOST}") as client:
        for index, name in enumerate(NAMES, 1):
            teacher = client.post("/api/teachers", headers={"X-Admin-Key": admin_key},
                                  json={"teacher_id": f"DEMO-{index:03}", "name": name})
            teacher.raise_for_status()
            code = teacher.json()["badge_code"]
            options.append(f'<option value="{escape(code)}">{escape(name)}</option>')
            # Leave the first teacher unrecorded for the visitor's first check-in.
            directions = {2: ("in", "out"), 3: ("in",), 4: ("in",)}.get(index, ())
            for direction in directions:
                client.post("/api/scans", headers={"X-Station-Key": station_key}, json={
                    "code": code, "direction": direction, "request_id": str(uuid4()),
                }).raise_for_status()

    picker = f"""<div id="sample-kit" class="inline-form">
      <label for="sample-badge">Fictional teacher
        <select id="sample-badge">{''.join(options)}</select>
      </label>
      <button id="try-badge" type="button" class="secondary">Scan sample badge</button>
    </div>"""
    html = (STATIC / "index.html").read_text().replace(
        '<div id="scan-feedback"', picker + '\n<div id="scan-feedback"'
    ).replace("</head>", '<script defer src="/preview.js"></script>\n</head>')

    @app.get("/scanner")
    async def scanner():
        # Issue the same station-only cookie as a station key sign-in.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{HOST}") as login_client:
            login = await login_client.post("/api/session", json={"role": "station", "access_key": station_key})
            login.raise_for_status()
        return HTMLResponse(html, headers={"Set-Cookie": login.headers["set-cookie"]})

    @app.get("/preview.js")
    def script():
        return FileResponse(Path(__file__).with_suffix(".js"), media_type="application/javascript")

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18434)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535.")
    with TemporaryDirectory(prefix="glhs-scanner-") as directory:
        app = build_preview(Path(directory))
        print(f"Open http://{HOST}:{args.port}/scanner", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
