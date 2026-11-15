"""Relational booking lifecycle and transaction-backed half-hour allocation."""

import json
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Booking, BookingRequest, EmailLog, Room, RoomMaintenance, SlotAllocation, User
from app.domain.booking import BookingInput, MaintenanceInput


def _supports_for_update(db: Session) -> bool:
    """SQLite does not support SELECT ... FOR UPDATE; PostgreSQL does."""
    return "sqlite" not in str(db.bind.dialect.name if db.bind else "sqlite")


def _for_update(query, db: Session):
    """Apply with_for_update() only on databases that support it."""
    if _supports_for_update(db):
        return query.with_for_update()
    return query


def _room(db: Session, code: str) -> Room:
    room = db.scalar(_for_update(select(Room).where(Room.code == code, Room.active.is_(True)), db))
    if room is None:
        raise HTTPException(422, "Unknown or inactive room")
    return room


def _ensure_not_under_maintenance(db: Session, room_id: int, booking_date: date,
                                  start_minute: int, end_minute: int) -> None:
    maintenance = db.scalar(select(RoomMaintenance.id).where(
        RoomMaintenance.room_id == room_id,
        RoomMaintenance.maintenance_date == booking_date,
        RoomMaintenance.active.is_(True),
        RoomMaintenance.start_minute < end_minute,
        RoomMaintenance.end_minute > start_minute,
    ).limit(1))
    if maintenance is not None:
        raise HTTPException(409, "The room is under maintenance during the requested time")


def _ensure_request_time_available(db: Session, room_id: int, booking_date: date,
                                   start_minute: int, end_minute: int,
                                   exclude_request_id: int | None = None) -> None:
    _ensure_not_under_maintenance(db, room_id, booking_date, start_minute, end_minute)
    booking = db.scalar(select(Booking.id).where(
        Booking.room_id == room_id, Booking.booking_date == booking_date,
        Booking.status == "CONFIRMED", Booking.start_minute < end_minute,
        Booking.end_minute > start_minute,
    ).limit(1))
    if booking is not None:
        raise HTTPException(409, "The requested time overlaps an existing confirmed booking")
    pending_query = select(BookingRequest.id).where(
        BookingRequest.room_id == room_id, BookingRequest.booking_date == booking_date,
        BookingRequest.status == "PENDING", BookingRequest.start_minute < end_minute,
        BookingRequest.end_minute > start_minute,
    )
    if exclude_request_id is not None:
        pending_query = pending_query.where(BookingRequest.id != exclude_request_id)
    if db.scalar(pending_query.limit(1)) is not None:
        raise HTTPException(409, "The requested time overlaps another pending faculty request")


def _audit(db: Session, actor_id, action, entity_type, entity_id, details=None):
    db.add(AuditLog(actor_user_id=actor_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id), details=json.dumps(details or {})))


def _claim_booking(db: Session, request: BookingInput, creator_id: str, source: str,
                   source_id: str | None = None) -> Booking:
    room = _room(db, request.room_code)
    _ensure_not_under_maintenance(db, room.id, request.booking_date,
                                  request.start_minute, request.end_minute)
    overlap = db.scalar(select(Booking.id).where(
        Booking.room_id == room.id,
        Booking.booking_date == request.booking_date,
        Booking.status == "CONFIRMED",
        Booking.start_minute < request.end_minute,
        Booking.end_minute > request.start_minute,
    ).limit(1))
    if overlap is not None:
        raise HTTPException(409, "The requested time overlaps an existing confirmed booking")
    booking = Booking(
        room_id=room.id, room_code=room.code, booking_date=request.booking_date,
        start_minute=request.start_minute, end_minute=request.end_minute,
        start_time=request.start_time, end_time=request.end_time, purpose=request.purpose,
        source=source, source_id=str(source_id) if source_id is not None else None,
        created_by=creator_id, status="CONFIRMED",
    )
    db.add(booking)
    db.flush()
    db.add_all([SlotAllocation(room_id=room.id, booking_date=request.booking_date,
                               slot_id=slot, booking_id=booking.id) for slot in request.slot_ids])
    db.flush()  # the unique constraint detects concurrent allocations
    return booking


