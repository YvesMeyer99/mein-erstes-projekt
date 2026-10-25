"""Live runner: wires the engine to a real MT5 terminal and polls once per closed M5 bar.

    python -m fxbot.main [--config config.json] [--poll-seconds 5]

This trades FULLY AUTOMATICALLY with no human confirmation. See README.md.
"""
import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from fxbot.config import Settings, TradingConfig, load_config, load_settings
from fxbot.engine import LiveEngine
from fxbot.mt5_client import LiveMT5Client
from fxbot.db import init_db
from fxbot.sessions import SLOT_MINUTES

log = logging.getLogger(__name__)

UTC = timezone.utc
DEFAULT_POLL_SECONDS = 5
DEFAULT_SETTLE_SECONDS = 5  # let the broker publish the just-closed bar before we read it


def build_engine(settings: Settings, cfg: TradingConfig) -> LiveEngine:
    """Create the MT5 client, connect it, open the DB, and return the engine."""
    client = LiveMT5Client(settings.mt5_login, settings.mt5_password, settings.mt5_server, path=settings.mt5_path)
    if not client.connect():
        raise RuntimeError("could not connect/login to the MT5 terminal (is it running? check .env)")
    conn = init_db(settings.db_path)
    return LiveEngine(client, conn, cfg)


def _bar_slot(now_utc: datetime) -> datetime:
    """Start of the M5 bar that `now_utc` falls in."""
    minute = now_utc.minute - now_utc.minute % SLOT_MINUTES
    return now_utc.replace(minute=minute, second=0, microsecond=0)


def _log_outcomes(outcomes) -> None:
    """Log each outcome; a logging problem must never be mistaken for an engine failure
    (orders may already have been placed by then)."""
    try:
        for outcome in outcomes:
            log.info("%s: %s %s", outcome.symbol, outcome.action, "; ".join(map(str, outcome.reasons)))
    except Exception:
        log.exception("could not log run_all_once outcomes (the engine pass itself completed)")


def run_loop(
    engine,
    poll_seconds: int,
    clock=lambda: datetime.now(UTC),
    stop=lambda: False,
    sleep=time.sleep,
    settle_seconds: float = DEFAULT_SETTLE_SECONDS,
) -> None:
    """Call `engine.run_all_once` once per closed M5 bar until `stop()` is true.

    `clock` returns the current UTC time and `stop` returns the stop flag; both
    are injectable so the loop is testable without real time. A failure inside
    a pass is logged and never ends the loop (the bar is not retried).
    """
    last_slot: datetime | None = None
    while not stop():
        now = clock()
        slot = _bar_slot(now - timedelta(seconds=settle_seconds))
        if slot != last_slot:
            last_slot = slot
            try:
                outcomes = engine.run_all_once(now)
            except Exception:
                log.exception("run_all_once failed; continuing with the next bar")
            else:
                _log_outcomes(outcomes)
        if stop():
            break
        sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the FX/metals ORB bot live (fully automatic).")
    parser.add_argument("--config", default="config.json", help="path to config.json (copy of config.example.json)")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
        cfg = load_config(args.config)
        engine = build_engine(settings, cfg)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    stopping = {"v": False}

    def _request_stop(signum, frame):
        stopping["v"] = True

    signal.signal(signal.SIGINT, _request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _request_stop)

    log.info("bot started; polling every %ss (Ctrl+C to stop)", args.poll_seconds)
    run_loop(engine, args.poll_seconds, stop=lambda: stopping["v"])
    log.info("bot stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
