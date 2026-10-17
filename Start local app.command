#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo 'Create the private .env configuration first; see docs/SUPABASE.md.'
  exit 1
fi
exec uv run --env-file .env uvicorn app.main:create_app --factory --host 127.0.0.1 --port "${GLHS_PORT:-8317}"
