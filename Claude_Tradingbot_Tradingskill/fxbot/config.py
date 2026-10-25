import json
import os
from dataclasses import dataclass, fields, replace

from dotenv import load_dotenv

load_dotenv()

REQUIRED_KEYS = ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"]

VALID_STOP_RULES = ("or_mid", "or_low", "or_high", "atr", "pct")
VALID_TIMEFRAME = "M5"


@dataclass
class Settings:
    mt5_login: int
    mt5_password: str
    mt5_server: str
    db_path: str


def load_settings() -> Settings:
    missing = [key for key in REQUIRED_KEYS if not os.environ.get(key)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return Settings(
        mt5_login=int(os.environ["MT5_LOGIN"]),
        mt5_password=os.environ["MT5_PASSWORD"],
        mt5_server=os.environ["MT5_SERVER"],
        db_path=os.environ.get("DB_PATH", "data/fxbot.db"),
    )


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_weekly_loss_pct: float = 6.0
    max_trades_per_day: int = 3
    min_reward_risk: float = 1.5
    max_open_positions: int = 3


@dataclass(frozen=True)
class SessionConfig:
    timezone: str = "Europe/London"
    open: str = "08:00"
    flat_by: str = "20:00"


@dataclass(frozen=True)
class StrategyConfig:
    or_minutes: int = 15
    stop_rule: str = "or_mid"
    target_r: float = 2.0
    allow_short: bool = True
    max_spread_points: float = 30


@dataclass(frozen=True)
class TMConfig:
    enabled: bool = False
    min_p_green: float = 0.5
    replays: int = 10000
    seed: int = 19


@dataclass(frozen=True)
class SymbolConfig:
    name: str
    enabled: bool
    risk: RiskConfig
    session: SessionConfig
    strategy: StrategyConfig


@dataclass(frozen=True)
class TradingConfig:
    timeframe: str
    timemachine: TMConfig
    symbols: list[SymbolConfig]


_BLOCKS = {"risk": RiskConfig, "session": SessionConfig, "strategy": StrategyConfig}


def _check_types(obj, where: str) -> None:
    """Reject wrongly typed values instead of silently coercing them.

    bool fields must be real bools ("false" is truthy), int fields real ints,
    float fields int/float, str fields str. bool is never accepted as a number.
    """
    for f in fields(obj):
        value = getattr(obj, f.name)
        expected = f.type
        if expected is bool:
            ok = isinstance(value, bool)
        elif expected is int:
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif expected is float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected is str:
            ok = isinstance(value, str)
        else:
            ok = True
        if not ok:
            raise ValueError(
                f"{where}.{f.name} must be of type {expected.__name__}, got {type(value).__name__} ({value!r})"
            )


def _build(cls, data: dict | None, where: str):
    """Build a config dataclass from a dict, rejecting unknown keys (typos) and wrong types."""
    data = data or {}
    if not isinstance(data, dict):
        raise ValueError(f"{where} must be an object")
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"Unknown key(s) in {where}: {', '.join(unknown)}")
    obj = cls(**data)
    _check_types(obj, where)
    return obj


def _apply_overrides(blocks: dict, overrides: dict, symbol: str) -> dict:
    """Shallow-merge per-symbol overrides onto the top-level blocks.

    A key replaces only that single key; absent keys inherit the top-level
    value. Overrides may be flat ({"or_minutes": 30}, as in the spec) or
    grouped by block ({"strategy": {"or_minutes": 30}}).
    """
    if not isinstance(overrides, dict):
        raise ValueError(f"symbols[{symbol}].overrides must be an object")
    updates: dict[str, dict] = {name: {} for name in blocks}
    owners = {f.name: block for block, cls in _BLOCKS.items() for f in fields(cls)}
    for key, value in overrides.items():
        if key in _BLOCKS:
            if not isinstance(value, dict):
                raise ValueError(f"symbols[{symbol}].overrides.{key} must be an object")
            for sub_key, sub_value in value.items():
                if sub_key not in {f.name for f in fields(_BLOCKS[key])}:
                    raise ValueError(f"Unknown key in symbols[{symbol}].overrides.{key}: {sub_key}")
                updates[key][sub_key] = sub_value
        elif key in owners:
            updates[owners[key]][key] = value
        else:
            raise ValueError(f"Unknown override key in symbols[{symbol}]: {key}")
    merged = {name: replace(blocks[name], **updates[name]) for name in blocks}
    for name, block in merged.items():
        _check_types(block, f"symbols[{symbol}].overrides.{name}")
    return merged


def _validate_strategy(strategy: StrategyConfig, where: str) -> None:
    if strategy.stop_rule not in VALID_STOP_RULES:
        raise ValueError(
            f"Invalid stop_rule {strategy.stop_rule!r} in {where}; expected one of {', '.join(VALID_STOP_RULES)}"
        )


def load_config(path: str) -> TradingConfig:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("config root must be an object")

    timeframe = raw.get("timeframe", VALID_TIMEFRAME)
    if timeframe != VALID_TIMEFRAME:
        raise ValueError(f"Unsupported timeframe {timeframe!r}; only {VALID_TIMEFRAME} is supported")

    blocks = {
        name: _build(cls, raw.get(name), name) for name, cls in _BLOCKS.items()
    }
    _validate_strategy(blocks["strategy"], "strategy")
    timemachine = _build(TMConfig, raw.get("timemachine_filter"), "timemachine_filter")

    raw_symbols = raw.get("symbols", [])
    if not isinstance(raw_symbols, list):
        raise ValueError("symbols must be a list")
    symbols: list[SymbolConfig] = []
    for entry in raw_symbols:
        if not isinstance(entry, dict):
            raise ValueError("each symbols[] entry must be an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("each symbols[].name must be a non-empty string")
        name = name.strip()
        overrides = entry.get("overrides")
        merged = _apply_overrides(blocks, {} if overrides is None else overrides, name)
        _validate_strategy(merged["strategy"], f"symbols[{name}]")
        enabled = entry.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"symbols[{name}].enabled must be a boolean, got {type(enabled).__name__} ({enabled!r})")
        symbols.append(
            SymbolConfig(
                name=name,
                enabled=enabled,
                risk=merged["risk"],
                session=merged["session"],
                strategy=merged["strategy"],
            )
        )

    return TradingConfig(timeframe=timeframe, timemachine=timemachine, symbols=symbols)
