import time
from datetime import datetime, timezone
from fxbot.domain import Bar, Direction
from fxbot.mt5_types import SymbolInfo, Position, OrderResult

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - only available on Windows with MT5 installed
    mt5 = None

TIMEFRAME_MAP_NAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
}

# symbol_info().filling_mode is a bitmask of the fill policies a symbol allows.
# The MetaTrader5 Python package (unlike MQL5) does not expose these bit values
# as module attributes, so they're hardcoded here per the MT5 API docs:
# https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants#enum_symbol_trade_execution
_SYMBOL_FILLING_FOK = 1
_SYMBOL_FILLING_IOC = 2

DEFAULT_DEVIATION = 20


def resolve_symbol_in(available: list[str], generic: str) -> str:
    """Map a generic symbol name (e.g. "XAUUSD") to the broker's actual name
    (e.g. "XAUUSD.m"): exact case-insensitive match first, else the first
    (sorted) name starting with the generic, else ValueError."""
    wanted = generic.upper()
    exact = [s for s in available if s.upper() == wanted]
    if exact:
        return exact[0]
    partial = [s for s in available if s.upper().startswith(wanted)]
    if partial:
        return sorted(partial)[0]
    raise ValueError(f"No symbol matching {generic!r} found among: {available}")


def _row_to_bar(r) -> Bar:
    return Bar(
        time=datetime.fromtimestamp(r["time"], tz=timezone.utc),
        open=r["open"], high=r["high"], low=r["low"], close=r["close"],
        volume=r["tick_volume"],
    )


def build_order_request(
    symbol: str, direction: Direction, lot: float, sl: float, tp: float, price: float,
    deviation: int = DEFAULT_DEVIATION, filling_mode: str = "ORDER_FILLING_IOC",
) -> dict:
    return {
        "action": "TRADE_ACTION_DEAL",
        "symbol": symbol,
        "volume": lot,
        "type": "ORDER_TYPE_BUY" if direction == Direction.BUY else "ORDER_TYPE_SELL",
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "type_filling": filling_mode,
        "type_time": "ORDER_TIME_GTC",
    }


