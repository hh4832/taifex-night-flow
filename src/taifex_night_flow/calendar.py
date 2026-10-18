from __future__ import annotations
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

class CalendarUnavailable(RuntimeError):
    pass

def expected_trade_date(now: datetime | None = None, verified_open_dates: set[date] | None = None) -> date:
    """Resolve morning report date only when a verified official calendar is supplied."""
    current=now or datetime.now(TAIPEI)
    if current.tzinfo is None or current.utcoffset() is None:
        raise CalendarUnavailable("current time must be timezone-aware")
    local = current.astimezone(TAIPEI)
    if local.weekday() >= 5 or not (time(6, 30) <= local.time().replace(tzinfo=None) <= time(8, 45)):
        raise CalendarUnavailable("outside the configured Taiwan morning collection window")
    candidate = local.date()
    if verified_open_dates is None or candidate not in verified_open_dates:
        raise CalendarUnavailable(f"no verified TAIFEX trading-calendar confirmation for {candidate}")
    return candidate

def date_is_weekday(value: date) -> bool:
    return value.weekday() < 5
