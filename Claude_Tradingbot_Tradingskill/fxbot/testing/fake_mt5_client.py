import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from fxbot.domain import Bar, Direction
from fxbot.mt5_client import resolve_symbol_in
from fxbot.mt5_types import ClosedDeal, OrderResult, Position, SymbolInfo


@dataclass(frozen=True)
class SentOrder:
    symbol: str
    direction: Direction
    lot: float
    sl: float
    tp: float
    ticket: int


class FakeMT5Client:
    """In-memory MT5Client for tests. Records every sent order in
    `sent_orders`; positions stay open until closed."""

    def __init__(
        self,
        bars_by_symbol: dict[str, list[Bar]],
        balance: float,
        symbol_info: SymbolInfo,
        spread_points: float = 0.0,
        server_time: datetime | None = None,
        closed_deals: list[ClosedDeal] | None = None,
    ):
        self.bars_by_symbol = bars_by_symbol
        self.balance = balance
        self.symbol_info = symbol_info
        self.spread_points = spread_points
        self.server_time = server_time or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.sent_orders: list[SentOrder] = []
        self.closed_deals: list[ClosedDeal] = list(closed_deals or [])
        self._positions: dict[int, Position] = {}
        self._next_ticket = 1
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def get_available_symbols(self) -> list[str]:
        return sorted({*self.bars_by_symbol, self.symbol_info.name})

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return self.symbol_info

    def get_account_balance(self) -> float:
        return self.balance

    def get_rates(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        return list(self.bars_by_symbol[symbol][-count:])

    def get_rates_range(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        return [b for b in self.bars_by_symbol[symbol] if start <= b.time <= end]

    def get_spread_points(self, symbol: str) -> float:
        return self.spread_points

    def resolve_symbol(self, generic: str) -> str:
        return resolve_symbol_in(self.get_available_symbols(), generic)

    def get_current_price(self, symbol: str) -> tuple[float, float]:
        bars = self.bars_by_symbol[symbol]
        price = bars[-1].close
        half = self.spread_points * self.symbol_info.point / 2
        return price - half, price + half

    def get_server_time(self) -> datetime:
        return self.server_time

    def send_order(
        self, symbol: str, direction: Direction, lot: float, sl: float, tp: float
    ) -> OrderResult:
        ticket = self._next_ticket
        self._next_ticket += 1
        self.sent_orders.append(SentOrder(symbol, direction, lot, sl, tp, ticket))
        bid, ask = self.get_current_price(symbol)
        self._positions[ticket] = Position(
            ticket=ticket, symbol=symbol, direction=direction, volume=lot,
            price_open=ask if direction == Direction.BUY else bid,
            sl=sl, tp=tp, open_time=self.server_time,
        )
        return OrderResult(success=True, ticket=ticket, comment="ok")

    def get_open_positions(self, symbol: str) -> list[Position]:
        return [p for p in self._positions.values() if p.symbol == symbol]

    def close_position(self, ticket: int) -> bool:
        return self._positions.pop(ticket, None) is not None

    def close_partial_position(self, ticket: int, volume: float) -> bool:
        pos = self._positions.get(ticket)
        if pos is None:
            return False
        step = self.symbol_info.volume_step
        tol = step / 2  # float-safe: volumes are multiples of volume_step
        if volume > pos.volume + tol:
            return False
        remaining = pos.volume - volume
        if remaining < step - tol or math.isclose(volume, pos.volume):
            del self._positions[ticket]  # remainder below one step = full close
        else:
            self._positions[ticket] = replace(pos, volume=remaining)
        return True

    def modify_stop_loss(self, ticket: int, new_sl: float) -> bool:
        pos = self._positions.get(ticket)
        if pos is None:
            return False
        self._positions[ticket] = replace(pos, sl=new_sl)
        return True

    def get_closed_deals(self, start: datetime, end: datetime) -> list[ClosedDeal]:
        return [d for d in self.closed_deals if start <= d.close_time <= end]
