# Local Development

## Prerequisites

- Node.js and npm
- Python 3.11 or newer (the project virtual environment is configured with Python 3.14)
- Git
- A PostgreSQL database URL (Neon is the selected free-tier host)

## Frontend

```powershell
cd "E:\NITC\SS lab\NITC CCC tracker\frontend"
npm install
npm run dev
```

Vite prints the local URL, normally `http://localhost:5173`. The development server proxies `/api` and `/health` to the local FastAPI server.

## Backend

```powershell
cd "E:\NITC\SS lab\NITC CCC tracker\backend"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8001
```

The API is normally available at `http://127.0.0.1:8000`; interactive docs are at `/docs` and liveness is at `/health`. This workstation uses port 8001 because port 8000 is occupied; `frontend/.env.local` sets the local Vite proxy target and is ignored by Git. In the Neon dashboard, create a PostgreSQL project and copy the connection URL (the direct endpoint is recommended for schema/bootstrap operations). Set `DATABASE_URL` in `backend/.env`; include `sslmode=require` as provided by Neon. Run the idempotent initial data setup from the backend directory with `py -m scripts.bootstrap`. This creates the schema and rooms T1–T6, and creates configured initial admin/faculty accounts only when those usernames do not already exist.

## Configuration and secrets

Use `backend/.env` for local settings. The checked-in `.env.example` contains placeholders only. Never place OAuth credentials, tokens, database passwords, or real user passwords in source files or commit them. The OAuth client file remains at its protected local path and the Gmail worker reads it when authorized.

## Foundation API

- `POST /api/v1/auth/login` accepts application username/password and returns a short-lived bearer token.
- `GET /api/v1/auth/me` returns the authenticated user's safe profile.
- `GET /api/v1/rooms` returns active rooms to authenticated users.
- `GET /health` is a non-sensitive liveness endpoint.

Public signup is not implemented. After the schema is initialized and an administrator exists, admins can create student, faculty, and additional admin accounts in the frontend.

## Gmail worker setup

The OAuth client file is not stored in this repository. Set `GMAIL_CLIENT_SECRET_FILE` to its protected absolute path in `backend/.env`, set `GMAIL_MAILBOX` to the exact authorized mailbox, and set `GMAIL_ALLOWED_SENDERS` to a comma-separated allowlist of official sender addresses. Leave the allowlist empty only in a controlled test mailbox. The requested `https://mail.google.com/` OAuth scope grants broad mailbox access; protect the client/token files and revoke access when no longer needed.

Run the worker from the backend directory with `py worker.py`. The first run establishes a current UID high-water baseline and does not import mailbox history. Subsequent polling occurs every 30 seconds using read-only selection and `BODY.PEEK`. The first authorization opens the Google consent flow. The generated token file must remain outside source control.

Supported plain-text booking format (labels are case-insensitive):

```text
Room: T1
Date: 2026-11-20
Start: 09:00
End: 11:00
Purpose: Example lab session
```

The date accepts ISO, numeric day/month/year, and common month-name formats. Start/end values may use 24-hour or AM/PM notation and must align to 30-minute IST boundaries in the 08:00–20:00 window. The CCC bulletin format is also supported:

```text
Terminal Room T2 at the Central Computer Center has been reserved for Online assessment as per the following schedule:
Date :14 November 2026 (Saturday)
Time : 08:00 PM to 10:30 PM
Required : CCC Terminal 2
```

This example is extracted but rejected because it extends past closing time. Admin email logs show the safely parsed room/date/times/purpose and validation reason, including for invalid messages. Full email bodies are neither stored nor displayed.

## Frontend role pages

The React app provides a public room timeline with 1-, 2-, and 4-week ranges. Confirmed bookings and maintenance periods appear as duration bars on half-hour time tracks. The header offers separate faculty/admin login choices in a minimizable right-side drawer. Faculty and administrator dashboards have separate hash routes (`#faculty` and `#admin`). Admins can schedule and clear room maintenance windows; overlapping bookings and requests are rejected. Student accounts get a view-only dashboard; faculty can submit booking requests and view their status/history; administrators can create accounts, approve/reject requests, inspect email parsing outcomes and audit events, and cancel confirmed bookings.

## Admin-created user accounts

After signing in as administrator, create accounts with `POST /api/v1/admin/users` using `{ "username", "display_name", "password", "role" }`. Passwords must be at least 12 characters. Roles are `STUDENT`, `FACULTY`, or `ADMIN`. Do not send credentials over an insecure channel. Temporary local bootstrap credentials are stored in the ignored `backend/local-credentials.json` file; they are not usable until the bootstrap command connects to the database successfully.

## Limitations at this stage

- Live API, worker, login, and data flows require a reachable PostgreSQL database and local `.env` configuration. The Neon project and production branch are linked; connectivity from this workstation still needs confirmation.
- Booking lifecycle now uses PostgreSQL transactions and a unique constraint over room/date/slot allocation.
- Gmail sender policy and official template changes should be confirmed with CCC. The parser is deterministic and rejects messages that violate room, date, time, or slot rules.
- Initial bootstrap admin creation is optional and idempotent; changing an existing admin password is not supported by the bootstrap command.
- Cancellation email notifications and email-driven amendments are not implemented because requirements do not define their behavior.

## Current assumptions

`Asia/Kolkata` and 30-minute booking boundaries are the selected project settings. Live booking flows require the backend and PostgreSQL database to be running.
