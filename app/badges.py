"""Badge tokens and printable badge cards.

The server stores only a token's SHA-256 hash. A new code is returned once, together with the
QR and Code 128 patterns the office screen draws, and is never kept on the server afterwards.
"""
import hashlib
import secrets
import time
from typing import Annotated

import qrcode
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Teacher

MAX_BATCH = 200
START_B, STOP = 104, 106
# Code 128 bar/space module widths for symbol values 0-106; the stop pattern ends with its final bar.
CODE128_WIDTHS = (
    '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
    '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
    '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
    '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
    '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
    '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
    '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
    '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
    '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
    '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
    '114131', '311141', '411131', '211412', '211214', '211232', '2331112',
)


def badge_hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def new_badge(teacher, now=None):
    """Give a teacher a new badge, revoking the previous one, and return the code once."""
    code = secrets.token_urlsafe(24)
    teacher.badge_hash = badge_hash(code)
    teacher.badge_issued_at = now or int(time.time())
    return code


def code128_modules(value):
    """Code 128 subset B as bar (1) and space (0) modules, without quiet zones."""
    if not value or any(not 32 <= ord(character) <= 126 for character in value):
        raise ValueError("Code 128 subset B encodes printable ASCII only.")
    symbols = [ord(character) - 32 for character in value]
    checksum = (START_B + sum(position * symbol for position, symbol in enumerate(symbols, 1))) % 103
    symbols = [START_B, *symbols, checksum, STOP]
    return ''.join(('1' if index % 2 == 0 else '0') * int(width)
                   for symbol in symbols for index, width in enumerate(CODE128_WIDTHS[symbol]))


def qr_rows(value):
    """QR modules (medium error correction, 4-module quiet zone) as rows of 1 and 0."""
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    code.add_data(value)
    code.make(fit=True)
    return [''.join('1' if dark else '0' for dark in row) for row in code.get_matrix()]


def badge_card(code):
    return {"qr": qr_rows(code), "code128": code128_modules(code)}


class BatchInput(BaseModel):
    # IDs beyond a 32-bit SQL integer are invalid input rather than a database error.
    teacher_pks: list[Annotated[int, Field(ge=1, le=2**31 - 1)]] = Field(min_length=1, max_length=MAX_BATCH)
    replace_existing: bool = False

    @field_validator("teacher_pks")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Each staff member can appear once.")
        return value


def names(people, limit=3):
    shown = ", ".join(person.name for person in people[:limit])
    return shown + (f" and {len(people) - limit} more" if len(people) > limit else "")


def register_badges(app, sqlite, db, auth_admin):
    @app.post("/api/badges/batch", dependencies=[Depends(auth_admin)])
    def issue_batch(payload: BatchInput, session: Session = Depends(db)):
        # One transaction: either every selected person gets a new badge or nobody does.
        if sqlite:
            session.execute(text("BEGIN IMMEDIATE"))
        found = {person.id: person for person in session.scalars(
            select(Teacher).where(Teacher.id.in_(payload.teacher_pks)).order_by(Teacher.id).with_for_update())}
        if any(pk not in found or not found[pk].active for pk in payload.teacher_pks):
            raise HTTPException(409, "Some selected staff are no longer active. Refresh the list; no badges were issued.")
        people = sorted(found.values(), key=lambda person: (person.name.lower(), person.id))
        existing = [person for person in people if person.badge_issued_at is not None]
        if existing and not payload.replace_existing:
            raise HTTPException(409, f"{names(existing)} already {'has' if len(existing) == 1 else 'have'} a badge. "
                                     "Review the replacement; no badges were issued.")
        now = int(time.time())
        issued = []
        for person in people:
            code = new_badge(person, now)
            issued.append({"id": person.id, "name": person.name, "teacher_id": person.teacher_id,
                           "badge_code": code, **badge_card(code)})
        session.commit()
        return {"issued": issued, "replaced": len(existing), "issued_at": now}