def create_request(db: Session, payload: BookingInput, faculty):
    room = _room(db, payload.room_code)
    _ensure_request_time_available(db, room.id, payload.booking_date,
                                   payload.start_minute, payload.end_minute)
    try:
        request = BookingRequest(
            faculty_user_id=faculty.id, room_id=room.id, room_code=room.code,
            booking_date=payload.booking_date, start_time=payload.start_time, end_time=payload.end_time,
            start_minute=payload.start_minute, end_minute=payload.end_minute,
            purpose=payload.purpose, status="PENDING",
        )
        db.add(request)
        db.commit()
        db.refresh(request)
        return request
    except Exception:
        db.rollback()
        raise


def decide_request(db: Session, request_id: int, admin, approve: bool, note: str = ""):
    request = db.scalar(_for_update(select(BookingRequest).where(BookingRequest.id == request_id), db))
    if request is None:
        raise HTTPException(404, "Request not found")
    if request.status != "PENDING":
        raise HTTPException(409, "Request has already been reviewed")
    note = " ".join(note.split())
    if not approve and len(note) < 3:
        raise HTTPException(422, "A rejection reason of at least 3 characters is required")
    if len(note) > 500:
        raise HTTPException(422, "Rejection reason must be 500 characters or fewer")
    now = datetime.now(timezone.utc)
    try:
        if approve:
            booking_input = BookingInput(room_code=request.room_code, booking_date=request.booking_date,
                start_time=request.start_time, end_time=request.end_time, purpose=request.purpose)
            room = _room(db, request.room_code)
            _ensure_request_time_available(db, room.id, request.booking_date,
                request.start_minute, request.end_minute, exclude_request_id=request.id)
            booking = _claim_booking(db, booking_input, str(admin.id), "FACULTY_REQUEST", str(request.id))
            request.resulting_booking_id = booking.id
            action = "REQUEST_APPROVED"
        else:
            booking = None
            action = "REQUEST_REJECTED"
        request.status = "APPROVED" if approve else "REJECTED"
        request.reviewed_by = admin.id
        request.reviewed_at = now
        request.decision_note = note[:500]
        request.updated_at = now
        _audit(db, admin.id, action, "booking_request", request.id,
               {"decision_note": note} if note else {})
        db.commit()
        if booking:
            db.refresh(booking)
            return booking
        return {"status": "REJECTED", "id": str(request.id)}
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "One or more selected half-hour slots are already booked") from None
    except Exception:
        db.rollback()
        raise


def _remove_confirmed_booking(db: Session, booking_id: int, admin, audit_action: str,
                              reason: str = "Cancelled by CCC administrator"):
    booking = db.scalar(_for_update(select(Booking).where(Booking.id == booking_id), db))
    if booking is None or booking.status != "CONFIRMED":
        raise HTTPException(404, "Confirmed booking not found")
    now = datetime.now(timezone.utc)
    booking.status = "CANCELLED"
    booking.cancelled_by = admin.id
    booking.cancelled_at = now
    booking.updated_at = now
    db.execute(delete(SlotAllocation).where(SlotAllocation.booking_id == booking.id))
    _audit(db, admin.id, audit_action, "booking", booking.id,
           {"room_code": booking.room_code, "booking_date": booking.booking_date.isoformat(),
            "start_time": booking.start_time, "end_time": booking.end_time, "reason": reason})
    db.commit()
    return {"id": str(booking_id), "status": "CANCELLED", "action": audit_action, "reason": reason}


def cancel_booking(db: Session, booking_id: int, admin, reason: str = "Cancelled by CCC administrator"):
    return _remove_confirmed_booking(db, booking_id, admin, "BOOKING_CANCELLED", reason)


def delete_confirmed_booking(db: Session, booking_id: int, admin, reason: str = "Deleted by CCC administrator"):
    """Remove a confirmed booking from the active schedule and retain its audit history."""
    return _remove_confirmed_booking(db, booking_id, admin, "BOOKING_DELETED", reason)


