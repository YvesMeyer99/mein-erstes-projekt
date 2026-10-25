import math
import sqlite3
from dataclasses import dataclass, field
from collections.abc import Iterable
from datetime import datetime

from fxbot.config import RiskConfig
from fxbot.domain import Signal
from fxbot.mt5_types import Position


def effective_loss_caps(risks: Iterable[RiskConfig]) -> tuple[float, float]:
    """(daily, weekly) loss cap in percent the live guards enforce for these risk configs.

    The smallest POSITIVE cap wins (a cap of 0 means "off" for the config check, so it is
    ignored); if none is positive the RiskConfig() defaults apply. Shared by the live engine
    and the backtester so both resolve caps identically.
    """
    risks = list(risks)
    default = RiskConfig()

    def strictest(values: list[float], fallback: float) -> float:
        positive = [v for v in values if v > 0]
        return min(positive) if positive else fallback

    return (
        strictest([r.max_daily_loss_pct for r in risks], default.max_daily_loss_pct),
        strictest([r.max_weekly_loss_pct for r in risks], default.max_weekly_loss_pct),
    )


def calculate_lot_size(
    balance: float,
    risk_pct: float,
    sl_distance: float,
    contract_size: float,
    volume_step: float,
    volume_min: float,
    volume_max: float,
) -> float:
    if sl_distance <= 0:
        raise ValueError("sl_distance must be positive")

    money_risk = balance * (risk_pct / 100.0)
    money_risk_per_lot = sl_distance * contract_size
    raw_lot = money_risk / money_risk_per_lot

    steps = math.floor(raw_lot / volume_step)
    lot = steps * volume_step
    lot = max(lot, volume_min)
    lot = min(lot, volume_max)
    return round(lot, 8)


def round_down_to_volume_step(volume: float, volume_step: float) -> float:
    steps = math.floor(round(volume / volume_step, 8))
    return round(steps * volume_step, 8)


class DailyRiskGuard:
    def __init__(self, conn: sqlite3.Connection, max_daily_risk_pct: float, daily_win_stop_pct: float | None = None):
        self.conn = conn
        self.max_daily_risk_pct = max_daily_risk_pct
        self.daily_win_stop_pct = daily_win_stop_pct

    def _get_row(self, date: str):
        return self.conn.execute(
            "SELECT * FROM daily_risk WHERE date = ?", (date,)
        ).fetchone()

    def realized_pnl_pct(self, date: str) -> float:
        row = self._get_row(date)
        return row["realized_pnl_pct"] if row is not None else 0.0

    def record_pnl(self, date: str, pnl_pct: float) -> None:
        row = self._get_row(date)
        if row is None:
            realized = pnl_pct
        else:
            realized = row["realized_pnl_pct"] + pnl_pct

        hit_loss_limit = realized <= -abs(self.max_daily_risk_pct)
        hit_win_stop = self.daily_win_stop_pct is not None and realized >= self.daily_win_stop_pct
        # Latch: once locked for a date it stays locked, even if later PnL recovers.
        already_locked = row is not None and bool(row["is_locked"])
        is_locked = 1 if (already_locked or hit_loss_limit or hit_win_stop) else 0

        self.conn.execute(
            "INSERT INTO daily_risk (date, realized_pnl_pct, is_locked) VALUES (?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET realized_pnl_pct = excluded.realized_pnl_pct, "
            "is_locked = excluded.is_locked",
            (date, realized, is_locked),
        )
        self.conn.commit()

    def is_locked(self, date: str) -> bool:
        row = self._get_row(date)
        return bool(row["is_locked"]) if row is not None else False


