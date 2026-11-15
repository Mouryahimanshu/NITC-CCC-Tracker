"""PostgreSQL-backed mail processing with durable deduplication."""

from datetime import datetime, timezone
from email import message_from_bytes
from email.utils import parsedate_to_datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import EmailLog
from app.email.parser import _time_to_minutes, extract_booking_fields, extract_text, validate_booking_fields
from app.services.booking import _claim_booking, _audit


def process_message(db: Session, mailbox_key: str, uid_validity: str, uid: int, raw_message: bytes,
                    allowed_senders: set[str]):
    message = message_from_bytes(raw_message)
    message_id = (message.get("Message-ID") or "").strip() or None
    sender = (message.get("From") or "").strip()
    subject = (message.get("Subject") or "").strip()
    received = datetime.now(timezone.utc)
    try:
        received = parsedate_to_datetime(message.get("Date")) if message.get("Date") else received
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    log = db.scalar(select(EmailLog).where(EmailLog.mailbox_key == mailbox_key,
                                           EmailLog.uid_validity == str(uid_validity), EmailLog.imap_uid == uid))
    if log is None and message_id:
        log = db.scalar(select(EmailLog).where(EmailLog.mailbox_key == mailbox_key, EmailLog.message_id == message_id))
    if log and log.status in {"PROCESSED", "DISMISSED", "DUPLICATE"}:
        return log.status
    if log is None:
        log = EmailLog(mailbox_key=mailbox_key, uid_validity=str(uid_validity), imap_uid=uid,
                       message_id=message_id, sender=sender, subject=subject, received_at=received,
                       status="RECEIVED", attempt_count=0)
        db.add(log)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return "RECEIVED"
    log.status = "PROCESSING"
    log.attempt_count += 1
    sender_addr = sender.rsplit("<", 1)[-1].rstrip("> ").lower()
    if not allowed_senders or sender_addr not in allowed_senders:
        log.status = "NEEDS_REVIEW"
        log.error_code = "UNTRUSTED_SENDER"
        log.error_detail = "Sender is not in the configured allowlist"
        db.commit()
        return log.status
    log_id = log.id
    try:
        fields = extract_booking_fields(extract_text(message))
        log.parsed_room = fields.room_code if fields.room_code and len(fields.room_code) <= 2 else None
        log.parsed_date = fields.parsed_date
        log.parsed_start = _normalized_time(fields.start_text)
        log.parsed_end = _normalized_time(fields.end_text)
        log.parsed_purpose = fields.purpose
        # Mark as NEEDS_REVIEW initially until verified and confirmed
        log.status = "NEEDS_REVIEW"
        db.commit()
        booking_input = validate_booking_fields(fields)
        booking = _claim_booking(db, booking_input, "gmail-worker", "EMAIL", str(log.id))
        log.status = "PROCESSED"
        log.booking_id = booking.id
        log.error_code = None
        log.error_detail = None
        log.processed_at = datetime.now(timezone.utc)
        _audit(db, None, "EMAIL_BOOKING_IMPORTED", "booking", booking.id, {"email_log_id": log.id})
        db.commit()
        return log.status
    except IntegrityError:
        db.rollback()
        log = db.get(EmailLog, log_id)
        log.status = "NEEDS_REVIEW"
        log.error_code = "BOOKING_CONFLICT"
        log.error_detail = "One or more requested half-hour slots have already been allocated"
    except HTTPException as error:
        db.rollback()
        log = db.get(EmailLog, log_id)
        log.status = "NEEDS_REVIEW"
        log.error_code = "BOOKING_CONFLICT" if error.status_code == 409 else "INVALID_BOOKING_DATA"
        log.error_detail = str(error.detail)[:500]
    except (ValueError, TypeError) as error:
        db.rollback()
        log = db.get(EmailLog, log_id)
        log.status = "NEEDS_REVIEW"
        log.error_code = "INVALID_BOOKING_DATA"
        log.error_detail = str(error)[:500]
    except Exception as error:
        db.rollback()
        log = db.get(EmailLog, log_id)
        log.status = "FAILED"
        log.error_code = "PROCESSING_ERROR"
        log.error_detail = str(error)[:500]
    db.commit()
    return log.status


def _normalized_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        minutes = _time_to_minutes(value)
    except ValueError:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