def update_confirmed_booking(db: Session, booking_id: int, payload: BookingInput, admin):
    booking = db.scalar(_for_update(select(Booking).where(Booking.id == booking_id), db))
    if booking is None or booking.status != "CONFIRMED":
        raise HTTPException(404, "Confirmed booking not found")
    room = _room(db, booking.room_code)
    if payload.room_code != booking.room_code or payload.booking_date != booking.booking_date:
        raise HTTPException(422, "Editing a booking can change its time only; room and date are fixed")
    _ensure_not_under_maintenance(db, room.id, booking.booking_date,
                                  payload.start_minute, payload.end_minute)
    overlap = db.scalar(select(Booking.id).where(
        Booking.room_id == room.id, Booking.booking_date == booking.booking_date,
        Booking.status == "CONFIRMED", Booking.id != booking.id,
        Booking.start_minute < payload.end_minute, Booking.end_minute > payload.start_minute,
    ).limit(1))
    if overlap is not None:
        raise HTTPException(409, "The new time overlaps another confirmed booking")
    pending = db.scalar(select(BookingRequest.id).where(
        BookingRequest.room_id == room.id, BookingRequest.booking_date == booking.booking_date,
        BookingRequest.status == "PENDING", BookingRequest.start_minute < payload.end_minute,
        BookingRequest.end_minute > payload.start_minute,
    ).limit(1))
    if pending is not None:
        raise HTTPException(409, "The new time overlaps a pending faculty request")
    old = {"start_time": booking.start_time, "end_time": booking.end_time}
    db.execute(delete(SlotAllocation).where(SlotAllocation.booking_id == booking.id))
    booking.start_minute = payload.start_minute
    booking.end_minute = payload.end_minute
    booking.start_time = payload.start_time
    booking.end_time = payload.end_time
    booking.purpose = payload.purpose
    booking.updated_at = datetime.now(timezone.utc)
    try:
        db.add_all([SlotAllocation(room_id=room.id, booking_date=booking.booking_date,
                                   slot_id=slot, booking_id=booking.id) for slot in payload.slot_ids])
        db.flush()
        _audit(db, admin.id, "BOOKING_TIME_UPDATED", "booking", booking.id,
               {"room_code": booking.room_code, "booking_date": booking.booking_date.isoformat(),
                "previous": old, "updated": {"start_time": booking.start_time,
                                             "end_time": booking.end_time}})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "One or more selected half-hour slots are already allocated") from None
    except Exception:
        db.rollback()
        raise
    return {"id": str(booking.id), "status": booking.status,
            "start_time": booking.start_time, "end_time": booking.end_time}


def create_room_maintenance(db: Session, payload: MaintenanceInput, admin: User) -> RoomMaintenance:
    room = _room(db, payload.room_code)
    overlapping_bookings = db.scalars(_for_update(select(Booking).where(
        Booking.room_id == room.id,
        Booking.booking_date == payload.maintenance_date,
        Booking.status == "CONFIRMED",
        Booking.start_minute < payload.end_minute,
        Booking.end_minute > payload.start_minute,
    ), db)).all()
    existing = db.scalar(select(RoomMaintenance.id).where(
        RoomMaintenance.room_id == room.id,
        RoomMaintenance.maintenance_date == payload.maintenance_date,
        RoomMaintenance.active.is_(True),
        RoomMaintenance.start_minute < payload.end_minute,
        RoomMaintenance.end_minute > payload.start_minute,
    ).limit(1))
    if existing is not None:
        raise HTTPException(409, "Maintenance overlaps an existing maintenance window")
    overlapping_requests = db.scalars(_for_update(select(BookingRequest).where(
        BookingRequest.room_id == room.id,
        BookingRequest.booking_date == payload.maintenance_date,
        BookingRequest.status == "PENDING",
        BookingRequest.start_minute < payload.end_minute,
        BookingRequest.end_minute > payload.start_minute,
    ), db)).all()
    now = datetime.now(timezone.utc)
    for booking in overlapping_bookings:
        booking.status = "CANCELLED"
        booking.cancelled_by = admin.id
        booking.cancelled_at = now
        booking.updated_at = now
        db.execute(delete(SlotAllocation).where(SlotAllocation.booking_id == booking.id))
        _audit(db, admin.id, "BOOKING_CANCELLED_FOR_MAINTENANCE", "booking", booking.id,
               {"room_code": room.code, "booking_date": payload.maintenance_date.isoformat(),
                "start_time": booking.start_time, "end_time": booking.end_time,
                "maintenance_start": payload.start_time, "maintenance_end": payload.end_time})
    rejection_reason = f"Automatically rejected because {room.code} was scheduled for maintenance from {payload.start_time} to {payload.end_time}."
    for request in overlapping_requests:
        request.status = "REJECTED"
        request.reviewed_by = admin.id
        request.reviewed_at = now
        request.updated_at = now
        request.decision_note = rejection_reason[:500]
        _audit(db, admin.id, "REQUEST_REJECTED_FOR_MAINTENANCE", "booking_request", request.id,
               {"decision_note": request.decision_note, "room_code": room.code,
                "booking_date": payload.maintenance_date.isoformat()})
    entry = RoomMaintenance(
        room_id=room.id, room_code=room.code, maintenance_date=payload.maintenance_date,
        start_minute=payload.start_minute, end_minute=payload.end_minute,
        start_time=payload.start_time, end_time=payload.end_time,
        note=payload.note, created_by=admin.id, active=True,
    )
    db.add(entry)
    db.flush()
    _audit(db, admin.id, "ROOM_MAINTENANCE_CREATED", "room_maintenance", entry.id,
           {"room_code": room.code, "date": payload.maintenance_date.isoformat(),
            "start": payload.start_time, "end": payload.end_time,
            "cancelled_booking_ids": [str(row.id) for row in overlapping_bookings],
            "rejected_request_ids": [str(row.id) for row in overlapping_requests]})
    db.commit()
    db.refresh(entry)
    entry.cancelled_bookings_count = len(overlapping_bookings)
    entry.rejected_requests_count = len(overlapping_requests)
    return entry


