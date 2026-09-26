from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import ScanEvent, Teacher

ADMIN = {"X-Admin-Key": "test-admin"}
ONE = {"X-Station-Key": "test-one"}
TWO = {"X-Station-Key": "test-two"}


@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}", "test-admin", {"front-1": "test-one", "front-2": "test-two"})
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
