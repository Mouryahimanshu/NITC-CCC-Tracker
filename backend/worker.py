"""Launch the standalone Gmail polling worker with `py worker.py`."""

from app.email.imap_worker import run


if __name__ == "__main__":
    run()
