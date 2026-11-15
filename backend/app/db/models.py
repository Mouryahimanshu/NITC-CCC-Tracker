"""Relational schema for users, rooms, bookings, mail processing, and audit."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(2), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RoomMaintenance(Base):
    __tablename__ = "room_maintenance"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    room_code: Mapped[str] = mapped_column(String(2))
    maintenance_date: Mapped[date] = mapped_column(Date, index=True)
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    note: Mapped[str] = mapped_column(String(500), default="Room maintenance")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    room_code: Mapped[str] = mapped_column(String(2))
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    purpose: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="CONFIRMED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BookingRequest(Base):
    __tablename__ = "booking_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    room_code: Mapped[str] = mapped_column(String(2))
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resulting_booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SlotAllocation(Base):
    __tablename__ = "slot_allocations"
    __table_args__ = (UniqueConstraint("room_id", "booking_date", "slot_id", name="uq_room_date_slot"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    booking_date: Mapped[date] = mapped_column(Date)
    slot_id: Mapped[int] = mapped_column(Integer)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)


class EmailLog(Base):
    __tablename__ = "email_logs"
    __table_args__ = (
        UniqueConstraint("mailbox_key", "uid_validity", "imap_uid", name="uq_mailbox_uid"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    mailbox_key: Mapped[str] = mapped_column(String(320))
    uid_validity: Mapped[str] = mapped_column(String(64))
    imap_uid: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    sender: Mapped[str] = mapped_column(String(500), default="")
    subject: Mapped[str] = mapped_column(String(998), default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    parsed_room: Mapped[str | None] = mapped_column(String(2), nullable=True)
    parsed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    parsed_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    parsed_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    parsed_purpose: Mapped[str | None] = mapped_column(String(500), nullable=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class MailboxState(Base):
    __tablename__ = "mailbox_state"
    mailbox_key: Mapped[str] = mapped_column(String(320), primary_key=True)
    uid_validity: Mapped[str] = mapped_column(String(64))
    last_uid: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
