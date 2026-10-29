"""Serverless deployment must fail closed and keep per-instance pools small."""
import importlib.util
from pathlib import Path

import pytest

from app.main import create_app


def test_vercel_limits_postgres_connections(monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    app = create_app('postgresql+psycopg://user:password@localhost/example_test',
                     'admin', {'one': 'one', 'two': 'two'})
    pool = app.state.engine.pool
    assert pool.size() == 1
    assert pool._max_overflow == 0
    app.state.engine.dispose()


@pytest.mark.parametrize('url', ['', 'sqlite:///local.db',
    'postgresql+psycopg://user:password@localhost/db?sslmode=require'])
def test_hosted_entrypoint_refuses_missing_database_or_unverified_tls(monkeypatch, url):
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('SUPABASE_CA_CERT', 'not a certificate')
    spec = importlib.util.spec_from_file_location('hosted_check', Path('app/hosted.py'))
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(RuntimeError, match='certificate-verified PostgreSQL'):
        spec.loader.exec_module(module)


def test_hosted_entrypoint_rejects_invalid_certificate(monkeypatch):
    import ssl
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:password@localhost/db?sslmode=verify-full')
    monkeypatch.setenv('SUPABASE_CA_CERT', 'not a certificate')
    spec = importlib.util.spec_from_file_location('hosted_invalid_cert', Path('app/hosted.py'))
    with pytest.raises(ssl.SSLError):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))


def test_office_login_succeeds_with_one_available_connection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine as real_create_engine
    from sqlalchemy.orm import Session
    from app.models import OfficeUser
    from app.security import hash_password

    def single_connection_engine(url, **kwargs):
        kwargs.update(pool_size=1, max_overflow=0, pool_timeout=0.1)
        return real_create_engine(url, **kwargs)

    monkeypatch.setattr('app.main.create_engine', single_connection_engine)
    app = create_app(f'sqlite:///{tmp_path / "login.db"}', 'admin', {'one': 'one', 'two': 'two'})
    with TestClient(app) as browser:
        with Session(app.state.engine) as session:
            session.add(OfficeUser(username='office', display_name='Office',
                                   password_hash=hash_password('a local test password')))
            session.commit()
        response = browser.post('/api/office-session', json={
            'username': 'office', 'password': 'a local test password'})
        assert response.status_code == 200
        assert browser.get('/api/session').json()['role'] == 'admin'
