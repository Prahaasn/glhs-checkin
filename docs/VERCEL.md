# Vercel frontend

This deployment publishes the existing browser screens at an HTTPS address.
The Windows scanner computers can open the address without installing Python.
It does **not** host the Python API: signing in, displaying staff records,
and saving badge scans require the backend to be hosted and connected first.
Supabase stores the database; it does not serve this app's Python API.

## Deploy

Use the repository root, the Other framework preset, no install/build command,
and `app/static` as the output directory. `vercel.json` records these settings
and maps `/static/...` asset requests to the published files. There is no SPA
catch-all: `/api/...` must not return the login page with a misleading HTTP 200.
The `.vercelignore` allowlist limits CLI uploads to the frontend and config.
Do not add `.env`, database files, station keys, or passwords to the deployment.

The frontend is available at https://glhs-checkin.vercel.app. It is a standalone
static project named `glhs-checkin` under `prahaas-7509s-projects`. It does not automatically deploy future Git pushes.
After review/merge, a Git integration can use the same configuration.

## Verify and connect

Open the HTTPS URL on the HP and check that the login screen is styled and its
Office staff / Scanner station selector works. Check `/static/app.js` and
`/static/style.css` return their actual assets. Until the API is connected,
`/api/health` and sign-in requests fail; this is a frontend preview only.

To enable check-ins, host the existing FastAPI app with its private database
configuration and proxy `/api/:path*` to its approved HTTPS address. Preserve
the existing same-origin session-cookie and authorization behavior. Verify
secure cookies, office/station access, and a fictional badge scan end to end
before using staff records. Do not point a public deployment at localhost.

## Recovery

Remove the standalone Vercel deployment to withdraw its web link, or redeploy
a previous verified frontend revision. Reverting the Vercel configuration
has no effect on the local Python server or the database.
