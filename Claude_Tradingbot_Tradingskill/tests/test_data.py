from datetime import datetime, timezone
from pathlib import Path

import pytest

from fxbot.data import bars_from_csv, bars_from_mt5
from fxbot.domain import Bar
from fxbot.mt5_types import SymbolInfo
from fxbot.testing.fake_mt5_client import FakeMT5Client

FIXTURE_CSV = str(Path(__file__).parent / "fixtures" / "data" / "eurusd-sample.csv")
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_csv_loads_and_sorts_bars():
    bars = bars_from_csv(FIXTURE_CSV)
    assert len(bars) == 4
    assert bars[0].time < bars[-1].time and bars[0].open > 0
    assert [b.time for b in bars] == sorted(b.time for b in bars)
    assert all(b.time.tzinfo is not None and b.time.utcoffset().total_seconds() == 0 for b in bars)
    assert bars[0].time == datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)
    assert bars[1].time == datetime(2026, 1, 5, 8, 5, tzinfo=timezone.utc)  # naive ISO -> UTC
    assert bars[2].time == datetime(2026, 1, 5, 8, 10, tzinfo=timezone.utc)
    assert bars[3].time == datetime(2026, 1, 5, 8, 15, tzinfo=timezone.utc)  # from epoch seconds
    assert bars[0].volume == 150


def test_csv_missing_column_raises(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("time,open,high,low,volume\n2026-01-05T08:00:00+00:00,1,2,0.5,10\n")
    with pytest.raises(ValueError, match="close"):
        bars_from_csv(str(bad))


def test_bars_from_mt5_uses_resolved_symbol():
    info = SymbolInfo(
        name="XAUUSD.m", volume_step=0.01, volume_min=0.01, volume_max=100.0,
        contract_size=100.0, point=0.01, digits=2,
    )
    bars = [
        Bar(datetime(2026, 1, 1, h, tzinfo=timezone.utc), 2000.0, 2001.0, 1999.0, 2000.5, 10)
        for h in range(3)
    ]
    client = FakeMT5Client({"XAUUSD.m": bars}, balance=10_000, symbol_info=info)
    assert bars_from_mt5(client, "XAUUSD", "M5", START, END) == bars
