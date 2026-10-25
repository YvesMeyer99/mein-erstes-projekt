import pytest

from fxbot.mt5_client import resolve_symbol_in


def test_resolve_symbol_raises_clear_error_when_absent():
    with pytest.raises(ValueError, match="XAUUSD"):
        resolve_symbol_in(["EURUSD", "GBPUSD"], "XAUUSD")


def test_error_lists_available_candidates():
    with pytest.raises(ValueError, match="GBPUSD"):
        resolve_symbol_in(["EURUSD", "GBPUSD"], "XAUUSD")


def test_resolve_symbol_matches_broker_suffix():
    assert resolve_symbol_in(["XAUUSD.m", "EURUSD"], "XAUUSD") == "XAUUSD.m"


def test_exact_match_is_case_insensitive_and_preferred():
    assert resolve_symbol_in(["XAUUSD.m", "xauusd"], "XAUUSD") == "xauusd"


def test_prefix_match_picks_first_sorted():
    assert resolve_symbol_in(["XAUUSD.z", "XAUUSD.a"], "XAUUSD") == "XAUUSD.a"


# ---------------------------------------------------------------- server time -> UTC

from datetime import datetime, timezone

from fxbot.mt5_client import _row_to_bar, derive_server_utc_offset_seconds, normalize_server_epoch

UTC = timezone.utc


def _fake_utc_epoch(y, mo, d, h, mi=0) -> int:
    """MT5 style: a broker wall-clock time encoded as if it were UTC."""
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp())


def test_normalize_server_epoch_subtracts_positive_offset():
    # broker clock (UTC+2) says 10:00 -> real UTC is 08:00
    got = normalize_server_epoch(_fake_utc_epoch(2026, 1, 12, 10), 7200)
    assert got == datetime(2026, 1, 12, 8, 0, tzinfo=UTC)
    assert got.tzinfo is not None and got.utcoffset().total_seconds() == 0


def test_normalize_server_epoch_summer_offset_and_day_rollover():
    # broker clock (UTC+3) says 01:30 on the 13th -> 22:30 UTC on the 12th
    got = normalize_server_epoch(_fake_utc_epoch(2026, 7, 13, 1, 30), 10800)
    assert got == datetime(2026, 7, 12, 22, 30, tzinfo=UTC)


def test_normalize_server_epoch_zero_and_negative_offset():
    epoch = _fake_utc_epoch(2026, 1, 12, 8)
    assert normalize_server_epoch(epoch, 0) == datetime(2026, 1, 12, 8, 0, tzinfo=UTC)
    assert normalize_server_epoch(epoch, -3600) == datetime(2026, 1, 12, 9, 0, tzinfo=UTC)


def test_row_to_bar_emits_true_utc_time():
    row = {
        "time": _fake_utc_epoch(2026, 1, 12, 10), "open": 1.1, "high": 1.2, "low": 1.0,
        "close": 1.15, "tick_volume": 7,
    }
    bar = _row_to_bar(row, 7200)
    assert bar.time == datetime(2026, 1, 12, 8, 0, tzinfo=UTC)
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (1.1, 1.2, 1.0, 1.15, 7)


def test_derive_offset_rounds_fresh_tick_to_the_hour():
    now = datetime(2026, 1, 12, 8, 0, 30, tzinfo=UTC)
    tick = int(now.timestamp()) + 7200 - 2  # broker UTC+2, tick 2 s old
    assert derive_server_utc_offset_seconds(tick, now) == 7200


def test_derive_offset_summer_and_utc_brokers():
    now = datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC)
    assert derive_server_utc_offset_seconds(int(now.timestamp()) + 10800 + 1, now) == 10800
    assert derive_server_utc_offset_seconds(int(now.timestamp()) - 1, now) == 0


def test_derive_offset_rejects_stale_tick():
    now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)  # Saturday: market closed
    stale = int(now.timestamp()) + 7200 - 37 * 60      # tick not near a whole hour
    with pytest.raises(ValueError, match="MT5_SERVER_UTC_OFFSET_HOURS"):
        derive_server_utc_offset_seconds(stale, now)


def test_derive_offset_rejects_implausible_offset():
    now = datetime(2026, 1, 12, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="MT5_SERVER_UTC_OFFSET_HOURS"):
        derive_server_utc_offset_seconds(int(now.timestamp()) - 20 * 3600, now)


# ---------------------------------------------------------------- closed deals aggregation

from types import SimpleNamespace

from fxbot.mt5_client import DEAL_ENTRY_IN, DEAL_ENTRY_OUT, aggregate_closed_deals

SERVER_OFFSET = 7200  # UTC+2


def _d(position_id=7, entry=DEAL_ENTRY_OUT, typ=1, volume=0.5, price=1.1, profit=0.0,
       commission=0.0, swap=0.0, fee=0.0, hour=10, symbol="EURUSD"):
    return SimpleNamespace(
        position_id=position_id, symbol=symbol, entry=entry, type=typ, volume=volume, price=price,
        profit=profit, commission=commission, swap=swap, fee=fee,
        time=_fake_utc_epoch(2026, 1, 12, hour),
    )


def test_aggregate_sums_net_profit_and_normalizes_close_time():
    deals = [
        _d(entry=DEAL_ENTRY_IN, typ=0, price=1.1, commission=-3.0, hour=9),
        _d(entry=DEAL_ENTRY_OUT, typ=1, price=1.095, profit=-100.0, commission=-3.0, swap=-1.0, hour=12),
    ]
    [cd] = aggregate_closed_deals(deals, SERVER_OFFSET)
    assert cd.position_id == 7 and cd.symbol == "EURUSD"
    assert cd.profit == -107.0
    assert cd.volume == 0.5 and cd.close_price == 1.095
    assert cd.close_time == datetime(2026, 1, 12, 10, tzinfo=UTC)  # server 12:00 -> 10:00 UTC


def test_aggregate_skips_open_balance_and_partially_closed_positions():
    deals = [
        _d(position_id=1, entry=DEAL_ENTRY_IN, typ=0, volume=1.0),          # still open
        _d(position_id=2, entry=DEAL_ENTRY_IN, typ=0, volume=1.0),
        _d(position_id=2, entry=DEAL_ENTRY_OUT, volume=0.4, profit=5.0),    # partial close only
        _d(position_id=0, entry=0, typ=2, volume=0.0, profit=1000.0),       # balance operation
        _d(position_id=3, entry=DEAL_ENTRY_OUT, volume=0.3, profit=7.0),    # entry outside window
    ]
    got = aggregate_closed_deals(deals, SERVER_OFFSET)
    assert [c.position_id for c in got] == [3]


def test_aggregate_sorts_by_close_time():
    deals = [_d(position_id=2, hour=14, profit=1.0), _d(position_id=1, hour=11, profit=2.0)]
    assert [c.position_id for c in aggregate_closed_deals(deals, SERVER_OFFSET)] == [1, 2]
