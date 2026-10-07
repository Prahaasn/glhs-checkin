# Open this project in Claude

This folder contains the full GLHS platform, including the fresh-demo and
teacher-absence work. Open the folder as a local Code project in Claude Desktop,
or double-click **Open in Claude.command**. The launcher starts Claude Code
Desktop in this folder using the installed Claude CLI and its normal settings.
Terminal alternative: open a terminal in this folder and run claude.
See the [official Claude Code quickstart](https://code.claude.com/docs/en/quickstart).

Paste this as your first message:

> Read CLAUDE.md, docs/CLAUDE-HANDOFF.md, and docs/PLATFORM-UX-PLAN.md. Verify the
> current branch and PR states. Explain the platform and the remaining daily
> workflow work, then help me review what is already built. Keep the drafts and
> human merge boundary intact, and use fictional data for local verification.

## Run a fresh local rehearsal

~~~sh
uv sync --extra dev --extra demo --locked
uv run --extra demo python -m app.local_demo create --port 8332
~~~

The command prints the new data/scanner-demo-… directory. Open its START-HERE.md
for local login locations, printable badges, and its start.command. Start that
launcher to serve this folder's code. Restart it to keep the same badges/history;
run create again when you want a separate empty rehearsal.

Use 127.0.0.1:8332 for the office and localhost:8332 for the scanner to separate
their cookies on one computer. Both connect to the same demo server/database.
Other servers on this Mac may use 8317, 8330, or 8331; use an available port.
Different ports on the same hostname still share browser cookies.

All generated credentials and data stay in ignored data/. Each rehearsal starts
with eight fictional staff, no scans, and no planned absences. Badges from a
different rehearsal do not work here. No school environment or roster is copied.
