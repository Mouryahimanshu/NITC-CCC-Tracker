"""Comprehensive test suite verifying all aspects of the NITC CCC Terminal Booking Tracker."""

import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from starlette.testclient import TestClient

from app.core.config import get_settings
from app.db.models import Base, Booking, BookingRequest, Room, RoomMaintenance, User
from app.db.postgres import initialize_database, session_scope
from app.email.parser import extract_booking_fields, parse_date, validate_booking_fields
from app.email.processor import process_message
from app.main import app
from app.services.auth import hash_password

settings = get_settings()
tz = ZoneInfo(settings.campus_timezone)


def run_tests():
    print("=" * 70)
    print("STARTING NITC CCC TRACKER FULL SUITE AUDIT & TEST")
    print("=" * 70)

    # 1. Database & Schema Initialization
    print("\n[1/10] Verifying Database & Schema Initialization...")
    initialize_database()
    with session_scope() as db:
        # Ensure rooms T1-T6 exist
        for code in ("T1", "T2", "T3", "T4", "T5", "T6"):
            if db.query(Room).filter(Room.code == code).first() is None:
                db.add(Room(code=code, active=True))
        # Ensure admin user
        admin = db.query(User).filter(User.username == "admin").first()
        if admin is None:
            admin = User(username="admin", display_name="CCC Administrator",
                         password_hash=hash_password("AdminPass1234!"), role="ADMIN", active=True)
            db.add(admin)
        # Ensure faculty user
        faculty = db.query(User).filter(User.username == "faculty").first()
        if faculty is None:
            faculty = User(username="faculty", display_name="CCC Faculty",
                           password_hash=hash_password("FacultyPass1234!"), role="FACULTY", active=True)
            db.add(faculty)
        db.commit()
    print("  -> Database initialized with rooms T1-T6, admin, and faculty.")

    client = TestClient(app)

    # 2. Public / Health Endpoints
    print("\n[2/10] Testing Health & Root Endpoints...")
    res = client.get("/health")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert res.json() == {"status": "ok"}

    res = client.get(f"{settings.api_prefix}/")
    assert res.status_code == 200
    assert "NITC CCC" in res.json().get("name", "")
    print("  -> Health & Root endpoints passed.")

    # 3. Authentication & Authorization Tests
    print("\n[3/10] Testing Authentication & Authorization...")
    # Admin Login
    res = client.post(f"{settings.api_prefix}/auth/login", json={"username": "admin", "password": "AdminPass1234!"})
    assert res.status_code == 200, f"Admin login failed: {res.text}"
    admin_token = res.json()["access_token"]
    assert res.json()["user"]["role"] == "ADMIN"

    # Faculty Login
    res = client.post(f"{settings.api_prefix}/auth/login", json={"username": "faculty", "password": "FacultyPass1234!"})
    assert res.status_code == 200, f"Faculty login failed: {res.text}"
    faculty_token = res.json()["access_token"]
    assert res.json()["user"]["role"] == "FACULTY"

    # Invalid Password
    res = client.post(f"{settings.api_prefix}/auth/login", json={"username": "admin", "password": "WrongPassword!"})
    assert res.status_code == 401

    # Invalid User
    res = client.post(f"{settings.api_prefix}/auth/login", json={"username": "nonexistent", "password": "Password123!"})
    assert res.status_code == 401

    # Protected me endpoint with tokens
    res = client.get(f"{settings.api_prefix}/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert res.json()["username"] == "admin"

    res = client.get(f"{settings.api_prefix}/auth/me", headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 200
    assert res.json()["username"] == "faculty"

    # Role enforcement: Faculty calling Admin endpoint -> 403 Forbidden
    res = client.get(f"{settings.api_prefix}/admin/bookings?from=2026-11-16",
                     headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 403, f"Expected 403 for faculty accessing admin route, got {res.status_code}"

    # Missing token -> 401 Unauthorized
    res = client.get(f"{settings.api_prefix}/admin/bookings?from=2026-11-16")
    assert res.status_code == 401
    print("  -> Authentication & Role-based Access Control passed.")

    # 4. Rooms & Public Availability Tests
    print("\n[4/10] Testing Rooms & Availability Grid...")
    res = client.get(f"{settings.api_prefix}/rooms")
    assert res.status_code == 200
    room_codes = [r["code"] for r in res.json()]
    assert set(room_codes) == {"T1", "T2", "T3", "T4", "T5", "T6"}

    today = datetime.now(tz).date()
    today_str = today.isoformat()
    res = client.get(f"{settings.api_prefix}/rooms/availability?from={today_str}&days=3")
    assert res.status_code == 200
    avail_data = res.json()
    assert len(avail_data) == 3 * 6  # 3 days * 6 rooms
    # Check slots: 08:00 to 20:00 is 12 hours = 24 slots of 30 minutes
    assert len(avail_data[0]["slots"]) == 24
    assert avail_data[0]["slots"][0]["start"] == "08:00"
    assert avail_data[0]["slots"][-1]["end"] == "20:00"
    print("  -> Rooms listing & 30-min availability grid (08:00-20:00 IST) passed.")

    # 5. Faculty Booking Requests Workflow
    print("\n[5/10] Testing Faculty Booking Requests...")
    test_date = (today + timedelta(days=2)).isoformat()

    # Valid request
    req_body = {
        "room_code": "T1",
        "booking_date": test_date,
        "start_time": "10:00",
        "end_time": "11:30",
        "purpose": "CS3001 Operating Systems Lab Exam",
    }
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=req_body, headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 201, f"Create request failed: {res.text}"
    req_id = res.json()["id"]
    assert res.json()["status"] == "PENDING"

    # View faculty's own requests
    res = client.get(f"{settings.api_prefix}/booking-requests/mine",
                     headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 200
    mine = res.json()
    assert any(r["id"] == str(req_id) for r in mine)

    # Overlapping request for same room and time should be rejected (409)
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=req_body, headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 409, f"Expected 409 overlap, got {res.status_code}"

    # Invalid boundary: past date
    past_date = (today - timedelta(days=1)).isoformat()
    invalid_past = {**req_body, "booking_date": past_date}
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=invalid_past, headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 422, f"Expected 422 for past date, got {res.status_code}"

    # Invalid boundary: end <= start
    invalid_times = {**req_body, "start_time": "11:00", "end_time": "10:00"}
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=invalid_times, headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 422

    # Invalid boundary: outside operating hours (e.g. 07:30 or 20:30)
    invalid_hours = {**req_body, "start_time": "07:30", "end_time": "09:00"}
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=invalid_hours, headers={"Authorization": f"Bearer {faculty_token}"})
    assert res.status_code == 422

    print("  -> Faculty request creation, listing, conflict detection, and input validation passed.")

    # 6. Admin Approval & Booking Lifecycle
    print("\n[6/10] Testing Admin Decision & Booking Lifecycle...")
    # Admin fetches pending requests
    res = client.get(f"{settings.api_prefix}/admin/booking-requests?status=PENDING",
                     headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    pending_list = res.json()
    assert any(r["id"] == str(req_id) for r in pending_list)

    # Admin approves request
    res = client.post(f"{settings.api_prefix}/admin/booking-requests/{req_id}/approve",
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200, f"Approval failed: {res.text}"
    booking_id = int(res.json()["id"])

    # Availability must now show BOOKED for 10:00-11:30 in T1 on test_date
    res = client.get(f"{settings.api_prefix}/rooms/availability?from={test_date}&days=1")
    t1_day = next(r for r in res.json() if r["room_code"] == "T1")
    slots_10_to_1130 = [s for s in t1_day["slots"] if s["start"] in ("10:00", "10:30", "11:00")]
    for s in slots_10_to_1130:
        assert s["status"] == "BOOKED", f"Slot {s['start']} should be BOOKED, was {s['status']}"

    # Admin modifies booking time (e.g. shift to 11:30-13:00)
    update_body = {
        "room_code": "T1",
        "booking_date": test_date,
        "start_time": "11:30",
        "end_time": "13:00",
        "purpose": "Rescheduled OS Lab Exam",
    }
    res = client.patch(f"{settings.api_prefix}/admin/bookings/{booking_id}",
                       json=update_body, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200, f"Booking update failed: {res.text}"

    # Verify old slot 10:00-10:30 is now AVAILABLE
    res = client.get(f"{settings.api_prefix}/rooms/availability?from={test_date}&days=1")
    t1_day = next(r for r in res.json() if r["room_code"] == "T1")
    slot_10 = next(s for s in t1_day["slots"] if s["start"] == "10:00")
    assert slot_10["status"] == "AVAILABLE"
    slot_12 = next(s for s in t1_day["slots"] if s["start"] == "12:00")
    assert slot_12["status"] == "BOOKED"

    # Admin deletes the booking
    res = client.delete(f"{settings.api_prefix}/admin/bookings/{booking_id}",
                        headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200

    # Verify all slots for T1 are now AVAILABLE again
    res = client.get(f"{settings.api_prefix}/rooms/availability?from={test_date}&days=1")
    t1_day = next(r for r in res.json() if r["room_code"] == "T1")
    for s in t1_day["slots"]:
        assert s["status"] == "AVAILABLE"
    print("  -> Admin request approval, schedule reflection, booking update, and deletion passed.")

    # 7. Admin Rejection with Reason
    print("\n[7/10] Testing Faculty Request Rejection...")
    req_body_rej = {
        "room_code": "T2",
        "booking_date": test_date,
        "start_time": "14:00",
        "end_time": "16:00",
        "purpose": "Seminar Session",
    }
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=req_body_rej, headers={"Authorization": f"Bearer {faculty_token}"})
    rej_req_id = res.json()["id"]

    # Reject without note (too short) -> 422
    res = client.post(f"{settings.api_prefix}/admin/booking-requests/{rej_req_id}/reject",
                      json={"note": "no"}, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 422

    # Reject with valid note
    res = client.post(f"{settings.api_prefix}/admin/booking-requests/{rej_req_id}/reject",
                      json={"note": "Room T2 scheduled for department maintenance"},
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert res.json()["status"] == "REJECTED"
    print("  -> Request rejection and mandatory reason validation passed.")

    # 8. Room Maintenance Lifecycle
    print("\n[8/10] Testing Room Maintenance & Conflict Auto-Resolution...")
    maint_date = (today + timedelta(days=3)).isoformat()
    # 1. Create a confirmed booking first in T3
    req_maint_booking = {
        "room_code": "T3",
        "booking_date": maint_date,
        "start_time": "09:00",
        "end_time": "11:00",
        "purpose": "Session to be cancelled by maintenance",
    }
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=req_maint_booking, headers={"Authorization": f"Bearer {faculty_token}"})
    m_bid = res.json()["id"]
    client.post(f"{settings.api_prefix}/admin/booking-requests/{m_bid}/approve",
                headers={"Authorization": f"Bearer {admin_token}"})

    # 2. Schedule maintenance window covering 08:30-12:00 in T3
    maint_payload = {
        "room_code": "T3",
        "maintenance_date": maint_date,
        "start_time": "08:30",
        "end_time": "12:00",
        "note": "Quarterly switchboard servicing",
    }
    res = client.post(f"{settings.api_prefix}/admin/room-maintenance",
                      json=maint_payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 201, f"Failed to create maintenance: {res.text}"
    maint_id = res.json()["id"]
    assert res.json()["cancelled_bookings"] == 1, "Should have cancelled 1 overlapping booking"

    # Verify slots show MAINTENANCE
    res = client.get(f"{settings.api_prefix}/rooms/availability?from={maint_date}&days=1")
    t3_day = next(r for r in res.json() if r["room_code"] == "T3")
    maint_slot = next(s for s in t3_day["slots"] if s["start"] == "09:00")
    assert maint_slot["status"] == "MAINTENANCE"

    # 3. Clear maintenance
    res = client.post(f"{settings.api_prefix}/admin/room-maintenance/{maint_id}/clear",
                      headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert res.json()["status"] == "CLEARED"

    # Verify slot is AVAILABLE again
    res = client.get(f"{settings.api_prefix}/rooms/availability?from={maint_date}&days=1")
    t3_day = next(r for r in res.json() if r["room_code"] == "T3")
    cleared_slot = next(s for s in t3_day["slots"] if s["start"] == "09:00")
    assert cleared_slot["status"] == "AVAILABLE"
    print("  -> Room maintenance scheduling, auto-cancellation of bookings, and clear passed.")

    # 9. Admin User Management & Student Role Access
    print("\n[9/10] Testing User Creation (Student/Faculty) & Authentication...")
    new_student = {
        "username": "student_test",
        "display_name": "Test Student NITC",
        "password": "StudentPassword1234!",
        "role": "STUDENT",
    }
    res = client.post(f"{settings.api_prefix}/admin/users",
                      json=new_student, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 201
    assert res.json()["username"] == "student_test"
    assert res.json()["role"] == "STUDENT"

    # Test login with student account
    res = client.post(f"{settings.api_prefix}/auth/login",
                      json={"username": "student_test", "password": "StudentPassword1234!"})
    assert res.status_code == 200
    student_token = res.json()["access_token"]
    assert res.json()["user"]["role"] == "STUDENT"

    # Student cannot submit booking requests -> 403 Forbidden
    res = client.post(f"{settings.api_prefix}/booking-requests",
                      json=req_body, headers={"Authorization": f"Bearer {student_token}"})
    assert res.status_code == 403

    # Duplicate username error
    res = client.post(f"{settings.api_prefix}/admin/users",
                      json=new_student, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 409

    # Password too short (<12 chars) -> 422
    short_pw_user = {**new_student, "username": "short_user", "password": "short"}
    res = client.post(f"{settings.api_prefix}/admin/users",
                      json=short_pw_user, headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 422
    print("  -> User management, role isolation (Student view-only), and constraint checks passed.")

    # 10. Email Parsing & Ingestion Worker
    print("\n[10/10] Testing Email Parser & Ingestion Pipeline...")
    # Plain text format test
    plain_email = f"""
    Room: T4
    Date: {test_date}
    Start: 15:00
    End: 17:00
    Purpose: Campus Placement Coding Test
    """
    fields = extract_booking_fields(plain_email)
    assert fields.room_code == "T4"
    assert fields.date_text.strip() == test_date
    assert fields.start_text.strip() == "15:00"
    assert fields.end_text.strip() == "17:00"
    booking_input = validate_booking_fields(fields)
    assert booking_input.room_code == "T4"
    assert booking_input.start_time == "15:00"
    assert booking_input.end_time == "17:00"

    # CCC Bulletin bulletin format test
    bulletin_email = f"""
    Terminal Room T5 at the Central Computer Center has been reserved for Online assessment as per the following schedule:
    Date : {test_date}
    Time : 02:00 PM to 04:30 PM
    Required : CCC Terminal 5
    """
    b_fields = extract_booking_fields(bulletin_email)
    assert b_fields.room_code == "T5"
    b_input = validate_booking_fields(b_fields)
    assert b_input.room_code == "T5"
    assert b_input.start_time == "14:00"
    assert b_input.end_time == "16:30"
    assert "Online assessment" in b_input.purpose

    # Test full process_message pipeline in DB
    raw_mime = f"""From: maincc@nitc.ac.in
To: ccc-terminal@nitc.ac.in
Subject: Booking confirmation T6
Message-ID: <test-email-msg-001@nitc.ac.in>
Date: Mon, 16 Nov 2026 09:00:00 +0530
Content-Type: text/plain

Room: T6
Date: {test_date}
Start: 13:00
End: 15:00
Purpose: ACM ICPC Practice Contest
""".strip().encode("utf-8")

    with session_scope() as db:
        status = process_message(db, "maincc@nitc.ac.in", "12345", 101, raw_mime, {"maincc@nitc.ac.in"})
        assert status == "PROCESSED", f"Expected PROCESSED, got {status}"

    # Verify T6 is now BOOKED on test_date
    res = client.get(f"{settings.api_prefix}/rooms/availability?from={test_date}&days=1")
    t6_day = next(r for r in res.json() if r["room_code"] == "T6")
    slot_t6 = next(s for s in t6_day["slots"] if s["start"] == "13:00")
    assert slot_t6["status"] == "BOOKED"

    # Untrusted sender test -> status INVALID
    untrusted_mime = f"""From: hacker@unknown.org
Subject: Bad request
Content-Type: text/plain

Room: T6
Date: {test_date}
Start: 08:00
End: 09:00
Purpose: Unauthorized
""".strip().encode("utf-8")

    with session_scope() as db:
        status = process_message(db, "maincc@nitc.ac.in", "12345", 102, untrusted_mime, {"maincc@nitc.ac.in"})
        assert status == "INVALID"

    print("  -> Email extraction, bulletin parsing, sender allowlist, and database ingestion passed.")

    # Audit log inspection
    res = client.get(f"{settings.api_prefix}/admin/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert len(res.json()) >= 5
    print("  -> Audit log inspection verified.")

    print("\n" + "=" * 70)
    print("ALL 10 TEST SUITES PASSED FLAWLESSLY! CODEBASE FULLY CERTIFIED.")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()
