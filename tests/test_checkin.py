import os
from sqlalchemy import text
from sqlalchemy.engine import make_url

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Base, OfficeUser, ScanEvent, Teacher
from app.security import hash_password

ADMIN = {"X-Admin-Key": "test-admin"}
ONE = {"X-Station-Key": "test-one"}
TWO = {"X-Station-Key": "test-two"}


@pytest.fixture(params=["sqlite", "postgres"] if os.getenv("TEST_DATABASE_URL") else ["sqlite"])
def client(tmp_path, request):
    url = f"sqlite:///{tmp_path / 'test.db'}" if request.param == "sqlite" else os.environ["TEST_DATABASE_URL"]
    if request.param == "postgres":
        parsed = make_url(url)
        assert parsed.database.endswith("_test") and parsed.host in ("127.0.0.1", "localhost"), "Refusing to reset a non-local test database"
    app = create_app(url, "test-admin", {"front-1": "test-one", "front-2": "test-two"})
    if request.param == "postgres":
        with app.state.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS school_checkin"))
            Base.metadata.drop_all(connection)
            Base.metadata.create_all(connection)
    with TestClient(app) as c:
        yield c


def teacher(client, name="Alex Morgan", teacher_id="001"):
    r = client.post('/api/teachers', headers=ADMIN, json={"name": name, "teacher_id": teacher_id})
    assert r.status_code == 201
    return r.json()


def scan(client, code, direction="in", headers=ONE, request_id=None):
    return client.post('/api/scans', headers=headers, json={"code": code, "direction": direction, "request_id": request_id or str(uuid4())})


def test_two_stations_share_presence_and_history(client):
    t = teacher(client)
    assert scan(client,t['badge_code']).json()['inside']
    assert client.get('/api/teachers',headers=ADMIN).json()[0]['inside']
    assert scan(client,t['badge_code'],'out',TWO).json()['changed']
    assert not client.get('/api/teachers',headers=ADMIN).json()[0]['inside']
    events=client.get('/api/events',headers=ADMIN).json()
    assert [e['station'] for e in events]==['front-2','front-1']


def test_repeat_scans_do_not_toggle(client):
    t=teacher(client)
    assert scan(client,t['badge_code']).json()['changed']
    repeated=scan(client,t['badge_code'],headers=TWO).json()
    assert not repeated['changed'] and repeated['inside']
    assert len(client.get('/api/events',headers=ADMIN).json())==2


def test_lost_response_retry_is_idempotent_even_after_checkout(client):
    t=teacher(client); request_id=str(uuid4())
    first=scan(client,t['badge_code'],request_id=request_id).json()
    scan(client,t['badge_code'],'out',TWO)
    assert scan(client,t['badge_code'],request_id=request_id).json()==first
    assert not client.get('/api/teachers',headers=ADMIN).json()[0]['inside']
    assert len(client.get('/api/events',headers=ADMIN).json())==2


def test_request_id_reuse_for_other_payload_is_rejected(client):
    t=teacher(client); request_id=str(uuid4())
    scan(client,t['badge_code'],request_id=request_id)
    assert scan(client,t['badge_code'],'out',request_id=request_id).status_code==409
    other=teacher(client,teacher_id='002')
    assert scan(client,other['badge_code'],request_id=request_id).status_code==409


def test_unknown_badges_do_not_change_roster(client):
    teacher(client)
    assert scan(client,'unknown').status_code==404
    assert client.get('/api/events',headers=ADMIN).json()==[]


def test_auth_boundaries(client):
    t=teacher(client)
    for endpoint in ['/api/teachers','/api/events','/api/export','/api/presence?at=0']:
        assert client.get(endpoint).status_code==401
        assert client.get(endpoint,headers=ONE).status_code==401
    assert scan(client,t['badge_code'],headers=ADMIN).status_code==401
    assert client.post('/api/teachers',headers=ONE,json={'name':'X','teacher_id':'2'}).status_code==401
    assert client.get('/api/station',headers=TWO).json()=={'station':'front-2'}


def test_badge_rotation_revokes_old_code(client):
    t=teacher(client)
    new=client.post(f"/api/teachers/{t['id']}/badge",headers=ADMIN).json()
    assert scan(client,t['badge_code']).status_code==404
    assert scan(client,new['badge_code']).status_code==200


