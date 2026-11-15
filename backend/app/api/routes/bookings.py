import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.models import AuditLog, Booking, BookingRequest, EmailLog, RoomMaintenance, User
from app.db.postgres import get_session
from app.domain.booking import BookingInput, MaintenanceInput
from app.domain.roles import UserRole
from app.services.auth import hash_password
from app.services.booking import (cancel_booking, clear_room_maintenance, create_request,
                                  create_room_maintenance, decide_request, delete_confirmed_booking,
                                  update_confirmed_booking)

router = APIRouter(tags=["booking requests", "admin bookings"])


@router.get("/admin/bookings")
def admin_bookings(from_date: date = Query(alias="from"), days: int = Query(default=42, ge=1, le=62),
                   _: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_session)):
    until = from_date + timedelta(days=days - 1)
    rows = db.scalars(select(Booking).where(
        Booking.status == "CONFIRMED", Booking.booking_date >= from_date,
        Booking.booking_date <= until,
    ).order_by(Booking.booking_date, Booking.room_code, Booking.start_minute)).all()
    return [{"id": str(row.id), "room_code": row.room_code,
        "booking_date": row.booking_date.isoformat(), "start_time": row.start_time,
        "end_time": row.end_time, "purpose": row.purpose, "source": row.source}
        for row in rows]


def _public_request(row: BookingRequest) -> dict:
    return {"id": str(row.id), "room_code": row.room_code,
        "booking_date": row.booking_date.isoformat(), "start_time": row.start_time, "end_time": row.end_time,
        "purpose": row.purpose, "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decision_note": row.decision_note}


@router.post("/booking-requests", status_code=201)
def submit_request(payload: BookingInput, faculty: User = Depends(require_roles(UserRole.FACULTY)),
                   db: Session = Depends(get_session)):
    return _public_request(create_request(db, payload, faculty))


@router.get("/booking-requests/mine")
def my_requests(faculty: User = Depends(require_roles(UserRole.FACULTY)), db: Session = Depends(get_session)):
    rows = db.scalars(select(BookingRequest).where(BookingRequest.faculty_user_id == faculty.id)
                      .order_by(BookingRequest.created_at.desc())).all()
    return [_public_request(row) for row in rows]


@router.get("/admin/booking-requests")
def admin_requests(status: str = Query(default="PENDING", pattern="^(PENDING|APPROVED|REJECTED|CANCELLED)$"),
                   _: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_session)):
    rows = db.scalars(select(BookingRequest).where(BookingRequest.status == status)
                      .order_by(BookingRequest.created_at).limit(200)).all()
    return [{**_public_request(row), "faculty_user_id": str(row.faculty_user_id)} for row in rows]


@router.post("/admin/booking-requests/{request_id}/approve")
def approve_request(request_id: int, admin: User = Depends(require_roles(UserRole.ADMIN)),
                    db: Session = Depends(get_session)):
    booking = decide_request(db, request_id, admin, True)
    return {"id": str(booking.id), "status": booking.status}


@router.post("/admin/booking-requests/{request_id}/reject")
def reject_request(request_id: int, payload: dict | None = None,
                   admin: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_session)):
    note = str((payload or {}).get("note", ""))[:500]
    return decide_request(db, request_id, admin, False, note)


@router.post("/admin/bookings/{booking_id}/cancel")
def cancel(booking_id: int, payload: dict | None = None,
           admin: User = Depends(require_roles(UserRole.ADMIN)),
           db: Session = Depends(get_session)):
    reason = str((payload or {}).get("reason", "Cancelled by CCC administrator")).strip()[:500]
    return cancel_booking(db, booking_id, admin, reason)


@router.delete("/admin/bookings/{booking_id}")
def delete_booking(booking_id: int, payload: dict | None = None,
                   admin: User = Depends(require_roles(UserRole.ADMIN)),
                   db: Session = Depends(get_session)):
    reason = str((payload or {}).get("reason", "Deleted by CCC administrator")).strip()[:500]
    return delete_confirmed_booking(db, booking_id, admin, reason)


