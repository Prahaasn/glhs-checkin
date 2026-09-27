"""Local configuration, demo data, and explicit hosted-schema initialization."""
import argparse
import json
import secrets
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.main import TeacherInput, badge_hash, create_app
from app.models import Base, Teacher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['keys', 'demo', 'init-postgres'])
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
    if engine.dialect.name != 'sqlite':
        raise SystemExit('Demo seeding is restricted to local SQLite.')
    Base.metadata.create_all(engine)
    codes=[]
    with Session(engine) as session:
        for i,name in enumerate(['Alex Morgan','Jordan Rivera','Taylor Chen','Sam Patel','Casey Brooks','Riley Thompson','Jamie Wilson','Avery Garcia'],1):
            validated=TeacherInput(teacher_id=f'DEMO-{i:03}',name=name)
            if session.query(Teacher).filter_by(teacher_id=validated.teacher_id).first():
                continue
            code=secrets.token_urlsafe(24)
            session.add(Teacher(teacher_id=validated.teacher_id,name=name,badge_hash=badge_hash(code)))
            codes.append({'name':name,'code':code})
        session.commit()
    Path('data').mkdir(exist_ok=True)
    demo_path=Path('data/demo-badges.json')
    if codes:
        demo_path.write_text(json.dumps(codes,indent=2)); demo_path.chmod(0o600)
    print(f'Created {len(codes)} fictional teachers. Local test badge codes are in data/demo-badges.json.')


if __name__ == '__main__':
    main()
