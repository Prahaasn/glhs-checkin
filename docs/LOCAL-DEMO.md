# Repeatable local scanner rehearsal

**Outcome:** anyone with the checkout can start with zero attendance, print eight
fictional badges, and exercise the existing scan workflow.

**Observed:** the earlier rehearsal was created by temporary scripts and private
files. The existing seeded demo shows example attendance instead of a fresh day.

**Constraints:** preserve school records and configuration; keep generated keys,
credentials, tokens, PDFs, and databases inside ignored data/; use the real app.

**Done when:** a new demo has eight Not recorded staff and zero scans, both printed
formats match its badges, arrival/departure scans work, and a restart preserves
history while another creation preserves all previous demos.

Run from the checkout root:

~~~sh
uv run --extra demo python -m app.local_demo create
# Choose another port when 8317 is already in use:
uv run --extra demo python -m app.local_demo create --port 8330
~~~

Each command creates a new private data/scanner-demo-… directory:

| Local file | Purpose |
| --- | --- |
| START-HERE.md | Office/station URLs and scan instructions |
| start.command | Starts the existing Python app on loopback |
| staff-badges.pdf | Two pages: eight Code128 barcodes and eight QR codes |
| office-login.txt | Newly generated demo office credentials |
| demo.env | Demo database location and separate station/API keys |
| badges.json | The issued fictional badge tokens |
| demo.db | This rehearsal's staff, scans, and sessions |

Read credentials locally. Do not upload these files to a PR. The database stores
password and badge hashes; the private files retain the values needed to rehearse.
The server refuses a configuration pointing to another database or a non-demo
roster. Inherited DATABASE_URL, access keys, and host configuration cannot redirect
the demo to school data.

Use 127.0.0.1 for the office and localhost for the scanner on one computer. Cookies
are scoped to hostnames, not ports; two station tabs on the same hostname share a
login. Use separate profiles or computers for simultaneous arrival/departure.

Print at Actual size / 100%. Set the physical scanner to USB keyboard mode with
Enter after each scan. Test arrivals, departures, repeats, an unknown badge, an
outage/retry, and a missed-scan correction. A phone camera alone cannot submit a
scan. Tokens can be pasted into the masked input for keyboard-only rehearsal.

Stop with Ctrl+C and rerun start.command to resume. Create another demo to start
fresh; no existing history is erased. The launcher uses the checkout's current
code. Physical scanner/printing verification and school deployment remain
separate checks.

Barcode generation uses the supported formats documented by
[ReportLab](https://docs.reportlab.com/reportlab/barcode/).