@router.patch("/admin/bookings/{booking_id}")
def update_booking(booking_id: int, payload: BookingInput,
                   admin: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_session)):
    return update_confirmed_booking(db, booking_id, payload, admin)


def _maintenance_response(row: RoomMaintenance) -> dict:
    return {"id": str(row.id), "room_code": row.room_code,
        "maintenance_date": row.maintenance_date.isoformat(), "start_time": row.start_time,
        "end_time": row.end_time, "note": row.note, "active": row.active}


@router.get("/admin/room-maintenance")
def room_maintenance(from_date: date = Query(alias="from"), days: int = Query(default=28, ge=1, le=28),
                     _: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_session)):
    until = from_date + timedelta(days=days - 1)
    rows = db.scalars(select(RoomMaintenance).where(
        RoomMaintenance.active.is_(True),
        RoomMaintenance.maintenance_date >= from_date,
        RoomMaintenance.maintenance_date <= until,
    ).order_by(RoomMaintenance.maintenance_date, RoomMaintenance.room_code, RoomMaintenance.start_minute)).all()
    return [_maintenance_response(row) for row in rows]


@router.post("/admin/room-maintenance", status_code=201)
def add_room_maintenance(payload: MaintenanceInput, admin: User = Depends(require_roles(UserRole.ADMIN)),
                         db: Session = Depends(get_session)):
    entry = create_room_maintenance(db, payload, admin)
    return {**_maintenance_response(entry),
        "cancelled_bookings": getattr(entry, "cancelled_bookings_count", 0),
        "rejected_requests": getattr(entry, "rejected_requests_count", 0)}


@router.post("/admin/room-maintenance/{maintenance_id}/clear")
def clear_maintenance(maintenance_id: int, admin: User = Depends(require_roles(UserRole.ADMIN)),
                      db: Session = Depends(get_session)):
    return clear_room_maintenance(db, maintenance_id, admin)


@router.post("/admin/users", status_code=201)
def create_user(payload: dict, admin: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_session)):
    username = str(payload.get("username", "")).strip().lower()
    display_name = str(payload.get("display_name", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", ""))
    if len(username) < 3 or len(username) > 80 or len(password) < 12 or not display_name:
        raise HTTPException(422, "Provide username, display name, and password (at least 12 characters)")
    if role not in {"STUDENT", "FACULTY", "ADMIN"}:
        raise HTTPException(422, "Invalid role")
    user = User(username=username, display_name=display_name, password_hash=hash_password(password),
                role=role, active=True)
    db.add(user)
    try:
        db.flush()
        db.add(AuditLog(actor_user_id=admin.id, action="USER_CREATED", entity_type="user",
                        entity_id=str(user.id), details=json.dumps({"role": role})))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists") from None
    return {"id": str(user.id), "username": username, "display_name": display_name, "role": role}


@router.get("/admin/email-logs")
def email_logs(status: str | None = None, _: User = Depends(require_roles(UserRole.ADMIN)),
               db: Session = Depends(get_session)):
    query = select(EmailLog)
    if status:
        query = query.where(EmailLog.status == status)
    rows = db.scalars(query.order_by(EmailLog.received_at.desc()).limit(200)).all()
    return [{"id": str(row.id), "sender": row.sender, "subject": row.subject,
        "received_at": row.received_at.isoformat() if row.received_at else None, "status": row.status,
        "error": row.error_detail,
        "parsed": {"room_code": row.parsed_room, "booking_date": row.parsed_date.isoformat() if row.parsed_date else None,
                   "start_time": row.parsed_start, "end_time": row.parsed_end, "purpose": row.parsed_purpose}
                  if any((row.parsed_room, row.parsed_date, row.parsed_start, row.parsed_end, row.parsed_purpose)) else None}
        for row in rows]


@router.get("/admin/audit-logs")
def audit_logs(_: User = Depends(require_roles(UserRole.ADMIN)), db: Session = Depends(get_session)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
    return [{"id": str(row.id), "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "action": row.action, "entity_type": row.entity_type, "entity_id": row.entity_id,
        "details": json.loads(row.details or "{}"), "created_at": row.created_at.isoformat()} for row in rows]
