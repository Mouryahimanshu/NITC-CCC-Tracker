from datetime import date, datetime, timezone

from fastapi import APIRouter, Query, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MailboxState, Room
from app.db.postgres import get_session
from app.schemas.room import RoomResponse
from app.services.booking import list_availability

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("", response_model=list[RoomResponse])
def list_rooms(db: Session = Depends(get_session)):
    rooms = db.scalars(select(Room).where(Room.active.is_(True)).order_by(Room.code)).all()
    return [RoomResponse(id=str(room.id), code=room.code, active=room.active) for room in rooms]


@router.get("/availability", tags=["availability"])
def availability(from_date: date = Query(alias="from"), days: int = Query(default=14, ge=1, le=28),
                 db: Session = Depends(get_session)):
    return list_availability(db, from_date, days)


@router.get("/sync-status", tags=["sync"])
def sync_status(db: Session = Depends(get_session)):
    """Return the last successful mailbox synchronization time and stale warning (REQ-8, NFR-08)."""
    now = datetime.now(timezone.utc)
    state = db.scalar(select(MailboxState).order_by(MailboxState.updated_at.desc()))
    if state is None or state.updated_at is None:
        return {
            "last_sync_time": None,
            "is_stale": True,
            "stale_threshold_minutes": 15,
            "message": "Mailbox synchronization has not occurred yet. Stale-data warning active.",
        }
    last_time = state.updated_at
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    diff_seconds = (now - last_time).total_seconds()
    is_stale = diff_seconds > 15 * 60
    return {
        "last_sync_time": last_time.isoformat(),
        "diff_minutes": round(diff_seconds / 60, 1),
        "is_stale": is_stale,
        "stale_threshold_minutes": 15,
        "message": "Warning: Mailbox synchronization has not succeeded within the last 15 minutes." if is_stale else "Mailbox synchronization is up to date.",
    }
