from datetime import date, datetime, timezone

import pytest

from fxbot.domain import Bar
from fxbot.sessions import (
    group_by_session_day,
    opening_range,
    session_day,
    session_slots,
    slot_index,
)

LONDON = "Europe/London"


def _bar(t, o=1.0, h=2.0, l=0.5, c=1.5):
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=1.0)


THREE_BARS_8_00_TO_8_15 = {
    0: _bar(datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc), h=10.0, l=8.0),
    1: _bar(datetime(2026, 1, 5, 8, 5, tzinfo=timezone.utc), h=12.0, l=9.0),
    2: _bar(datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc), h=11.0, l=7.5),
}


def test_slot_zero_is_london_open_in_summer():  # BST = UTC+1
    t = datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)  # 08:00 London
    assert slot_index(t, date(2026, 7, 1), LONDON, "08:00") == 0


def test_slot_zero_is_london_open_in_winter():  # GMT = UTC+0
    t = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)  # 08:00 London
    assert slot_index(t, date(2026, 1, 5), LONDON, "08:00") == 0


def test_slot_index_later_bar_and_before_open():
    day = date(2026, 7, 1)
    assert slot_index(datetime(2026, 7, 1, 7, 15, tzinfo=timezone.utc), day, LONDON, "08:00") == 3
    assert slot_index(datetime(2026, 7, 1, 6, 55, tzinfo=timezone.utc), day, LONDON, "08:00") is None


def test_slot_index_dst_transition_day():
    # 2026-03-29: clocks go forward 01:00 GMT -> 02:00 BST. 08:00 London = 07:00 UTC.
    day = date(2026, 3, 29)
    assert slot_index(datetime(2026, 3, 29, 7, 0, tzinfo=timezone.utc), day, LONDON, "08:00") == 0
    assert slot_index(datetime(2026, 3, 29, 7, 5, tzinfo=timezone.utc), day, LONDON, "08:00") == 1


def test_session_day_is_london_local_date():
    # 23:30 UTC in summer is 00:30 London next day
    t = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)
    assert session_day(t, LONDON) == date(2026, 7, 2)
    # In winter it is still the same day
    t = datetime(2026, 1, 5, 23, 30, tzinfo=timezone.utc)
    assert session_day(t, LONDON) == date(2026, 1, 5)


def test_opening_range_first_three_bars():
    hi, lo = opening_range(THREE_BARS_8_00_TO_8_15, or_minutes=15)
    assert (hi, lo) == (12.0, 7.5)


def test_opening_range_missing_slot_returns_none():
    partial = {0: THREE_BARS_8_00_TO_8_15[0], 2: THREE_BARS_8_00_TO_8_15[2]}
    assert opening_range(partial, or_minutes=15) is None


def test_opening_range_ignores_slots_after_window():
    bars = dict(THREE_BARS_8_00_TO_8_15)
    bars[3] = _bar(datetime(2026, 1, 5, 8, 15, tzinfo=timezone.utc), h=99.0, l=0.1)
    assert opening_range(bars, or_minutes=15) == (12.0, 7.5)


def test_session_slots_08_to_20_is_144():
    assert session_slots("08:00", "20:00") == 144


def test_group_by_session_day_summer_and_winter():
    bars = [
        _bar(datetime(2026, 7, 1, 6, 55, tzinfo=timezone.utc)),  # 07:55 London, before open
        _bar(datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc)),   # slot 0
        _bar(datetime(2026, 7, 1, 7, 5, tzinfo=timezone.utc)),   # slot 1
        _bar(datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)),   # slot 0
    ]
    grouped = group_by_session_day(bars, LONDON, "08:00")
    assert set(grouped) == {date(2026, 7, 1), date(2026, 1, 5)}
    assert set(grouped[date(2026, 7, 1)]) == {0, 1}
    assert set(grouped[date(2026, 1, 5)]) == {0}


def test_naive_datetime_raises():
    t = datetime(2026, 1, 5, 8, 0)
    with pytest.raises(ValueError):
        session_day(t, LONDON)
    with pytest.raises(ValueError):
        slot_index(t, date(2026, 1, 5), LONDON, "08:00")
