"""Office setup checklist: a read-only view of whether the front office is ready to scan.

Each step reports what the server can observe (accounts, roster, badges on record, station
sign-ins, today's scans, and how browsers reach it) and the next action. It never shows keys or
passwords; logins and station keys stay with the administrator on the server.
"""
import time

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.absences import school_today
from app.attention import day_start, moment, plural
from app.models import AccessSession, OfficeUser, ScanEvent, Teacher

LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}
STATION_LABELS = {"front-1": "Arrival station", "front-2": "Departure station"}


def step(key, status, title, detail, actions=(), lines=(), help=()):
    return {"key": key, "status": status, "title": title, "detail": detail,
            "actions": list(actions), "lines": list(lines), "help": list(help)}


def tip(text, command=None):
    return {"text": text, "command": command}


def register_readiness(app, db, auth_admin, stations, allowed_hosts):
    lan = any(host not in LOOPBACK for host in allowed_hosts)

    @app.get("/api/setup", dependencies=[Depends(auth_admin)])
    def readiness(request: Request, session: Session = Depends(db)):
        now = int(time.time())
        start = day_start(school_today())
        count = lambda query: session.scalar(select(func.count()).select_from(query.subquery()))
        active = count(select(Teacher.id).where(Teacher.active == True))
        inactive = count(select(Teacher.id).where(Teacher.active == False))
        missing = list(session.scalars(select(Teacher.id).where(
            Teacher.active == True, Teacher.badge_issued_at.is_(None)).order_by(Teacher.name)))
        demo = active > 0 and count(select(Teacher.id).where(
            Teacher.active == True, ~Teacher.teacher_id.startswith("DEMO-"))) == 0
        office_users = count(select(OfficeUser.id).where(OfficeUser.active == True))
        station_rows = []
        for name in stations:
            expires = session.scalar(select(func.max(AccessSession.expires_at)).where(
                AccessSession.role == "station", AccessSession.station == name, AccessSession.expires_at > now))
            last_scan = session.scalar(select(func.max(ScanEvent.occurred_at)).where(ScanEvent.station == name))
            station_rows.append({"station": name, "label": STATION_LABELS.get(name, name),
                                 "signed_in_until": expires, "last_scan_at": last_scan,
                                 "scanned_today": last_scan is not None and last_scan >= start})
        https = request.url.scheme == "https"
        steps = []

        logins = tip("Run on the server computer, in the checkout folder. Passwords are typed privately there.",
                     "uv run --env-file .env python -m app.setup add-user --username NAME --name \"Display Name\"")
        leavers = tip("When someone leaves the office team, disable their login (reset-password changes one instead):",
                      "uv run --env-file .env python -m app.setup disable-user --username NAME")
        if office_users == 0:
            steps.append(step("office", "todo", "Office logins", "No named office login is active. Create one for each person who runs the desk.",
                              help=[logins, leavers]))
        else:
            detail = plural(office_users, "active office login") + "." + (
                " Add a second so someone else can cover the desk." if office_users == 1 else "")
            steps.append(step("office", "done", "Office logins", detail, help=[logins, leavers]))

        roster_help = [tip("Add one person at a time on Staff & badges."),
                       tip("Or load the school's public directory on the server. Download it first:",
                           "uv run python -m app.roster fetch-directory"),
                       tip("Preview the import, then run it again without --dry-run. It adds names only: no scans and no usable badges.",
                           "uv run --env-file .env python -m app.roster import-directory --dry-run")]
        add_staff = {"type": "page", "page": "teachers", "label": "Add staff"}
        if active == 0:
            steps.append(step("roster", "todo", "Staff roster", "No active staff yet.", [add_staff], help=roster_help))
        else:
            detail = plural(active, "active staff member") + (f" · {inactive} inactive" if inactive else "") + "."
            if demo:
                detail += " This is a fictional demo roster."
            steps.append(step("roster", "done", "Staff roster", detail,
                              [{"type": "page", "page": "teachers", "label": "Open Staff & badges"}], help=roster_help))

        badge_help = [tip("Print at Actual size / 100% on letter paper, then cut along each card's border."),
                      tip("Each card carries a Code 128 barcode and a QR code with the same private code, so a 1D or 2D scanner works."),
                      tip("Codes are shown once and are not saved. If a sheet does not print, issue those badges again; the unprinted codes stop working.")]
        if active == 0:
            steps.append(step("badges", "todo", "Badges", "Add staff before printing badges.", help=badge_help))
        elif missing:
            steps.append(step("badges", "todo", "Badges",
                              f"{len(missing)} of {plural(active, 'active staff member')} {'has' if len(missing) == 1 else 'have'} no badge on record.",
                              [{"type": "print_missing", "label": "Print " + plural(len(missing), "badge")}], help=badge_help))
        else:
            steps.append(step("badges", "done", "Badges", "Every active staff member has a badge on record.",
                              [{"type": "print", "label": "Reprint or replace badges"}], help=badge_help))

        def station_line(row):
            signed = (f"signed in until {moment(row['signed_in_until'])}" if row["signed_in_until"] else "not signed in")
            scan = f"last scan {moment(row['last_scan_at'])}" if row["last_scan_at"] else "no scans yet"
            return f"{row['label']}: {signed} · {scan}"
        waiting = [row["label"] for row in station_rows if not row["signed_in_until"]]
        station_help = [tip("On each scanner computer, open this server's address in a browser."),
                        tip("Choose Scanner station and enter that computer's key from the server's .env file: "
                            "STATION_1_KEY for arrivals, STATION_2_KEY for departures."),
                        tip("Set the USB scanner to keyboard (HID) mode with an Enter suffix, using its own manual.")]
        if not lan:
            station_help.append(tip("On one computer, open the office at 127.0.0.1 and the station at localhost so their sign-ins stay separate."))
        steps.append(step("stations", "todo" if waiting else "done", "Scanner stations",
                          (" and ".join(waiting) + (" is" if len(waiting) == 1 else " are") + " not signed in.") if waiting
                          else "Both stations are signed in.",
                          lines=[station_line(row) for row in station_rows], help=station_help))

        untested = [row["label"] for row in station_rows if not row["scanned_today"]]
        steps.append(step("test_scan", "todo" if untested else "done", "Scans today",
                          ("No scan recorded today at the " + " or the ".join(label.lower() for label in untested) + ".")
                          if untested else "Both stations recorded a scan today.",
                          [{"type": "page", "page": "dashboard", "label": "Check Overview"}],
                          help=[tip("Click the badge box at the arrival station, scan a badge, and wait for the on-screen confirmation."),
                                tip("Scan the same badge at the departure station."),
                                tip("Both scans should appear under Latest scans. A scanner beep alone does not mean the scan was saved.")]))

        if https:
            steps.append(step("network", "done", "Network and security", "Browsers reach this server over HTTPS."))
        elif lan:
            steps.append(step("network", "warning", "Network and security",
                              "Other computers can connect over plain HTTP, which exposes sign-ins and attendance on the network.",
                              help=[tip("Serve the app through the school's approved HTTPS before using real staff data."),
                                    tip("Keep the database on the server's own disk, not a network share.")]))
        else:
            steps.append(step("network", "info", "Network and security",
                              "Only this computer can connect, which suits a one-computer rehearsal.",
                              help=[tip("For two scanner computers, set ALLOWED_HOSTS to the school-approved hostname or LAN address "
                                        "and serve through school-approved HTTPS. See README.md.")]))

        return {"steps": steps, "remaining": sum(item["status"] in ("todo", "warning") for item in steps),
                "staff": {"active": active, "inactive": inactive, "demo": demo},
                "badges": {"missing": missing, "issued": active - len(missing)},
                "office_users": office_users, "stations": station_rows, "https": https, "lan": lan}