class LiveMT5Client:
    """Thin wrapper around the MetaTrader5 package. Requires the MT5 terminal
    to be installed and running. Not unit-tested (no live terminal in CI) —
    verify manually against a demo account."""

    def __init__(self, login: int, password: str, server: str):
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package not available on this platform")
        self.login = login
        self.password = password
        self.server = server

    def connect(self) -> bool:
        if not mt5.initialize():
            return False
        return mt5.login(self.login, password=self.password, server=self.server)

    def is_connected(self) -> bool:
        return mt5.terminal_info() is not None

    def get_available_symbols(self) -> list[str]:
        return [s.name for s in mt5.symbols_get()]

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"mt5.symbol_info returned None for {symbol} (mt5.last_error()={mt5.last_error()})")
        return SymbolInfo(
            name=info.name,
            volume_step=info.volume_step,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            contract_size=info.trade_contract_size,
            point=info.point,
            digits=info.digits,
        )

    def get_account_balance(self) -> float:
        return mt5.account_info().balance

    def get_rates(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        mt5.symbol_select(symbol, True)
        tf = getattr(mt5, TIMEFRAME_MAP_NAMES[timeframe])

        # Manche Broker/Terminals lehnen sehr grosse Einzel-Requests mit
        # "Invalid params" ab, daher wird die Historie in Batches abgeholt.
        batch_size = 2000
        rates_batches = []
        start_pos = 0
        while sum(len(b) for b in rates_batches) < count:
            remaining = count - sum(len(b) for b in rates_batches)
            request_size = min(batch_size, remaining)

            batch = None
            for attempt in range(5):
                batch = mt5.copy_rates_from_pos(symbol, tf, start_pos, request_size)
                if batch is not None:
                    break
                time.sleep(1)  # Terminal laedt Historie ggf. erst asynchron vom Broker nach

            if batch is None:
                if not rates_batches:
                    raise RuntimeError(
                        f"mt5.copy_rates_from_pos returned None for {symbol}/{timeframe} after retries "
                        f"(mt5.last_error()={mt5.last_error()}) — pruefe, ob das Symbol im "
                        f"Market Watch aktiviert ist und der Broker genug Historie liefert"
                    )
                break  # bereits gesammelte Bars zurueckgeben, statt komplett abzubrechen
            if len(batch) == 0:
                break  # keine weitere (aeltere) Historie verfuegbar

            rates_batches.insert(0, batch)
            start_pos += request_size

        return [_row_to_bar(r) for batch in rates_batches for r in batch]

    def get_rates_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Bar]:
        mt5.symbol_select(symbol, True)
        tf = getattr(mt5, TIMEFRAME_MAP_NAMES[timeframe])
        rates = None
        for attempt in range(5):
            rates = mt5.copy_rates_range(symbol, tf, start, end)
            if rates is not None:
                break
            time.sleep(1)  # Terminal laedt Historie ggf. erst asynchron vom Broker nach
        if rates is None:
            raise RuntimeError(
                f"mt5.copy_rates_range returned None for {symbol}/{timeframe} after retries "
                f"(mt5.last_error()={mt5.last_error()})"
            )
        return [_row_to_bar(r) for r in rates]

    def get_spread_points(self, symbol: str) -> float:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"mt5.symbol_info returned None for {symbol}")
        return float(info.spread)

    def resolve_symbol(self, generic: str) -> str:
        return resolve_symbol_in(self.get_available_symbols(), generic)

    def get_current_price(self, symbol: str) -> tuple[float, float]:
        mt5.symbol_select(symbol, True)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"mt5.symbol_info_tick returned None for {symbol} (mt5.last_error()={mt5.last_error()})")
        return tick.bid, tick.ask

    def get_server_time(self) -> datetime:
        symbols = mt5.symbols_get()
        if not symbols:
            raise RuntimeError("No symbols available from MT5 terminal to determine server time")
        tick = mt5.symbol_info_tick(symbols[0].name)
        return datetime.fromtimestamp(tick.time, tz=timezone.utc)

    def _resolve_filling_mode(self, symbol: str) -> str:
        """Not every broker/symbol accepts ORDER_FILLING_IOC — sending an
        unsupported mode is rejected with 'Unsupported filling mode'. Ask the
        broker which modes this symbol actually allows (a bitmask) and pick the
        first one it supports, falling back to ORDER_FILLING_RETURN (the most
        widely supported mode) if neither FOK nor IOC is advertised."""
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"mt5.symbol_info returned None for {symbol} (mt5.last_error()={mt5.last_error()})")
        filling_mode = info.filling_mode
        if filling_mode & _SYMBOL_FILLING_FOK:
            return "ORDER_FILLING_FOK"
        if filling_mode & _SYMBOL_FILLING_IOC:
            return "ORDER_FILLING_IOC"
        return "ORDER_FILLING_RETURN"

    def send_order(self, symbol: str, direction: Direction, lot: float, sl: float, tp: float) -> OrderResult:
        bid, ask = self.get_current_price(symbol)
        price = ask if direction == Direction.BUY else bid
        filling_mode = self._resolve_filling_mode(symbol)
        request = build_order_request(symbol, direction, lot, sl, tp, price, filling_mode=filling_mode)
        request["type"] = getattr(mt5, request["type"])
        request["action"] = getattr(mt5, request["action"])
        request["type_filling"] = getattr(mt5, request["type_filling"])
        request["type_time"] = getattr(mt5, request["type_time"])
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(False, None, f"order_send returned None: {mt5.last_error()}")
        success = result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(success=success, ticket=result.order if success else None, comment=result.comment)

    def get_open_positions(self, symbol: str) -> list[Position]:
        positions = mt5.positions_get(symbol=symbol) or []
        return [
            Position(
                ticket=p.ticket, symbol=p.symbol,
                direction=Direction.BUY if p.type == 0 else Direction.SELL,
                volume=p.volume, price_open=p.price_open, sl=p.sl, tp=p.tp,
                open_time=datetime.fromtimestamp(p.time, tz=timezone.utc),
            )
            for p in positions
        ]

    def _close_request(self, position, volume: float) -> dict:
        """Build the opposite-side market DEAL request that closes `volume` of
        `position`. type_filling is resolved per symbol (default FOK is rejected
        by brokers that only allow IOC/RETURN)."""
        direction = Direction.SELL if position.type == 0 else Direction.BUY
        bid, ask = self.get_current_price(position.symbol)
        price = bid if direction == Direction.SELL else ask
        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_SELL if direction == Direction.SELL else mt5.ORDER_TYPE_BUY,
            "position": position.ticket,
            "price": price,
            "deviation": DEFAULT_DEVIATION,
            "type_filling": getattr(mt5, self._resolve_filling_mode(position.symbol)),
        }

    def _close(self, ticket: int, volume: float | None) -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        position = positions[0]
        request = self._close_request(position, position.volume if volume is None else volume)
        result = mt5.order_send(request)
        if result is None:
            return False
        return result.retcode == mt5.TRADE_RETCODE_DONE

    def close_position(self, ticket: int) -> bool:
        return self._close(ticket, None)

    def close_partial_position(self, ticket: int, volume: float) -> bool:
        return self._close(ticket, volume)

    def modify_stop_loss(self, ticket: int, new_sl: float) -> bool:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        position = positions[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": position.symbol,
            "sl": new_sl,
            "tp": position.tp,
        }
        result = mt5.order_send(request)
        if result is None:
            return False
        return result.retcode == mt5.TRADE_RETCODE_DONE
