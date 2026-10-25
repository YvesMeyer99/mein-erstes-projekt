"""Technical indicators over lists of Bars."""
from fxbot.domain import Bar


def atr14(bars: list[Bar], period: int = 14) -> float:
    """Average True Range: simple mean of the last `period` true ranges.

    Ported from the legacy compute_atr: the first bar's true range has no prior
    close, so `period` true ranges require `period + 1` bars. Raises ValueError
    if fewer bars are given.
    """
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(bars) < period + 1:
        raise ValueError(f"ATR({period}) needs at least {period + 1} bars, got {len(bars)}")
    trs = []
    for prev, cur in zip(bars[-(period + 1):-1], bars[-period:]):
        trs.append(
            max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
        )
    return sum(trs) / period
