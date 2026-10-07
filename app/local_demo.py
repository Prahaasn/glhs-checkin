"""Create and serve an isolated, persistent scanner rehearsal from the real app."""
import argparse
import json
import os
import secrets
import shlex
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo_badges import render_badges
from app.main import badge_hash, create_app
from app.models import Base, OfficeUser, Teacher
from app.security import hash_password

NAMES = ("Alex Morgan", "Jordan Rivera", "Taylor Chen", "Sam Patel",
         "Casey Brooks", "Riley Thompson", "Jamie Wilson", "Avery Garcia")


def private_file(path, content, mode=0o600):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "wb") as file:
        file.write(content.encode() if isinstance(content, str) else content)


def data_directory(root):
    root = root.resolve()
    data = root / "data"
    if data.is_symlink():
        raise ValueError("Demo data must stay inside the checkout's data directory.")
    data.mkdir(mode=0o700, exist_ok=True)
    return data


def create_demo(root, port=8317):
    if not 1 <= port <= 65535:
        raise ValueError("Choose a port between 1 and 65535.")
    root = root.resolve()
    run_dir = Path(tempfile.mkdtemp(prefix="scanner-demo-", dir=data_directory(root)))
    settings = {"DATABASE_URL": f"sqlite:///{run_dir / 'demo.db'}",
                **{key: secrets.token_urlsafe(32) for key in
                   ("ADMIN_KEY", "STATION_1_KEY", "STATION_2_KEY")},
                "ALLOWED_HOSTS": "127.0.0.1,localhost"}
    password = secrets.token_urlsafe(18)
    app = create_app(settings["DATABASE_URL"], settings["ADMIN_KEY"],
                     {"front-1": settings["STATION_1_KEY"], "front-2": settings["STATION_2_KEY"]},
                     allowed_hosts=["127.0.0.1", "localhost"])
    badges = []
    try:
        Base.metadata.create_all(app.state.engine)
        with Session(app.state.engine) as session:
            for index, name in enumerate(NAMES, 1):
                code = secrets.token_urlsafe(24)
                staff = Teacher(name=name, teacher_id=f"DEMO-{index:03}", badge_hash=badge_hash(code))
                session.add(staff)
                session.flush()
                badges.append({"id": staff.id, "name": name, "teacher_id": staff.teacher_id, "code": code})
            session.add(OfficeUser(username="demo", display_name="Local demo office",
                                   password_hash=hash_password(password)))
            session.commit()
    finally:
        app.state.engine.dispose()
    (run_dir / "demo.db").chmod(0o600)
    private_file(run_dir / "demo.env", "\n".join(f"{key}={value}" for key, value in settings.items()) + "\n")
    private_file(run_dir / "office-login.txt", f"Username: demo\nPassword: {password}\n")
    private_file(run_dir / "badges.json", json.dumps(badges, indent=2))
    private_file(run_dir / "staff-badges.pdf", render_badges(badges))
    uv = shutil.which("uv") or "uv"
    command = " ".join(shlex.quote(value) for value in (
        uv, "run", "--extra", "demo", "python", "-m", "app.local_demo", "serve",
        str(run_dir), "--port", str(port)))
    private_file(run_dir / "start.command",
                 f"#!/bin/sh\nset -eu\ncd {shlex.quote(str(root))}\nexec {command}\n", 0o700)
    private_file(run_dir / "START-HERE.md", f"""# Fresh local scanner demo

Eight fictional staff start as Not recorded. These cards work only with this demo.

1. Run start.command to start the server.
2. Office dashboard: http://127.0.0.1:{port}/ . Choose Office staff; use office-login.txt locally.
3. Scanner station: http://localhost:{port}/ . Choose Scanner station; locally copy STATION_1_KEY from demo.env for arrivals, or STATION_2_KEY for departures.
4. Print staff-badges.pdf at Actual size / 100%. Each Code128 barcode and QR code encode the same badge token.
5. Set a USB scanner to keyboard mode with an Enter suffix. Click the badge input, scan, and wait for confirmation.
6. Repeat arrival scans keep someone IN. Sign out of the station, use the departure key, and scan the same card OUT.

Without a scanner, paste a card's token into the station input and press Enter. A phone camera alone does not send scans to this app.

On one computer, use 127.0.0.1 for the office and localhost for the station so their login cookies stay separate. Two station tabs on the same hostname share a login; use separate profiles or computers for simultaneous stations.

Press Ctrl+C in the server terminal to stop. Restarting preserves scans and badges. Create another demo to start fresh; existing demos and school data are preserved.
""")
    return run_dir


def demo_app(root, run_dir):
    data = data_directory(root)
    run_dir = run_dir.resolve()
    if run_dir.parent != data or not run_dir.name.startswith("scanner-demo-"):
        raise ValueError("Choose a generated scanner-demo directory inside this checkout's data directory.")
    settings = dict(line.split("=", 1) for line in (run_dir / "demo.env").read_text().splitlines() if line)
    if settings.get("DATABASE_URL") != f"sqlite:///{run_dir / 'demo.db'}":
        raise ValueError("Demo configuration must use its own local database.")
    keys = [settings.get(key, "") for key in ("ADMIN_KEY", "STATION_1_KEY", "STATION_2_KEY")]
    if any(len(key) < 32 for key in keys) or len(set(keys)) != 3:
        raise ValueError("Demo access keys must be distinct and at least 32 characters.")
    app = create_app(settings["DATABASE_URL"], keys[0], {"front-1": keys[1], "front-2": keys[2]},
                     allowed_hosts=["127.0.0.1", "localhost"])
    with Session(app.state.engine) as session:
        staff = list(session.scalars(select(Teacher)))
        if len(staff) != len(NAMES) or any(not person.teacher_id.startswith("DEMO-") for person in staff):
            app.state.engine.dispose()
            raise ValueError("Demo server requires the generated fictional roster.")
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Make a fresh demo and printable scan cards.")
    create.add_argument("--port", type=int, default=8317)
    serve = commands.add_parser("serve", help="Resume an existing demo on loopback.")
    serve.add_argument("directory", type=Path)
    serve.add_argument("--port", type=int, default=8317)
    args = parser.parse_args()
    root = Path.cwd()
    if not (root / "app/main.py").is_file() or not (root / "pyproject.toml").is_file():
        parser.error("Run from the GLHS codebase root.")
    try:
        if args.command == "create":
            directory = create_demo(root, args.port)
            print(f"Created 8 fictional staff, all Not recorded, in {directory}")
            print("Open START-HERE.md for local logins, printable badges, and start.command.")
        else:
            if not 1 <= args.port <= 65535:
                raise ValueError("Choose a port between 1 and 65535.")
            import uvicorn
            uvicorn.run(demo_app(root, args.directory), host="127.0.0.1", port=args.port)
    except (ValueError, OSError):
        parser.exit(1, "Demo setup failed. Check the checkout, demo directory, and local file permissions.\n")


if __name__ == "__main__":
    main()
