# NITC CCC Terminal Booking Tracker

A web application for browsing 1–4 weeks of NITC Central Computer Centre room availability and managing T1–T6 bookings on a 30-minute timeline.

## Project status

Implementation covers the initial setup, backend foundation, booking workflows, Gmail worker, and role-based dashboard. The database target is Neon PostgreSQL. Read [the architecture plan](docs/architecture.md), [the development/runbook](docs/development.md), and [the milestone roadmap](docs/roadmap.md).

## Planned stack

- Frontend: React, Vite, Tailwind CSS, JavaScript
- API: Python, FastAPI, REST
- Data: PostgreSQL (recommended host: Neon Free) and SQLAlchemy
- Mail integration: Gmail IMAP with OAuth 2.0 XOAUTH2, implemented with Python standard-library `imaplib` and `email`

## Local development

See [docs/development.md](docs/development.md) for setup and run commands. Copy `backend/.env.example` to `backend/.env` and set local values as needed. Never commit `.env`, OAuth client files, or token files.

For production hosting, see [the Vercel deployment guide](docs/deployment-vercel.md). The frontend and FastAPI API are deployed as separate Vercel projects from this repository.
