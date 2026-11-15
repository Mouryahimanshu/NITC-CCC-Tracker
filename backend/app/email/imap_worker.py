"""Independent read-only IMAP polling worker using Gmail XOAUTH2."""

import imaplib
import logging
import os
import time
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

from app.core.config import get_settings
from app.core.config import BACKEND_ENV
from app.db.models import MailboxState
from app.db.postgres import dispose_database, initialize_database, session_scope

load_dotenv(BACKEND_ENV)
from app.email.processor import process_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
SCOPES = ["https://mail.google.com/"]


def get_credentials(client_secret_file: str, token_file: str) -> Credentials:
    creds = Credentials.from_authorized_user_file(token_file, SCOPES) if os.path.exists(token_file) else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(token_file, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
    return creds


def connect_mailbox(mailbox: str, access_token: str):
    connection = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    auth_string = f"user={mailbox}\x01auth=Bearer {access_token}\x01\x01".encode("utf-8")
    # imaplib.authenticate base64-encodes the callback response itself.
    connection.authenticate("XOAUTH2", lambda _: auth_string)
    typ, _ = connection.select("INBOX", readonly=True)
    if typ != "OK":
        raise RuntimeError("Unable to open INBOX read-only")
    return connection


def poll_once(connection, mailbox: str, initial_uid: int, allowed_senders: set[str]):
    typ, validity_data = connection.response("UIDVALIDITY")
    uid_validity = (validity_data or [b"unknown"])[0].decode("ascii", errors="replace")
    with session_scope() as db:
        state = db.get(MailboxState, mailbox)
        if state is None:
            # Establish a controlled baseline at the current mailbox high-water mark.
            typ, high = connection.uid("search", None, "ALL")
            baseline = max((int(value) for value in (high[0].split() if typ == "OK" and high and high[0] else [])), default=0)
            last_uid = max(initial_uid, baseline)
            db.add(MailboxState(mailbox_key=mailbox, uid_validity=uid_validity, last_uid=last_uid))
            db.commit()
            logging.info("Mailbox baseline established at UID %s; historical messages were not imported", last_uid)
            return last_uid, uid_validity
        last_uid = int(state.last_uid) if state.uid_validity == uid_validity else initial_uid
        if state.uid_validity != uid_validity:
            typ, high = connection.uid("search", None, "ALL")
            baseline = max((int(value) for value in (high[0].split() if typ == "OK" and high and high[0] else [])), default=0)
            state.uid_validity = uid_validity
            state.last_uid = max(initial_uid, baseline)
            db.commit()
            logging.info("UIDVALIDITY changed; reset safe baseline to UID %s without backfill", state.last_uid)
            return state.last_uid, uid_validity
        typ, data = connection.uid("search", None, f"UID {last_uid + 1}:*")
        state.updated_at = datetime.now(timezone.utc)
        db.commit()
        if typ != "OK" or not data or not data[0]:
            return last_uid, uid_validity
        for uid_bytes in data[0].split():
            uid = int(uid_bytes)
            typ, message_data = connection.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((part[1] for part in message_data if isinstance(part, tuple)), None) if message_data else None
            if typ != "OK" or raw is None:
                logging.error("Unable to fetch mailbox message UID %s", uid)
                break
            try:
                status = process_message(db, mailbox, uid_validity, uid, raw, allowed_senders)
                state = db.get(MailboxState, mailbox)
                state.uid_validity = uid_validity
                state.last_uid = uid
                state.updated_at = datetime.now(timezone.utc)
                db.commit()
                logging.info("Processed mailbox message UID %s with status %s", uid, status)
                last_uid = uid
            except Exception:
                db.rollback()
                logging.exception("Message processing failed for UID %s", uid)
                break
        return last_uid, uid_validity


def run():
    settings = get_settings()
    mailbox = os.getenv("GMAIL_MAILBOX", "").strip()
    client_secret = os.getenv("GMAIL_CLIENT_SECRET_FILE", "").strip()
    token_file = os.getenv("GMAIL_TOKEN_FILE", "token.json")
    if not mailbox or not client_secret:
        raise SystemExit("Set GMAIL_MAILBOX and GMAIL_CLIENT_SECRET_FILE in backend/.env")
    if not settings.database_url:
        raise SystemExit("Set DATABASE_URL in backend/.env")
    initialize_database()
    allowed = {email.strip().lower() for email in os.getenv("GMAIL_ALLOWED_SENDERS", "").split(",") if email.strip()}
    poll_seconds = max(30, int(os.getenv("GMAIL_POLL_SECONDS", "120")))
    try:
        while True:
            try:
                creds = get_credentials(client_secret, token_file)
                client = connect_mailbox(mailbox, creds.token)
                poll_once(client, mailbox, int(os.getenv("GMAIL_INITIAL_UID", "0")), allowed)
                client.logout()
            except Exception:
                logging.exception("Mailbox poll failed; retrying")
            time.sleep(poll_seconds)
    finally:
        dispose_database()


if __name__ == "__main__":
    run()