def test_deactivation_requires_checkout_and_disables_scans(client):
    t=teacher(client); scan(client,t['badge_code'])
    assert client.patch(f"/api/teachers/{t['id']}",headers=ADMIN).status_code==409
    scan(client,t['badge_code'],'out')
    assert client.patch(f"/api/teachers/{t['id']}",headers=ADMIN).status_code==200
    assert scan(client,t['badge_code']).status_code==404


def test_office_correction_is_audited(client):
    t=teacher(client)
    result=client.post(f"/api/teachers/{t['id']}/correction",headers=ADMIN,json={'direction':'in','reason':'Missed arrival scan','request_id':str(uuid4())})
    assert result.json()['inside']
    entry=client.get('/api/events',headers=ADMIN).json()[0]
    assert entry['station']=='office' and entry['reason']=='Missed arrival scan'


def test_past_snapshot_uses_event_history_not_current_state(client):
    t=teacher(client); scan(client,t['badge_code']); scan(client,t['badge_code'],'out')
    with Session(client.app.state.engine) as s:
        person=s.get(Teacher,t['id']); person.created_at=50
        entries=list(s.scalars(select(ScanEvent).order_by(ScanEvent.id)))
        entries[0].occurred_at=100;entries[1].occurred_at=200;s.commit()
    assert client.get('/api/presence?at=40',headers=ADMIN).json()==[]
    assert not client.get('/api/presence?at=80',headers=ADMIN).json()[0]['inside']
    assert client.get('/api/presence?at=150',headers=ADMIN).json()[0]['inside']
    assert not client.get('/api/presence?at=250',headers=ADMIN).json()[0]['inside']


def test_concurrent_stations_only_one_arrival_changes_state(client):
    t=teacher(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda h:scan(client,t['badge_code'],headers=h),[ONE,TWO]))
    assert all(r.status_code==200 for r in results)
    assert sum(r.json()['changed'] for r in results)==1
    assert client.get('/api/teachers',headers=ADMIN).json()[0]['inside']


def test_concurrent_retries_create_one_event(client):
    t=teacher(client); request_id=str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:scan(client,t['badge_code'],request_id=request_id),range(2)))
    assert results[0].json()==results[1].json()
    assert len(client.get('/api/events',headers=ADMIN).json())==1


def test_export_escapes_spreadsheet_formulas_and_uses_utc(client):
    t=teacher(client,name='=DANGEROUS()',teacher_id='@001');scan(client,t['badge_code'])
    result=client.get('/api/export',headers=ADMIN)
    assert "'=DANGEROUS()" in result.text and "'@001" in result.text
    assert '+00:00' in result.text and 'badge_code' not in result.text
    assert client.get('/api/export?until=0',headers=ADMIN).text.count('\n')==1


def test_validation_duplicate_ids_and_qr(client):
    t=teacher(client)
    assert client.post('/api/teachers',headers=ADMIN,json={'name':'Other','teacher_id':'001'}).status_code==409
    assert client.post('/api/teachers',headers=ADMIN,json={'name':'   ','teacher_id':'002'}).status_code==422
    r=client.post('/api/badge-image',headers=ADMIN,json={'code':t['badge_code'],'direction':'in','request_id':str(uuid4())})
    assert r.content.startswith(b'\x89PNG')
    assert 'badge_hash' not in str(client.get('/api/teachers',headers=ADMIN).json())


def test_security_headers_and_health(client):
    r=client.get('/')
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']
    assert client.get('/api/health').json()=={'status':'ok'}


def test_keys_must_be_separate():
    with pytest.raises(RuntimeError):
        create_app('sqlite://','same',{'front-1':'same'})


def test_no_scan_means_unrecorded_not_outside(client):
    t=teacher(client)
    assert t['presence']=='unrecorded' and t['inside'] is None
    result=scan(client,t['badge_code'],'out').json()
    assert result['changed'] and not result['inside']
    view=client.get('/api/teachers',headers=ADMIN).json()[0]
    assert view['presence']=='out' and view['last_seen'] is not None


def test_cookie_session_auth_and_logout(client):
    response=client.post('/api/session',json={'role':'admin','access_key':'test-admin'})
    assert response.status_code==200
    cookie=response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/api' in cookie
    assert response.json()['role']=='admin' and 'access_key' not in response.text
    assert client.get('/api/teachers').status_code==200
    assert client.delete('/api/session').status_code==200
    assert client.get('/api/teachers').status_code==401


