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
    assert pool._max_overflow == 1  # Office login temporarily uses two sessions.
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
