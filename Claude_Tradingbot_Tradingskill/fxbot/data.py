import csv
from datetime import datetime, timezone

from fxbot.domain import Bar
from fxbot.mt5_types import MT5Client

_REQUIRED_COLUMNS = ("time", "open", "high", "low", "close", "volume")


def _parse_time(raw: str) -> datetime:
    """Epoch seconds or ISO-8601 -> tz-aware UTC datetime (naive ISO is taken as UTC)."""
    text = raw.strip()
    try:
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    except ValueError:
        pass
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def bars_from_csv(path: str) -> list[Bar]:
    """Load bars from a CSV with columns time,open,high,low,close,volume,
    sorted ascending by time."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        for col in _REQUIRED_COLUMNS:
            if col not in fields:
                raise ValueError(f"CSV {path!r} is missing required column {col!r}")
        bars = [
            Bar(
                time=_parse_time(row["time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in reader
        ]
    bars.sort(key=lambda b: b.time)
    return bars


def bars_from_mt5(
    client: MT5Client, symbol: str, timeframe: str, start: datetime, end: datetime
) -> list[Bar]:
    """Fetch history for a generic symbol, resolving the broker's actual name first."""
    resolved = client.resolve_symbol(symbol)
    return client.get_rates_range(resolved, timeframe, start, end)
