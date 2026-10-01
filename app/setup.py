"""Local configuration, demo data, and explicit hosted-schema initialization."""
import argparse
import json
import getpass
import secrets
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.main import TeacherInput, badge_hash, create_app
from app.models import AccessSession, Base, OfficeSession, OfficeUser, ScanEvent, Teacher
from app.security import hash_password
from uuid import uuid4
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['keys', 'demo', 'init-postgres', 'add-user', 'disable-user', 'reset-password'])
    parser.add_argument('--username')
    parser.add_argument('--name')
    args = parser.parse_args()
    if args.command == 'keys':
        path = Path('.env')
        if path.exists():
            raise SystemExit('.env exists; refusing to overwrite your keys.')
        path.write_text('\n'.join(f'{name}={secrets.token_urlsafe(32)}' for name in ['ADMIN_KEY','STATION_1_KEY','STATION_2_KEY'])+'\n')
        path.chmod(0o600)
        print('Created .env with three separate access keys. Open it locally to connect each station.')
        return
    app = create_app()
    engine = app.state.engine
    if args.command == 'init-postgres':
        if engine.dialect.name != 'postgresql':
            raise SystemExit('Set DATABASE_URL to a PostgreSQL connection before provisioning.')
        with engine.begin() as conn:
            conn.execute(text('CREATE SCHEMA IF NOT EXISTS school_checkin'))
            conn.execute(text('SET search_path TO school_checkin'))
            Base.metadata.create_all(conn)
            conn.execute(text('REVOKE ALL ON SCHEMA school_checkin FROM PUBLIC, anon, authenticated'))
            conn.execute(text('REVOKE ALL ON ALL TABLES IN SCHEMA school_checkin FROM PUBLIC, anon, authenticated'))
        print('Initialized private school_checkin schema. Future schema changes require migrations.')
        return
    if args.command in ('add-user', 'disable-user', 'reset-password'):
        username = (args.username or input('Username: ')).strip().lower()
        if not username or len(username) > 40 or not all(c.isascii() and (c.isalnum() or c in '._-') for c in username):
            raise SystemExit('Use a username of 1–40 letters, numbers, dots, underscores, or hyphens.')
        name = (args.name or input('Display name: ')).strip() if args.command == 'add-user' else None
        if args.command == 'add-user' and (not name or len(name) > 80):
            raise SystemExit('Display name must be 1–80 characters.')
        if args.command != 'disable-user':
            password = getpass.getpass('Password (12+ characters): ')
            if password != getpass.getpass('Confirm password: '):
                raise SystemExit('Passwords did not match.')
            try:
                password_hash = hash_password(password)
            except ValueError as error:
                raise SystemExit(str(error)) from error
        if engine.dialect.name == 'sqlite':
            Base.metadata.create_all(engine)
        with Session(engine) as session:
            user = session.query(OfficeUser).filter_by(username=username).first()
            if args.command == 'add-user':
                if user:
                    raise SystemExit('Username already exists. No account was changed.')
                session.add(OfficeUser(username=username, display_name=name, password_hash=password_hash))
            else:
                if not user:
                    raise SystemExit('Office account not found.')
                if args.command == 'disable-user':
                    user.active = False
                else:
                    user.password_hash = password_hash
                tokens = session.query(OfficeSession.token_hash).filter_by(user_id=user.id)
                session.query(AccessSession).filter(AccessSession.token_hash.in_(tokens)).delete(synchronize_session=False)
                session.query(OfficeSession).filter_by(user_id=user.id).delete()
            session.commit()
        print({'add-user': 'Created', 'disable-user': 'Disabled', 'reset-password': 'Updated'}[args.command] + f' office login for {username}.')
        return
    if engine.dialect.name != 'sqlite':
        raise SystemExit('Demo seeding is restricted to local SQLite.')
    Base.metadata.create_all(engine)
    codes=[]
    with Session(engine) as session:
        if session.query(Teacher).filter(~Teacher.teacher_id.like('DEMO-%')).first():
            raise SystemExit('Demo data cannot be mixed into a real roster.')
        for i,name in enumerate(['Alex Morgan','Jordan Rivera','Taylor Chen','Sam Patel','Casey Brooks','Riley Thompson','Jamie Wilson','Avery Garcia'],1):
            validated=TeacherInput(teacher_id=f'DEMO-{i:03}',name=name)
            if session.query(Teacher).filter_by(teacher_id=validated.teacher_id).first():
                continue
            code=secrets.token_urlsafe(24)
            teacher = Teacher(teacher_id=validated.teacher_id,name=name,badge_hash=badge_hash(code))
            session.add(teacher)
            session.flush()
            # A sample school day makes each recorded state visible without implying
            # that a newly imported staff member has checked in or out.
            if i <= 4 or i in (5, 6):
                direction = 'in' if i <= 4 else 'out'
                now = int(time.time()) - (9-i)*360
                teacher.inside = direction == 'in'
                teacher.last_seen = now
                session.add(ScanEvent(teacher_pk=teacher.id, request_id=str(uuid4()), direction=direction,
                                      station='demo', occurred_at=now, changed=True))
            codes.append({'name':name,'code':code})
        session.commit()
    Path('data').mkdir(exist_ok=True)
    demo_path=Path('data/demo-badges.json')
    if codes:
        demo_path.write_text(json.dumps(codes,indent=2)); demo_path.chmod(0o600)
    print(f'Created {len(codes)} fictional teachers. Local test badge codes are in data/demo-badges.json.')


if __name__ == '__main__':
    main()
