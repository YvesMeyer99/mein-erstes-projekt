"""Backtest CLI.

    python -m fxbot.backtest_cli --symbol EURUSD --source csv --file eurusd.csv
    python -m fxbot.backtest_cli --symbol EURUSD --source mt5 --from 2026-07-01 --to 2026-10-01
"""
import argparse
import sys
from datetime import datetime, timezone

from fxbot.backtester import BacktestResult, run_backtest
from fxbot.config import load_config, load_settings
from fxbot.data import bars_from_csv, bars_from_mt5
from fxbot.mt5_client import LiveMT5Client

UTC = timezone.utc


def _parse_day(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)


def format_result(symbol: str, n_bars: int, r: BacktestResult) -> str:
    pf = "n/a (no losing trades)" if r.profit_factor is None else f"{r.profit_factor:.2f}"
    return "\n".join(
        [
            f"Backtest {symbol} ({n_bars} bars)",
            f"  n_trades:      {r.n_trades}",
            f"  win_rate:      {r.win_rate:.1%}",
            f"  avg_crv:       {r.avg_crv:.2f}",
            f"  expectancy:    {r.expectancy:.2f} per trade",
            f"  profit_factor: {pf}",
            f"  max_drawdown:  {r.max_drawdown:.1%}",
            f"  tp_hits:       {r.tp_hits}",
            f"  sl_hits:       {r.sl_hits}",
            f"  flat_hits:     {r.flat_hits}",
            f"  final_equity:  {r.equity_curve[-1]:.2f} (start {r.equity_curve[0]:.2f})",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backtest the ORB strategy on historical M5 bars.")
    p.add_argument("--symbol", required=True)
    p.add_argument("--source", required=True, choices=["csv", "mt5"])
    p.add_argument("--file", help="CSV path (time,open,high,low,close,volume); required for --source csv")
    p.add_argument("--from", dest="start", help="YYYY-MM-DD (UTC); required for --source mt5")
    p.add_argument("--to", dest="end", help="YYYY-MM-DD (UTC); required for --source mt5")
    p.add_argument("--config", default="config.json")
    p.add_argument("--balance", type=float, default=10_000.0, help="starting balance")
    p.add_argument(
        "--contract-size", type=float, default=None,
        help="overrides the symbol's contract_size from the config (e.g. 100 for XAUUSD)",
    )
    args = p.parse_args(argv)

    def fail(msg: str) -> int:
        print(f"error: {msg}", file=sys.stderr)
        return 2

    if args.source == "csv" and not args.file:
        return fail("--file is required with --source csv")
    if args.source == "mt5" and not (args.start and args.end):
        return fail("--from and --to are required with --source mt5")

    try:
        cfg = load_config(args.config)
        wanted = args.symbol.strip().upper()
        sym = next((s for s in cfg.symbols if s.name.upper() == wanted), None)
        if sym is None:
            names = ", ".join(s.name for s in cfg.symbols)
            return fail(f"symbol {args.symbol!r} not found in {args.config} (have: {names})")

        if args.source == "csv":
            bars = bars_from_csv(args.file)
        else:
            settings = load_settings()
            client = LiveMT5Client(settings.mt5_login, settings.mt5_password, settings.mt5_server, path=settings.mt5_path)
            if not client.connect():
                return fail("could not connect/login to the MT5 terminal")
            bars = bars_from_mt5(client, sym.name, cfg.timeframe, _parse_day(args.start), _parse_day(args.end))

        contract_size = args.contract_size if args.contract_size is not None else sym.contract_size
        result = run_backtest(bars, sym, starting_balance=args.balance, contract_size=contract_size)
    except (ValueError, OSError, RuntimeError) as exc:
        return fail(str(exc))

    print(format_result(sym.name, len(bars), result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
