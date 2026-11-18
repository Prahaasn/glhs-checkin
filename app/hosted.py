"""Vercel entrypoint; credentials exist only in server environment variables."""
import os
import ssl
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url

from app.main import create_app


def hosted_app():
    raw_url = os.getenv("DATABASE_URL", "")
    if not raw_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Hosting requires certificate-verified PostgreSQL.")
    url = make_url(raw_url)
    certificate = os.getenv("SUPABASE_CA_CERT", "")
    if url.query.get("sslmode") != "verify-full" or not certificate:
        raise RuntimeError("Hosting requires certificate-verified PostgreSQL.")
    # Validate before writing. /tmp is writable in the hosted Python runtime.
    ssl.create_default_context(cadata=certificate)
    with tempfile.NamedTemporaryFile(mode="w", prefix="glhs-ca-", suffix=".crt", delete=False) as file:
        file.write(certificate)
        certificate_path = Path(file.name)
    url = url.update_query_dict({"sslrootcert": str(certificate_path)})
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    # Use the normal production factory path so key-length checks still apply.
    hosts = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
    if not hosts or "*" in hosts:
        raise RuntimeError("Set exact ALLOWED_HOSTS for the hosted app.")
    # The generated deployment URL permits checks before assigning the live domain.
    deployment_host = os.environ.get("VERCEL_URL")
    if deployment_host:
        hosts.append(deployment_host)
    return create_app(allowed_hosts=hosts)


app = hosted_app()
