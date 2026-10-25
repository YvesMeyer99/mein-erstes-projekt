from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Direction(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Signal:
    direction: Direction
    confidence: float
    entry: float
    sl: float
    tp: float

    def __post_init__(self):
        if self.direction == Direction.BUY:
            if not (self.sl < self.entry < self.tp):
                raise ValueError(f"BUY signal requires sl < entry < tp, got sl={self.sl}, entry={self.entry}, tp={self.tp}")
        else:
            if not (self.tp < self.entry < self.sl):
                raise ValueError(f"SELL signal requires tp < entry < sl, got sl={self.sl}, entry={self.entry}, tp={self.tp}")

    @property
    def crv(self) -> float:
        reward = abs(self.tp - self.entry)
        risk = abs(self.entry - self.sl)
        return reward / risk


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
