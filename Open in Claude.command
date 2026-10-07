#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_root"
if command -v claude >/dev/null 2>&1; then
  exec claude --desktop
fi
if [ -x "$HOME/.local/bin/claude" ]; then
  exec "$HOME/.local/bin/claude" --desktop
fi
printf '%s\n' 'Claude Code was not found. Install it from the official Claude Code quickstart, then open this folder again.'
exit 1
