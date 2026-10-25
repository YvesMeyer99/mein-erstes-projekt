# fxbot - FX / metals Opening-Range-Breakout bot

Fully automatic MetaTrader 5 bot. It trades an opening-range breakout (ORB) on M5 bars,
per symbol and per London-anchored session, with an optional "Time Machine" filter.

## RISK WARNING - read before connecting anything

**This bot trades fully automatically. If it is pointed at a live account it trades real
money with no human confirmation.** The risk engine is the only gate in front of an order.
Most retail traders lose money. Start on an MT5 **demo** account and do not go live until you
understand every limitation listed below.

## Install

- Windows with the MetaTrader 5 terminal installed and running (the `MetaTrader5` Python
  package only works on Windows).
- Python 3.11 or newer.

```
pip install -r requirements.txt
pip install tzdata        # time-zone database (needed on Windows for Europe/London etc.)
```

## Configure

1. Secrets: copy `.env.example` to `.env` and fill in your account. Secrets are read only from
   `.env` and are never printed.

   ```
   MT5_LOGIN=12345678
   MT5_PASSWORD=...
   MT5_SERVER=YourBroker-Demo
   # optional: DB_PATH=data/fxbot.db
   ```

2. Strategy / risk: copy `config.example.json` to `config.json` and edit it. Enable the
   symbols you want (`"enabled": true`) and adjust the risk, session, strategy and
   `timemachine_filter` blocks. Per-symbol `overrides` replace single keys of the top-level
   blocks.

## Run live

```
python -m fxbot.main                       # uses ./config.json
python -m fxbot.main --config my.json --poll-seconds 5
```

The runner connects to the terminal, then runs one pass per closed M5 bar until you press
Ctrl+C.

## Backtest

```
python -m fxbot.backtest_cli --symbol EURUSD --source csv --file eurusd.csv
python -m fxbot.backtest_cli --symbol EURUSD --source mt5 --from 2026-07-01 --to 2026-10-01
python -m fxbot.backtest_cli --symbol XAUUSD --source csv --file xau.csv --contract-size 100 --balance 10000
```

CSV columns: `time,open,high,low,close,volume` (epoch seconds or ISO-8601, UTC). The symbol is
looked up in `config.json` (override with `--config`). The result prints trade count, win rate,
average CRV, expectancy, profit factor, max drawdown and TP/SL/flat exit counts.

## Tests

```
python -m pytest
```

All tests run offline against a fake MT5 client; none touch a terminal or place orders.

## Manual verification (human, MT5 demo)

The live terminal paths (`LiveMT5Client`, real `order_send`) are not unit-tested. Verify them by hand:

1. Set `.env` to an MT5 **DEMO** account (never a live one for this check).
2. In `config.json` enable exactly one symbol.
3. Run `python -m fxbot.main`.
4. Confirm that a breakout places exactly ONE order, with SL and TP set, in the demo terminal.
5. Confirm that a wide-spread case (spread above `max_spread_points`, e.g. temporarily set it very
   low) is blocked and no order appears.

Result (fill in after running): _not yet performed_

## Known limitations (as of this build)

1. Closed-trade PnL is NOT yet reconciled back into the daily/weekly loss guards, so those loss
   limits do NOT fire during live trading yet (a follow-up task). They work in backtests.
2. Only the `or_mid` / `or_low` / `or_high` stop rules are usable; `pct` / `atr` need a
   `stop_param` config field that does not exist yet (a follow-up).
3. `flat_close` closes ALL positions on a traded symbol via the broker - run the bot on a
   DEDICATED account with no manual positions on those symbols.
4. The duplicate-order latch is in-memory and is lost on a process restart.
