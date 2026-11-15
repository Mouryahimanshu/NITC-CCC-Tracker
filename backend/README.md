# Backend

FastAPI backend for the NITC CCC Terminal Booking Tracker using PostgreSQL and SQLAlchemy.

From this directory, install `requirements.txt`, configure `DATABASE_URL` in `.env`, initialize the schema and seed data with `py -m scripts.bootstrap`, then run `uvicorn app.main:app --reload`. Interactive API docs are at `/docs` while the server is running.