def clear_room_maintenance(db: Session, maintenance_id: int, admin: User):
    entry = db.scalar(_for_update(select(RoomMaintenance).where(RoomMaintenance.id == maintenance_id), db))
    if entry is None or not entry.active:
        raise HTTPException(404, "Active maintenance window not found")
    entry.active = False
    _audit(db, admin.id, "ROOM_MAINTENANCE_CLEARED", "room_maintenance", entry.id,
           {"room_code": entry.room_code, "date": entry.maintenance_date.isoformat()})
    db.commit()
    return {"id": str(entry.id), "status": "CLEARED"}


def list_availability(db: Session, start_date: date, days: int = 14):
    rooms = db.scalars(select(Room).where(Room.active.is_(True)).order_by(Room.code)).all()
    end_date = start_date + timedelta(days=days - 1)
    bookings = db.scalars(select(Booking).where(
        Booking.booking_date >= start_date, Booking.booking_date <= end_date,
        Booking.status == "CONFIRMED")).all()
    maintenance_entries = db.scalars(select(RoomMaintenance).where(
        RoomMaintenance.maintenance_date >= start_date,
        RoomMaintenance.maintenance_date <= end_date,
        RoomMaintenance.active.is_(True))).all()
    pending_requests = db.scalars(select(BookingRequest).where(
        BookingRequest.booking_date >= start_date, BookingRequest.booking_date <= end_date,
        BookingRequest.status == "PENDING")).all()
    by_room_date: dict[tuple[str, date], list[Booking]] = {}
    for booking in bookings:
        by_room_date.setdefault((booking.room_code, booking.booking_date), []).append(booking)
    maintenance_by_room_date: dict[tuple[str, date], list[RoomMaintenance]] = {}
    for entry in maintenance_entries:
        maintenance_by_room_date.setdefault((entry.room_code, entry.maintenance_date), []).append(entry)
    pending_by_room_date: dict[tuple[str, date], list[BookingRequest]] = {}
    for request in pending_requests:
        pending_by_room_date.setdefault((request.room_code, request.booking_date), []).append(request)
    result = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        for room in rooms:
            entries = sorted(by_room_date.get((room.code, day), []), key=lambda row: row.start_minute)
            maintenance = sorted(maintenance_by_room_date.get((room.code, day), []), key=lambda row: row.start_minute)
            pending = sorted(pending_by_room_date.get((room.code, day), []), key=lambda row: row.start_minute)
            occupied = {slot for row in entries for slot in range(row.start_minute, row.end_minute, 30)}
            maintained = {slot for row in maintenance for slot in range(row.start_minute, row.end_minute, 30)}
            pending_slots = {slot for row in pending for slot in range(row.start_minute, row.end_minute, 30)}
            result.append({"date": day.isoformat(), "room_code": room.code,
                "slots": [{"start": f"{minute // 60:02d}:{minute % 60:02d}",
                           "end": f"{(minute + 30) // 60:02d}:{(minute + 30) % 60:02d}",
                           "status": "BOOKED" if minute in occupied else
                                    "MAINTENANCE" if minute in maintained else
                                    "PENDING" if minute in pending_slots else "AVAILABLE"}
                          for minute in range(8 * 60, 20 * 60, 30)],
                "bookings": [{"id": str(row.id), "start": row.start_time, "end": row.end_time} for row in entries],
                "maintenance": [{"id": str(row.id), "start": row.start_time, "end": row.end_time}
                                for row in maintenance],
                "pending_requests": [{"id": str(row.id), "start": row.start_time, "end": row.end_time}
                                     for row in pending]})
    return result
