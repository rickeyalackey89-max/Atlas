"""Shared date normalization for MLB slate-based source artifacts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment]


def local_slate_date(value: Any, *, fallback: str = "") -> str:
    """Return the Central-time MLB slate date for a UTC/source timestamp."""

    text = str(value or "").strip()
    if not text:
        return fallback
    parsed_text = text.replace(" ", "T")
    if parsed_text.endswith("Z"):
        parsed_text = parsed_text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(parsed_text)
    except ValueError:
        return text[:10] or fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    central = ZoneInfo("America/Chicago") if ZoneInfo else timezone(timedelta(hours=-5))
    return parsed.astimezone(central).date().isoformat()
