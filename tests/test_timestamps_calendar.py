from datetime import date, datetime, timezone
import pytest
from taifex_night_flow.timestamps import iso_utc, iso_taipei, TAIPEI
from taifex_night_flow.calendar import expected_trade_date, CalendarUnavailable

def test_timezone_conversion_uses_taipei_offset():
    value=datetime(2026,10,18,23,0,tzinfo=timezone.utc)
    assert iso_utc(value)=="2026-10-18T23:00:00Z"
    assert iso_taipei(value)=="2026-10-19T07:00:00+08:00"

def test_naive_timestamps_are_rejected():
    with pytest.raises(ValueError): iso_utc(datetime(2026,10,18,23,0))

def test_auto_calendar_fails_closed_without_verified_date():
    with pytest.raises(CalendarUnavailable,match="no verified"):
        expected_trade_date(datetime(2026,10,19,7,0,tzinfo=TAIPEI),set())

def test_auto_calendar_requires_window_and_open_date():
    open_days={date(2026,10,19)}
    assert expected_trade_date(datetime(2026,10,19,7,0,tzinfo=TAIPEI),open_days)==date(2026,10,19)
    with pytest.raises(CalendarUnavailable):
        expected_trade_date(datetime(2026,10,19,9,0,tzinfo=TAIPEI),open_days)