def test_named_office_login_can_read_presence_and_lock(client):
    person=teacher(client)
    with Session(client.app.state.engine) as session:
        session.add(OfficeUser(username='frontdesk',display_name='Front Desk',password_hash=hash_password('correct horse battery staple')))
        session.commit()
    response=client.post('/api/office-session',json={'username':'FRONTDESK','password':'correct horse battery staple'})
    assert response.status_code==200
    assert response.json()['display_name']=='Front Desk'
    assert 'password' not in response.text
    assert client.get('/api/teachers').status_code==200
    assert client.get('/api/station').status_code==401
    correction=client.post(f"/api/teachers/{person['id']}/correction",json={'direction':'in','reason':'Missed arrival scan','request_id':str(uuid4())})
    assert correction.status_code==200
    assert client.get('/api/events').json()[0]['station']=='Office · Front Desk'
    assert client.delete('/api/session').status_code==200
    assert client.get('/api/teachers').status_code==401


def test_named_login_rejects_bad_password_and_inactive_account(client):
    with Session(client.app.state.engine) as session:
        session.add(OfficeUser(username='office',display_name='Office',password_hash=hash_password('long private password')))
        session.commit()
    assert client.post('/api/office-session',json={'username':'office','password':'wrong'}).status_code==401
    assert client.post('/api/office-session',json={'username':'unknown','password':'wrong'}).status_code==401
    assert client.post('/api/office-session',json={'username':'office','password':'long private password'}).status_code==200
    with Session(client.app.state.engine) as session:
        user=session.scalar(select(OfficeUser).where(OfficeUser.username=='office'))
        user.active=False
        session.commit()
    assert client.get('/api/teachers').status_code==401


def test_password_reset_revokes_existing_office_session(tmp_path, monkeypatch):
    from app.setup import main as setup_main
    url=f"sqlite:///{tmp_path / 'accounts.db'}"
    monkeypatch.setenv('DATABASE_URL',url)
    monkeypatch.setenv('ADMIN_KEY','a'*40)
    monkeypatch.setenv('STATION_1_KEY','b'*40)
    monkeypatch.setenv('STATION_2_KEY','c'*40)
    monkeypatch.setenv('ALLOWED_HOSTS','testserver')
    app=create_app()
    with TestClient(app) as browser:
        monkeypatch.setattr('sys.argv',['setup','add-user','--username','office','--name','Office'])
        passwords=iter(['original long password','original long password'])
        monkeypatch.setattr('app.setup.getpass.getpass',lambda _:next(passwords))
        setup_main()
        assert browser.post('/api/office-session',json={'username':'office','password':'original long password'}).status_code==200
        monkeypatch.setattr('sys.argv',['setup','reset-password','--username','office'])
        passwords=iter(['replacement long password','replacement long password'])
        monkeypatch.setattr('app.setup.getpass.getpass',lambda _:next(passwords))
        setup_main()
        assert browser.get('/api/teachers').status_code==401
        assert browser.post('/api/office-session',json={'username':'office','password':'original long password'}).status_code==401
        assert browser.post('/api/office-session',json={'username':'office','password':'replacement long password'}).status_code==200
        monkeypatch.setattr('sys.argv',['setup','disable-user','--username','office'])
        setup_main()
        assert browser.get('/api/teachers').status_code==401
        assert browser.post('/api/office-session',json={'username':'office','password':'replacement long password'}).status_code==401


def test_station_cookie_cannot_read_office_routes(client):
    assert client.post('/api/session',json={'role':'station','access_key':'test-one'}).status_code==200
    assert client.get('/api/station').json()['station']=='front-1'
    assert client.get('/api/teachers').status_code==401
    assert client.get('/api/export').status_code==401
    assert client.post('/api/session',json={'role':'admin','access_key':'test-one'}).status_code==401


def test_expired_session_is_rejected(client):
    from app.models import AccessSession
    client.post('/api/session',json={'role':'admin','access_key':'test-admin'})
    with Session(client.app.state.engine) as session:
        stored=session.scalar(select(AccessSession));stored.expires_at=0;session.commit()
    assert client.get('/api/session').status_code==401
    assert client.get('/api/teachers').status_code==401


def test_https_session_cookie_is_secure(client):
    client.base_url='https://testserver'
    response=client.post('/api/session',json={'role':'admin','access_key':'test-admin'})
    assert 'Secure' in response.headers['set-cookie']
    assert response.headers['strict-transport-security']=='max-age=31536000'


