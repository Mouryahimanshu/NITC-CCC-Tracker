# NITC CCC Terminal Booking Tracker — Agent Instructions

## Project direction
- Build the NITC CCC Terminal Booking Tracker as a maintainable academic project.
- Follow `docs/architecture.md` and `docs/roadmap.md` as the current planning baseline.
- Keep the selected stack: React + Vite + Tailwind CSS + JavaScript; Python + FastAPI; PostgreSQL on Neon with SQLAlchemy/psycopg; Gmail IMAP OAuth 2.0 XOAUTH2 using Python standard-library IMAP/email modules.
- Do not substitute major technologies or introduce unnecessary dependencies without explaining the reason and obtaining the user's approval.

## Workflow
- Work one roadmap milestone at a time. Before each milestone, state its scope and implement only that scope.
- Inspect existing files before changing them. Preserve existing work; never delete or overwrite without explicit approval.
- Keep business logic out of API route handlers and separate frontend, API, persistence, booking, identity, and email concerns.
- Validate at the API and service/database boundary; frontend checks are not authoritative.
- Do not import historical mailbox contents automatically. Any baseline/backfill must be explicit and controlled.
- Never log or commit OAuth tokens, credentials, passwords, or other secrets. Keep local secrets outside version control.
- Use deterministic parsing for booking emails initially; do not add LLM parsing.
- Document design changes and assumptions. Ask before major architectural changes.
- Run relevant checks when requested or required by the active milestone, and report their results accurately.

## Domain invariants
- Rooms initially are T1–T6; operating hours are 08:00–20:00 in the configured campus timezone; booking boundaries are every 30 minutes.
- Confirmed bookings alone consume availability. Pending faculty requests do not.
- Booking intervals are half-open `[start, end)`: adjacent bookings are valid.
- Reject invalid/out-of-hours intervals and prevent overlapping confirmed bookings, including concurrent creation attempts.
- Imported invalid or conflicting messages must be retained in email processing logs for administrator review; never silently discard them.
- Preserve original emails: use read-only IMAP selection and `BODY.PEEK`; do not delete or mark messages read.

## Current stage
- Milestones 1–6 have implementation in the repository. Continue integration and live verification when the configured Neon connection is reachable and the authorized mailbox is supplied. Do not perform schema/bootstrap writes without the user's request.
