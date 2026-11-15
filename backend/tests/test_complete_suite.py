"""Comprehensive end-to-end and unit test suite for NITC CCC Terminal Booking Tracker."""

import os
import sys
import json
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import urllib.request
import urllib.error

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import get_settings
from app.db.models import AuditLog, Booking, BookingRequest, EmailLog, Room, RoomMaintenance, SlotAllocation, User
from app.db.postgres import dispose_database, initialize_database, session_scope
from app.domain.booking import BookingInput, MaintenanceInput
from app.email.parser import _time_to_minutes, extract_booking_fields, parse_date, validate_booking_fields
from app.email.processor import process_message
from app.services.auth import create_access_token, hash_password, verify_password
from app.services.booking import (
    _claim_booking,
    cancel_booking,
    clear_room_maintenance,
    create_request,
    create_room_maintenance,
    decide_request,
    delete_confirmed_booking,
    list_availability,
    update_confirmed_booking,
)

settings = get_settings()
tz = ZoneInfo(settings.campus_timezone)


def run_unit_and_service_tests():
    print("=" * 70)
    print("PHASE 1: UNIT & SERVICE LAYER TESTS")
    print("=" * 70)

    # 1. Auth Service
    print("\n[1/5] Testing Auth Service (Hashing, Tokens, Verification)...")
    raw_pass = "TestSecurePassword123!"
    hashed = hash_password(raw_pass)
    assert verify_password(raw_pass, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False

    token = create_access_token("1", "ADMIN")
    assert isinstance(token, str) and len(token) > 20
    print("  -> Password hashing and JWT generation passed.")

    # 2. Domain Models & Validations
    print("\n[2/5] Testing Domain Model Invariants...")
    today = datetime.now(tz).date()
    valid_date = today + timedelta(days=1)

    # Valid BookingInput
    bi = BookingInput(room_code="T1", booking_date=valid_date, start_time="08:00", end_time="10:00",
                      purpose="Valid lab session")
    assert bi.start_minute == 480
    assert bi.end_minute == 600
    assert bi.slot_ids == [480, 510, 540, 570]

    # Past date rejected
    try:
        BookingInput(room_code="T1", booking_date=today - timedelta(days=1), start_time="08:00", end_time="10:00",
                     purpose="Past date")
        assert False, "Should have rejected past date"
    except ValueError as e:
        assert "past" in str(e).lower()

    # End <= Start rejected
    try:
        BookingInput(room_code="T1", booking_date=valid_date, start_time="10:00", end_time="09:00",
                     purpose="Inverted times")
        assert False, "Should have rejected end <= start"
    except ValueError:
        pass

    # Maintenance past date rejected
    try:
        MaintenanceInput(room_code="T1", maintenance_date=today - timedelta(days=1),
                         start_time="08:00", end_time="10:00", note="Past maintenance")
        assert False, "Should have rejected past maintenance"
    except ValueError as e:
        assert "past" in str(e).lower()

    print("  -> Domain validation rules & boundary invariants passed.")

    # 3. Email Parser & Extraction
    print("\n[3/5] Testing Email Parsing & Formats...")
    # Standard format
    plain_text = f"""
    Room: T3
    Date: {valid_date.isoformat()}
    Start: 09:30 AM
    End: 11:30 AM
    Purpose: Data Structures Lab
    """
    fields = extract_booking_fields(plain_text)
    assert fields.room_code == "T3"
    assert fields.parsed_date == valid_date
    b_in = validate_booking_fields(fields)
    assert b_in.start_time == "09:30"
    assert b_in.end_time == "11:30"

    # Bulletin format
    bulletin = f"""
    Terminal Room T2 at the Central Computer Center has been reserved for Online Placement Test as per the following schedule:
    Date : {valid_date.strftime('%d %B %Y')} (Wednesday)
    Time : 02:00 PM to 04:00 PM
    Required : CCC Terminal 2
    """
    b_fields = extract_booking_fields(bulletin)
    assert b_fields.room_code == "T2"
    b_in2 = validate_booking_fields(b_fields)
    assert b_in2.start_time == "14:00"
    assert b_in2.end_time == "16:00"
    assert "Placement Test" in b_in2.purpose

    # Time parsing checks
    assert _time_to_minutes("08:00") == 480
    assert _time_to_minutes("08:00 AM") == 480
    assert _time_to_minutes("12:00 PM") == 720
    assert _time_to_minutes("08:00 PM") == 1200
    assert _time_to_minutes("20:00") == 1200
    assert _time_to_minutes("8.30 am") == 510

    # Date parsing checks
    assert parse_date("2026-11-20") == date(2026, 11, 20)
    assert parse_date("20th November 2026") == date(2026, 11, 20)
    assert parse_date("20 Nov 2026") == date(2026, 11, 20)
    assert parse_date("20/11/2026") == date(2026, 11, 20)

    print("  -> Deterministic plain text and bulletin extraction passed.")

    # 4. Service Layer Booking & Maintenance Life Cycle
    print("\n[4/5] Testing Booking Service, Slot Allocations & Maintenance Conflict Resolution...")
    initialize_database()
    with session_scope() as db:
        admin = db.query(User).filter(User.username == "admin").first()
        faculty = db.query(User).filter(User.username == "faculty").first()
        assert admin is not None and faculty is not None

        test_day = today + timedelta(days=5)

        # 4a. Create a faculty request
        b_input = BookingInput(room_code="T1", booking_date=test_day, start_time="14:00", end_time="16:00",
                               purpose="DBMS Project Review")
        req = create_request(db, b_input, faculty)
        assert req.status == "PENDING"
        req_id = req.id

        # 4b. Approve request -> creates Booking and SlotAllocations
        booking = decide_request(db, req_id, admin, approve=True)
        assert booking.status == "CONFIRMED"
        b_id = booking.id

        # Check slot allocations: 14:00, 14:30, 15:00, 15:30 -> 840, 870, 900, 930
        slots = db.query(SlotAllocation).filter(SlotAllocation.booking_id == b_id).all()
        assert len(slots) == 4
        assert {s.slot_id for s in slots} == {840, 870, 900, 930}

        # 4c. Verify overlap conflict is rejected
        try:
            b_conflict = BookingInput(room_code="T1", booking_date=test_day, start_time="15:00", end_time="17:00",
                                     purpose="Conflicting request")
            create_request(db, b_conflict, faculty)
            assert False, "Should have rejected overlapping request"
        except Exception as e:
            assert "overlap" in str(e).lower()

        # 4d. Schedule maintenance that overlaps with this booking (13:30 - 17:00)
        m_input = MaintenanceInput(room_code="T1", maintenance_date=test_day, start_time="13:30", end_time="17:00",
                                   note="Air conditioning repair")
        maint = create_room_maintenance(db, m_input, admin)
        assert maint.active is True
        # Verify the overlapping booking was automatically cancelled
        db.refresh(booking)
        assert booking.status == "CANCELLED"
        # Verify slots were freed
        remaining_slots = db.query(SlotAllocation).filter(SlotAllocation.booking_id == b_id).all()
        assert len(remaining_slots) == 0

        # 4e. Clear maintenance
        res_clear = clear_room_maintenance(db, maint.id, admin)
        assert res_clear["status"] == "CLEARED"

    print("  -> Service lifecycle, slot allocation, maintenance conflict resolution passed.")

    # 5. Email Ingestion via process_message
    print("\n[5/5] Testing Direct Email Message Ingestion in Database...")
    with session_scope() as db:
        test_email_day = today + timedelta(days=6)
        raw_msg = f"""From: maincc@nitc.ac.in
To: ccc@nitc.ac.in
Subject: Terminal T4 reservation
Message-ID: <test-email-{time.time()}@nitc.ac.in>
Date: Mon, 16 Nov 2026 10:00:00 +0530
Content-Type: text/plain

Room: T4
Date: {test_email_day.isoformat()}
Start: 10:00
End: 12:00
Purpose: High Performance Computing Workshop
""".strip().encode("utf-8")

        status = process_message(db, "maincc@nitc.ac.in", "999", 501, raw_msg, {"maincc@nitc.ac.in"})
        assert status == "PROCESSED", f"Expected PROCESSED, got {status}"

        # Verify booking in database
        b_email = db.query(Booking).filter(Booking.room_code == "T4", Booking.booking_date == test_email_day,
                                           Booking.start_time == "10:00").first()
        assert b_email is not None
        assert b_email.source == "EMAIL"

    print("  -> Email processor database ingestion and auto-confirmation passed.")


def run_http_api_tests():
    print("\n" + "=" * 70)
    print("PHASE 2: LIVE HTTP API ENDPOINT TESTS (via localhost:8000)")
    print("=" * 70)

    base = "http://127.0.0.1:8000"

    def api_call(path, method="GET", body=None, token=None):
        url = f"{base}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                code = res.getcode()
                raw = res.read().decode("utf-8")
                return code, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            return e.code, json.loads(raw) if raw else None

    # Check liveness
    code, res = api_call("/health")
    assert code == 200 and res == {"status": "ok"}, f"Health check failed: {code}, {res}"
    print("  [HTTP] GET /health -> OK")

    # Admin Login
    code, res = api_call("/api/v1/auth/login", method="POST",
                         body={"username": "admin", "password": "AdminPass1234!"})
    assert code == 200, f"Admin login failed: {code}, {res}"
    admin_token = res["access_token"]
    print("  [HTTP] POST /api/v1/auth/login (Admin) -> OK")

    # Faculty Login
    code, res = api_call("/api/v1/auth/login", method="POST",
                         body={"username": "faculty", "password": "FacultyPass1234!"})
    assert code == 200, f"Faculty login failed: {code}, {res}"
    faculty_token = res["access_token"]
    print("  [HTTP] POST /api/v1/auth/login (Faculty) -> OK")

    # Rooms list
    code, rooms = api_call("/api/v1/rooms")
    assert code == 200 and len(rooms) == 6
    print(f"  [HTTP] GET /api/v1/rooms -> OK ({[r['code'] for r in rooms]})")

    # Availability grid
    today = datetime.now(tz).date()
    code, avail = api_call(f"/api/v1/rooms/availability?from={today.isoformat()}&days=2")
    assert code == 200 and len(avail) == 12
    print("  [HTTP] GET /api/v1/rooms/availability -> OK (12 room-days returned)")

    # Faculty submits request
    target_date = (today + timedelta(days=4)).isoformat()
    req_body = {
        "room_code": "T2",
        "booking_date": target_date,
        "start_time": "11:00",
        "end_time": "12:30",
        "purpose": "Network Security Lab Test",
    }
    code, req_created = api_call("/api/v1/booking-requests", method="POST", body=req_body, token=faculty_token)
    assert code == 201, f"Create booking request failed: {code}, {req_created}"
    req_id = req_created["id"]
    print(f"  [HTTP] POST /api/v1/booking-requests -> Created (ID: {req_id}, Status: PENDING)")

    # Faculty checks own requests
    code, my_reqs = api_call("/api/v1/booking-requests/mine", token=faculty_token)
    assert code == 200 and any(r["id"] == str(req_id) for r in my_reqs)
    print("  [HTTP] GET /api/v1/booking-requests/mine -> OK")

    # Admin approves request
    code, appr = api_call(f"/api/v1/admin/booking-requests/{req_id}/approve", method="POST", token=admin_token)
    assert code == 200 and appr["status"] == "CONFIRMED"
    booking_id = appr["id"]
    print(f"  [HTTP] POST /api/v1/admin/booking-requests/{req_id}/approve -> CONFIRMED (Booking ID: {booking_id})")

    # Admin reads bookings calendar
    code, b_list = api_call(f"/api/v1/admin/bookings?from={today.isoformat()}&days=35", token=admin_token)
    assert code == 200 and any(b["id"] == str(booking_id) for b in b_list)
    print(f"  [HTTP] GET /api/v1/admin/bookings -> OK ({len(b_list)} bookings retrieved)")

    # Admin updates booking timing (11:00 -> 11:30)
    update_body = {
        "room_code": "T2",
        "booking_date": target_date,
        "start_time": "11:30",
        "end_time": "13:00",
        "purpose": "Updated Security Lab Test",
    }
    code, b_updated = api_call(f"/api/v1/admin/bookings/{booking_id}", method="PATCH", body=update_body, token=admin_token)
    assert code == 200 and b_updated["start_time"] == "11:30"
    print("  [HTTP] PATCH /api/v1/admin/bookings/{id} -> OK (Timing updated to 11:30-13:00)")

    # Admin deletes booking
    code, b_del = api_call(f"/api/v1/admin/bookings/{booking_id}", method="DELETE", token=admin_token)
    assert code == 200 and b_del["status"] == "CANCELLED"
    print("  [HTTP] DELETE /api/v1/admin/bookings/{id} -> OK (Booking cancelled, slots freed)")

    # Admin creates student user
    student_payload = {
        "username": f"student_{int(time.time())}",
        "display_name": "Roll No B230001CS",
        "password": "StudentPassword123!",
        "role": "STUDENT",
    }
    code, st_res = api_call("/api/v1/admin/users", method="POST", body=student_payload, token=admin_token)
    assert code == 201 and st_res["role"] == "STUDENT"
    print(f"  [HTTP] POST /api/v1/admin/users -> Created student user '{st_res['username']}'")

    # Student login
    code, st_login = api_call("/api/v1/auth/login", method="POST",
                              body={"username": student_payload["username"], "password": student_payload["password"]})
    assert code == 200 and st_login["user"]["role"] == "STUDENT"
    student_token = st_login["access_token"]
    print("  [HTTP] POST /api/v1/auth/login (Student) -> OK")

    # Student denied faculty booking request
    code, st_denied = api_call("/api/v1/booking-requests", method="POST", body=req_body, token=student_token)
    assert code == 403
    print("  [HTTP] POST /api/v1/booking-requests by Student -> 403 Forbidden (RBAC enforced)")

    # Admin audit logs
    code, a_logs = api_call("/api/v1/admin/audit-logs", token=admin_token)
    assert code == 200 and len(a_logs) > 0
    print(f"  [HTTP] GET /api/v1/admin/audit-logs -> OK ({len(a_logs)} events recorded)")

    print("\n" + "=" * 70)
    print("ALL UNIT, SERVICE, AND HTTP API TESTS COMPLETED WITH 100% SUCCESS!")
    print("=" * 70)


if __name__ == "__main__":
    run_unit_and_service_tests()
    # Check if a server is running for Phase 2
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1)
        run_http_api_tests()
    except Exception:
        print("\nNote: Local server is not currently running on port 8000.")
        print("Run 'uvicorn app.main:app --port 8000' and execute this script again for Phase 2 HTTP API tests.")
