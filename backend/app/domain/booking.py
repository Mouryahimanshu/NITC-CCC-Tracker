from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.config import get_settings

from pydantic import BaseModel, Field, field_validator, model_validator


class BookingInput(BaseModel):
    room_code: str = Field(pattern=r"^T[1-6]$")
    booking_date: date
    start_time: str = Field(pattern=r"^(0[8-9]|1[0-9]):(00|30)$")
    end_time: str = Field(pattern=r"^((0[8-9]|1[0-9]):(00|30)|20:00)$")
    purpose: str = Field(min_length=3, max_length=500)

    @field_validator("purpose")
    @classmethod
    def normalize_purpose(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def interval_is_valid(self):
        if self.start_time >= self.end_time:
            raise ValueError("End time must be after start time")
        if self.booking_date < datetime.now(ZoneInfo(get_settings().campus_timezone)).date():
            raise ValueError("Booking date cannot be in the past")
        return self

    @property
    def start_minute(self) -> int:
        hour, minute = map(int, self.start_time.split(":"))
        return hour * 60 + minute

    @property
    def end_minute(self) -> int:
        hour, minute = map(int, self.end_time.split(":"))
        return hour * 60 + minute

    @property
    def slot_ids(self) -> list[int]:
        # Store each half-hour slot by its start minute to distinguish these
        # allocations from legacy hourly slot IDs during the granularity change.
        return list(range(self.start_minute, self.end_minute, 30))


class MaintenanceInput(BaseModel):
    room_code: str = Field(pattern=r"^T[1-6]$")
    maintenance_date: date
    start_time: str = Field(pattern=r"^(0[8-9]|1[0-9]):(00|30)$")
    end_time: str = Field(pattern=r"^((0[8-9]|1[0-9]):(00|30)|20:00)$")
    note: str = Field(default="Room maintenance", min_length=3, max_length=500)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def interval_is_valid(self):
        if self.start_time >= self.end_time:
            raise ValueError("Maintenance end time must be after start time")
        if self.maintenance_date < datetime.now(ZoneInfo(get_settings().campus_timezone)).date():
            raise ValueError("Maintenance date cannot be in the past")
        return self

    @property
    def start_minute(self) -> int:
        hour, minute = map(int, self.start_time.split(":"))
        return hour * 60 + minute

    @property
    def end_minute(self) -> int:
        hour, minute = map(int, self.end_time.split(":"))
        return hour * 60 + minute