class WeeklyRiskGuard:
    def __init__(self, conn: sqlite3.Connection, max_weekly_risk_pct: float):
        self.conn = conn
        self.max_weekly_risk_pct = max_weekly_risk_pct

    def _get_row(self, week_start: str):
        return self.conn.execute(
            "SELECT * FROM weekly_risk WHERE week_start_date = ?", (week_start,)
        ).fetchone()

    def realized_pnl_pct(self, week_start: str) -> float:
        row = self._get_row(week_start)
        return row["realized_pnl_pct"] if row is not None else 0.0

    def record_pnl(self, week_start: str, pnl_pct: float) -> None:
        row = self._get_row(week_start)
        if row is None:
            realized = pnl_pct
        else:
            realized = row["realized_pnl_pct"] + pnl_pct

        # Latch: once locked for a week it stays locked, even if later PnL recovers.
        hit_loss_limit = realized <= -abs(self.max_weekly_risk_pct)
        already_locked = row is not None and bool(row["is_locked"])
        is_locked = 1 if (already_locked or hit_loss_limit) else 0

        self.conn.execute(
            "INSERT INTO weekly_risk (week_start_date, realized_pnl_pct, is_locked) VALUES (?, ?, ?) "
            "ON CONFLICT(week_start_date) DO UPDATE SET realized_pnl_pct = excluded.realized_pnl_pct, "
            "is_locked = excluded.is_locked",
            (week_start, realized, is_locked),
        )
        self.conn.commit()

    def is_locked(self, week_start: str) -> bool:
        row = self._get_row(week_start)
        return bool(row["is_locked"]) if row is not None else False


def count_trades_today(conn: sqlite3.Connection, symbol: str, today: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as c FROM trades WHERE symbol = ? AND date(entry_time) = ?",
        (symbol, today),
    ).fetchone()
    return row["c"]


@dataclass
class RiskDecision:
    ok: bool
    reasons: list[str] = field(default_factory=list)


class RiskEngine:
    """Pre-trade hard gate. Only ever returns PASS (ok=True) or BLOCK (ok=False)."""

    def __init__(self, conn: sqlite3.Connection, cfg: RiskConfig):
        self.conn = conn
        self.cfg = cfg
        self.daily = DailyRiskGuard(conn, cfg.max_daily_loss_pct)
        self.weekly = WeeklyRiskGuard(conn, cfg.max_weekly_loss_pct)

    def check(
        self,
        signal: Signal,
        symbol: str,
        *,
        spread_points: float,
        max_spread_points: float,
        open_positions: list[Position],
        trades_today: int,
        now_utc: datetime,
        session_open_utc: datetime,
        session_flat_by_utc: datetime,
        server_date: str,
        week_start: str,
    ) -> RiskDecision:
        reasons: list[str] = []

        if self.daily.is_locked(server_date):
            reasons.append(f"daily loss limit locked for {server_date}")
        if self.weekly.is_locked(week_start):
            reasons.append(f"weekly loss limit locked for week starting {week_start}")
        if trades_today >= self.cfg.max_trades_per_day:
            reasons.append(
                f"max trades per day reached ({trades_today} >= {self.cfg.max_trades_per_day})"
            )
        # Fail closed: negated comparisons so NaN inputs BLOCK instead of passing.
        if not (spread_points <= max_spread_points):
            reasons.append(f"spread too wide ({spread_points} > {max_spread_points} points)")
        if any(p.symbol == symbol for p in open_positions):
            reasons.append(f"position already open on {symbol}")
        if len(open_positions) >= self.cfg.max_open_positions:
            reasons.append(
                f"max open positions reached ({len(open_positions)} >= {self.cfg.max_open_positions})"
            )
        if not (signal.crv >= self.cfg.min_reward_risk):
            reasons.append(f"reward/risk too low ({signal.crv:.2f} < {self.cfg.min_reward_risk})")
        if not (session_open_utc <= now_utc < session_flat_by_utc):
            reasons.append(
                f"outside trading session ({now_utc.isoformat()} not in "
                f"[{session_open_utc.isoformat()}, {session_flat_by_utc.isoformat()}))"
            )

        return RiskDecision(ok=not reasons, reasons=reasons)
