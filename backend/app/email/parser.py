"""Deterministic extraction and validation for CCC booking emails."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from email.message import Message
from html.parser import HTMLParser

from app.domain.booking import BookingInput


class _HTMLText(HTMLParser):
    """Convert HTML email bodies into line-oriented text without external packages."""

    BLOCK_TAGS = {"address", "article", "br", "div", "li", "p", "tr", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str):
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


@dataclass(frozen=True)
class BookingEmailFields:
    """Safe extracted values; raw message bodies are never persisted."""

    room_code: str | None = None
    date_text: str | None = None
    start_text: str | None = None
    end_text: str | None = None
    purpose: str | None = None

    @staticmethod
    def _clean(value: str | None, limit: int = 500) -> str | None:
        if not value:
            return None
        return " ".join(value.split()).strip()[:limit] or None

    @property
    def parsed_date(self) -> date | None:
        if not self.date_text:
            return None
        try:
            return parse_date(self.date_text)
        except ValueError:
            return None


def extract_text(message: Message) -> str:
    """Extract MIME text/plain or text/html bodies, ignoring attachments."""
    parts = message.walk() if message.is_multipart() else [message]
    texts = []
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        raw = part.get_payload(decode=True)
        if raw is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = raw.decode(charset, errors="replace")
        if content_type == "text/html":
            parser = _HTMLText()
            parser.feed(decoded)
            decoded = "".join(parser.parts)
        texts.append(decoded)
    return "\n".join(texts)


def _find(pattern: str, body: str, flags=re.IGNORECASE | re.MULTILINE) -> str | None:
    match = re.search(pattern, body, flags)
    return match.group(1).strip() if match else None


def extract_booking_fields(body: str) -> BookingEmailFields:
    """Extract recognized CCC fields while leaving domain validation separate."""
    if not body or not body.strip():
        return BookingEmailFields()

    room = _find(r"^\s*(?:room|terminal)(?:\s+room)?\s*[:=-]\s*(T[1-6])\b", body)
    if not room:
        room = _find(r"\bTerminal\s+Room\s+(T[1-6])\b", body)
    if not room:
        room = _find(r"\b(T[1-6])\s+terminal\s+room\b", body)
    if not room:
        required = _find(r"^\s*Required\s*:\s*(?:CCC\s+)?Terminal\s*([1-6])\b", body)
        room = f"T{required}" if required else None

    date_text = _find(r"^\s*(?:booking\s+)?date\s*[:=-]\s*([^\r\n]+)", body)
    start_text = _find(r"^\s*(?:start(?:\s+time)?|from)\s*[:=-]\s*([^\r\n]+)", body)
    end_text = _find(r"^\s*(?:end(?:\s+time)?|to)\s*[:=-]\s*([^\r\n]+)", body)

    # CCC bulletin format: "Time: 08:00 PM to 10:30 PM".
    time_range = re.search(
        r"^\s*Time\s*:\s*(\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)\s*(?:to|[-–—])\s*"
        r"(\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)",
        body, re.IGNORECASE | re.MULTILINE,
    )
    if time_range:
        start_text, end_text = time_range.group(1).strip(), time_range.group(2).strip()

    purpose = _find(r"^\s*purpose\s*[:=-]\s*([^\r\n]+)", body)
    if not purpose:
        narrative = re.search(
            r"has been reserved\s+for\s+(.+?)(?:\s+as per the following schedule)?\s*:",
            body, re.IGNORECASE | re.DOTALL,
        )
        if narrative:
            purpose = " ".join(narrative.group(1).split()).strip(" .")
    if not purpose:
        purpose = _find(r"^\s*Required\s*:\s*([^\r\n]+)", body)

    fields = BookingEmailFields(
        room_code=room.upper() if room else None,
        date_text=date_text,
        start_text=start_text,
        end_text=end_text,
        purpose=purpose,
    )
    return BookingEmailFields(
        room_code=fields._clean(fields.room_code, 2),
        date_text=fields._clean(fields.date_text, 100),
        start_text=fields._clean(fields.start_text, 40),
        end_text=fields._clean(fields.end_text, 40),
        purpose=fields._clean(fields.purpose, 500),
    )


def parse_date(value: str) -> date:
    """Parse ISO and common CCC date formats, including optional weekday labels."""
    cleaned = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", value.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned).strip().rstrip(".,")
    cleaned = re.sub(r"\s+", " ", cleaned)
    formats = (
        "%Y-%m-%d", "%Y/%m/%d", "%d %B %Y", "%d %b %Y",
        "%d %B, %Y", "%d %b, %Y", "%d/%m/%Y", "%d-%m-%Y",
        "%m/%d/%Y", "%d/%m/%y", "%d-%m-%y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported booking date: {value.strip()}")


def _time_to_minutes(value: str) -> int:
    cleaned = re.sub(r"(?i)(a|p)\.?m\.?", lambda m: " AM" if m.group(1).lower() == "a" else " PM", value)
    cleaned = cleaned.strip().upper().replace(".", ":")
    cleaned = re.sub(r"\s+", " ", cleaned)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?", cleaned)
    if not match:
        raise ValueError(f"Unsupported time format: {value.strip()}")
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if minute not in {0, 30}:
        raise ValueError("Booking time minutes must be 00 or 30")
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError(f"Invalid 12-hour time: {value.strip()}")
        hour = hour % 12 + (12 if meridiem == "PM" else 0)
    elif hour > 23 or (hour == 24 and minute != 0):
        raise ValueError(f"Invalid 24-hour time: {value.strip()}")
    if hour == 24 and not meridiem:
        raise ValueError(f"Invalid 24-hour time: {value.strip()}")
    return hour * 60 + minute


def validate_booking_fields(fields: BookingEmailFields) -> BookingInput:
    """Validate extracted fields against 30-minute IST booking boundaries."""
    if not fields.room_code:
        raise ValueError("Room could not be extracted")
    if not re.fullmatch(r"T[1-6]", fields.room_code):
        raise ValueError("Room must be one of T1–T6")
    if not fields.date_text:
        raise ValueError("Booking date is missing")
    if not fields.start_text:
        raise ValueError("Start time is missing")
    if not fields.end_text:
        raise ValueError("End time is missing")
    booking_date = parse_date(fields.date_text)
    start_minute = _time_to_minutes(fields.start_text)
    end_minute = _time_to_minutes(fields.end_text)
    if start_minute < 8 * 60 or end_minute > 20 * 60:
        raise ValueError("Booking is outside operating hours (08:00–20:00 IST)")
    if start_minute % 30 or end_minute % 30:
        raise ValueError("Booking times must align to 30-minute boundaries")
    if end_minute <= start_minute:
        raise ValueError("End time must be after start time")
    raw_purpose = (fields.purpose or "").strip()
    purpose = raw_purpose if len(raw_purpose) >= 3 else "CCC room reservation"
    return BookingInput(
        room_code=fields.room_code,
        booking_date=booking_date,
        start_time=f"{start_minute // 60:02d}:{start_minute % 60:02d}",
        end_time=f"{end_minute // 60:02d}:{end_minute % 60:02d}",
        purpose=purpose[:500],
    )


def parse_booking(body: str) -> BookingInput:
    """Compatibility helper: extract and validate one email as a confirmed booking."""
    return validate_booking_fields(extract_booking_fields(body))
