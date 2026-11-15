"""Seed clearly labeled future bookings for local UI/demo verification.

Safe to re-run: records are identified by deterministic DEMO source IDs. The
normal booking allocator enforces overlap, maintenance, and half-hour slots.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.models import Booking, User
from app.db.postgres import dispose_database, initialize_database, session_scope
from app.domain.booking import BookingInput
from app.services.booking import _claim_booking, _audit


# (room, day_offset_from_today, start_time, end_time, purpose)
DEMO_TEMPLATES = [
    ("T1", 0, "09:00", "10:00", "DEMO: CCC terminal availability sample"),
    ("T2", 0, "10:30", "12:30", "DEMO: Online assessment sample booking"),
    ("T3", 1, "13:00", "14:30", "DEMO: Faculty lab session sample"),
    ("T4", 3, "16:00", "17:00", "DEMO: Training session sample"),
    ("T5", 4, "11:30", "13:00", "DEMO: CCC terminal availability sample"),
    ("T6", 7, "08:30", "10:00", "DEMO: Online assessment sample booking"),
]


def main():
    initialize_database()
    created, skipped = [], []
    today = datetime.now(ZoneInfo(get_settings().campus_timezone)).date()
    try:
        with session_scope() as db:
            admin = db.scalar(select(User).where(User.role == "ADMIN", User.active.is_(True)).order_by(User.id))
            if admin is None:
                raise SystemExit("No active administrator exists; run scripts.bootstrap first.")
            for room, day_offset, start, end, purpose in DEMO_TEMPLATES:
                booking_date = today + timedelta(days=day_offset)
                iso_date = booking_date.isoformat()
                source_id = f"demo-{iso_date}-{room}-{start.replace(':', '')}"
                existing = db.scalar(select(Booking.id).where(Booking.source == "DEMO",
                                                             Booking.source_id == source_id))
                if existing is not None:
                    skipped.append(f"{room} {iso_date} {start}–{end} (already seeded)")
                    continue
                try:
                    payload = BookingInput(room_code=room, booking_date=booking_date,
                                           start_time=start, end_time=end, purpose=purpose)
                    booking = _claim_booking(db, payload, str(admin.id), "DEMO", source_id)
                    _audit(db, admin.id, "DEMO_BOOKING_SEEDED", "booking", booking.id,
                           {"room_code": room, "booking_date": iso_date,
                            "start_time": start, "end_time": end, "demo": True})
                    db.commit()
                    created.append(f"{room} {iso_date} {start}–{end}")
                except (HTTPException, ValueError) as error:
                    db.rollback()
                    skipped.append(f"{room} {iso_date} {start}–{end} (conflict: {getattr(error, 'detail', str(error))})")
                except IntegrityError:
                    db.rollback()
                    skipped.append(f"{room} {iso_date} {start}–{end} (slot conflict)")
        print(f"Created {len(created)} demo bookings; skipped {len(skipped)}.")
        for item in created:
            print(f"  + {item}")
        for item in skipped:
            print(f"  - {item}")
    finally:
        dispose_database()


if __name__ == "__main__":
    main()
