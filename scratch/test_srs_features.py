import os
import sys
import json
import random
from datetime import datetime, timezone, date

# Ensure backend directory is in sys.path
backend_dir = os.path.abspath("backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.db.postgres import initialize_database, session_scope
from app.db.models import Base, User, Room, Booking, EmailLog, AuditLog, MailboxState
from app.auth.security import hash_password, verify_password, create_access_token
from app.services.booking import create_booking_request, clear_room_maintenance

def test_all():
    initialize_database()
    with session_scope() as db:
        print("[1] Testing sync-status endpoint logic...")
        state = db.query(MailboxState).first()
        if not state:
            state = MailboxState(mailbox_key="ccc@nitc.ac.in", uid_validity="1", last_uid=0, updated_at=datetime.now(timezone.utc))
            db.add(state)
            db.commit()
            db.refresh(state)
        print(f"  MailboxState updated_at: {state.updated_at}")

        print("[2] Testing admin user & audit logs...")
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(username="admin", display_name="CCC Admin", password_hash=hash_password("admin1234567"), role="ADMIN", active=True)
            db.add(admin)
            db.commit()
            db.refresh(admin)
        print(f"  Admin user found: id={admin.id}, username={admin.username}")

        print("[3] Testing Needs Review flow...")
        uid1 = random.randint(100000, 999999)
        # Create a dummy email log needing review
        dummy_email = EmailLog(
            mailbox_key="ccc@nitc.ac.in",
            uid_validity="1",
            imap_uid=uid1,
            message_id=f"test-msg-{uid1}@nitc.ac.in",
            sender="faculty@nitc.ac.in",
            subject="Urgent booking for lab",
            status="NEEDS_REVIEW",
            error_code="UNPARSED_FIELDS",
            error_detail="Could not extract booking start and end times",
            parsed_room="T1",
            parsed_date=date(2026, 11, 25),
            parsed_purpose="Database Lab Session",
            received_at=datetime.now(timezone.utc)
        )
        db.add(dummy_email)
        db.commit()
        db.refresh(dummy_email)
        print(f"  Created EmailLog in NEEDS_REVIEW: id={dummy_email.id}")

        # Correct fields
        from app.api.routes.bookings import correct_needs_review, confirm_needs_review, dismiss_needs_review
        patch_payload = {
            "start_time": "10:00",
            "end_time": "12:00"
        }
        corrected = correct_needs_review(dummy_email.id, patch_payload, admin=admin, db=db)
        print(f"  Corrected fields: {corrected['parsed']}")
        assert corrected['parsed']['start_time'] == "10:00"
        assert corrected['parsed']['end_time'] == "12:00"

        # Confirm into booking
        confirmed = confirm_needs_review(dummy_email.id, admin=admin, db=db)
        print(f"  Confirmed into booking: booking_id={confirmed['booking_id']}, status={confirmed['status']}")
        assert confirmed['status'] == "PROCESSED"

        # Verify Audit Log
        audit = db.query(AuditLog).filter(AuditLog.entity_id == str(dummy_email.id)).all()
        print(f"  Audit logs recorded for email record: {[a.action for a in audit]}")
        assert any(a.action == "EMAIL_RECORD_CORRECTED" for a in audit)
        assert any(a.action == "EMAIL_RECORD_CONFIRMED" for a in audit)

        # Test Dismiss flow
        uid2 = random.randint(100000, 999999)
        dummy_spam = EmailLog(
            mailbox_key="ccc@nitc.ac.in",
            uid_validity="1",
            imap_uid=uid2,
            message_id=f"spam-msg-{uid2}@outside.com",
            sender="unknown@gmail.com",
            subject="Random inquiry",
            status="NEEDS_REVIEW",
            error_code="UNTRUSTED_SENDER",
            error_detail="Sender address not in trusted domain list",
            received_at=datetime.now(timezone.utc)
        )
        db.add(dummy_spam)
        db.commit()
        db.refresh(dummy_spam)

        dismissed = dismiss_needs_review(dummy_spam.id, {"reason": "Spam sender rejected"}, admin=admin, db=db)
        print(f"  Dismissed email record: status={dismissed['status']}, reason={dismissed['reason']}")
        assert dismissed['status'] == "DISMISSED"

        # Test booking cancellation with reason
        from app.services.booking import _remove_confirmed_booking
        b_id = int(confirmed['booking_id'])
        cancelled = _remove_confirmed_booking(db, b_id, str(admin.id), reason="Cancelled for server maintenance")
        print(f"  Booking cancelled: {cancelled}")
        cancel_audit = db.query(AuditLog).filter(AuditLog.entity_type == "booking", AuditLog.entity_id == str(b_id), AuditLog.action == "BOOKING_CANCELLED").first()
        assert cancel_audit is not None
        details = json.loads(cancel_audit.details)
        print(f"  Cancellation audit details: {details}")
        assert details.get("reason") == "Cancelled for server maintenance"

        # Test creating student user is rejected
        from app.api.routes.bookings import create_user
        from fastapi import HTTPException
        student_rejected = False
        try:
            create_user({"username": "newstudent", "display_name": "New Student", "password": "password12345", "role": "STUDENT"}, admin=admin, db=db)
        except HTTPException as e:
            if e.status_code == 422:
                student_rejected = True
                print(f"  Creating student user properly rejected with 422: {e.detail}")
        assert student_rejected, "Creating student user must be rejected!"

        print("\nALL BACKEND SRS VERIFICATION TESTS PASSED SUCCESSFULLY! ✓")

if __name__ == "__main__":
    test_all()
