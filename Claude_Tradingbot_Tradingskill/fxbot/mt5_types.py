from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fxbot.domain import Bar, Direction


@dataclass(frozen=True)
class SymbolInfo:
    name: str
    volume_step: float
    volume_min: float
    volume_max: float
    contract_size: float
    point: float
    digits: int


@dataclass(frozen=True)
class Position:
    ticket: int
    symbol: str
    direction: Direction
    volume: float
    price_open: float
    sl: float
    tp: float
    open_time: datetime


@dataclass(frozen=True)
class OrderResult:
    success: bool
    ticket: int | None
    comment: str


@dataclass(frozen=True)
class ClosedDeal:
    """A fully closed position, as realized at the broker.

    `position_id` is the broker position identifier (equals the opening order ticket
    that `send_order` returns). `profit` is the NET realized result in account
    currency (profit + commission + swap + fee across all deals of the position).
    `close_time` is tz-aware UTC; `volume` is the closed volume in lots.
    """
    position_id: int
    symbol: str
    profit: float
    close_time: datetime
    volume: float
    close_price: float = 0.0


class MT5Client(Protocol):
    def connect(self) -> bool: ...
    def is_connected(self) -> bool: ...
    def get_available_symbols(self) -> list[str]: ...
    def get_symbol_info(self, symbol: str) -> SymbolInfo: ...
    def get_account_balance(self) -> float: ...
    def get_rates(self, symbol: str, timeframe: str, count: int) -> list[Bar]: ...
    def get_rates_range(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]: ...
    def get_spread_points(self, symbol: str) -> float: ...
    def resolve_symbol(self, generic: str) -> str: ...
    def get_current_price(self, symbol: str) -> tuple[float, float]: ...
    def get_server_time(self) -> datetime: ...
    def send_order(
        self, symbol: str, direction: Direction, lot: float, sl: float, tp: float
    ) -> OrderResult: ...
    def get_open_positions(self, symbol: str) -> list[Position]: ...
    def close_position(self, ticket: int) -> bool: ...
    def close_partial_position(self, ticket: int, volume: float) -> bool: ...
    def modify_stop_loss(self, ticket: int, new_sl: float) -> bool: ...
    def get_closed_deals(self, start: datetime, end: datetime) -> list[ClosedDeal]: ...