def test_failed_logins_are_throttled(client):
    for _ in range(20):
        assert client.post('/api/session',json={'role':'admin','access_key':'wrong'}).status_code==401
    result=client.post('/api/session',json={'role':'admin','access_key':'wrong'})
    assert result.status_code==429 and result.headers['retry-after']=='60'


def test_unknown_badge_guessing_is_throttled_per_station(client):
    for _ in range(30):
        assert scan(client,'unknown').status_code==404
    assert scan(client,'unknown').status_code==429
    assert scan(client,'unknown',headers=TWO).status_code==404
    assert client.get('/api/teachers',headers=ADMIN).status_code==200


def test_untrusted_host_and_cross_origin_writes_are_rejected(client):
    assert client.get('/api/teachers',headers={**ADMIN,'Host':'evil.example'}).status_code==400
    assert client.post('/api/teachers',headers={**ADMIN,'Origin':'https://evil.example'},json={'name':'X','teacher_id':'X'}).status_code==403
    assert client.get('/api/teachers',headers=ADMIN).json()==[]


def test_oversized_and_chunked_requests_rejected_before_parsing(client):
    assert client.post('/api/scans',headers=ONE,content='x'*9000).status_code==413
    assert client.post('/api/scans',headers=ONE,content=iter([b'x'*5000,b'x'*5000])).status_code==413
    assert client.get('/api/events',headers=ADMIN).json()==[]


def test_blank_correction_reason_is_rejected(client):
    t=teacher(client)
    result=client.post(f"/api/teachers/{t['id']}/correction",headers=ADMIN,json={'direction':'in','request_id':str(uuid4()),'reason':'   '})
    assert result.status_code==422


def test_directory_import_is_idempotent_and_does_not_create_presence(client):
    from app.roster import SOURCE_URL, import_directory
    manifest={'source_url':SOURCE_URL,'expected_total':2,'staff':[{'directory_id':'101','name':'Example One'},{'directory_id':'102','name':'Example Two'}]}
    engine=client.app.state.engine
    assert import_directory(engine,manifest,dry_run=True)['added']==2
    assert client.get('/api/teachers',headers=ADMIN).json()==[]
    assert import_directory(engine,manifest)['added']==2
    assert import_directory(engine,manifest)=={'added':0,'skipped':2,'dry_run':False}
    staff=client.get('/api/teachers',headers=ADMIN).json()
    assert len(staff)==2 and all(t['presence']=='unrecorded' for t in staff)
    assert client.get('/api/events',headers=ADMIN).json()==[]
    manifest['staff'][1]['name']='Unexpected Rename'
    with pytest.raises(ValueError):
        import_directory(engine,manifest)
    assert client.get('/api/teachers',headers=ADMIN).json()[1]['name']=='Example Two'


def test_validation_never_echoes_badge_or_access_key(client):
    sentinel='sensitive-value-'*25
    result=client.post('/api/session',json={'role':'admin','access_key':sentinel})
    assert result.status_code==422 and sentinel not in result.text
    result=client.post('/api/scans',headers=ONE,json={'code':sentinel,'direction':'in','request_id':str(uuid4())})
    assert result.status_code==422 and sentinel not in result.text


def test_database_errors_return_generic_retryable_response(client,monkeypatch):
    from sqlalchemy.exc import OperationalError
    def unavailable(*args,**kwargs):
        raise OperationalError('private database statement',{},Exception('private connection detail'))
    monkeypatch.setattr(client.app.state.engine,'connect',unavailable)
    result=client.get('/api/health')
    assert result.status_code==503
    assert 'private' not in result.text and 'Retry the same scan' in result.text


def test_cookie_sessions_survive_server_restart(client):
    client.post('/api/session',json={'role':'admin','access_key':'test-admin'})
    restarted=create_app(str(client.app.state.engine.url),'test-admin',{'front-1':'test-one','front-2':'test-two'})
    with TestClient(restarted) as second:
        second.cookies.update(client.cookies)
        assert second.get('/api/teachers').status_code==200
        second.delete('/api/session')
    assert client.get('/api/teachers').status_code==401


def test_weak_environment_keys_refused(monkeypatch):
    monkeypatch.setenv('ADMIN_KEY','weak-admin');monkeypatch.setenv('STATION_1_KEY','weak-one');monkeypatch.setenv('STATION_2_KEY','weak-two')
    with pytest.raises(RuntimeError,match='at least 32'):
        create_app()
