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

   - `stop_param` (strategy block or per-symbol override): percent of entry for
     `"stop_rule": "pct"`, ATR(14) multiple for `"atr"`; leave `null` for the `or_*` rules.
   - `contract_size` (per symbol entry, used by the backtest CLI; default 100000, e.g. 100 for
     XAUUSD). `--contract-size` overrides it. Live sizing always uses the broker's value.
   - Config load fails if the enabled symbols' summed `risk_per_trade_pct` exceeds
     `max_daily_loss_pct` (see limitation 1): lower the per-trade risk, disable symbols or raise the cap.

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
python -m fxbot.backtest_cli --symbol XAUUSD --source csv --file xau.csv --balance 10000   # contract_size from config
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
4. Confirm the broker-time normalization: the log shows the derived `broker server UTC offset`
   (e.g. +2.00 h in winter, +3.00 h in summer) and slot 0 lands on the real 08:00 London candle
   (compare the first bar of the session in the terminal chart against the bot's session open).
   If the offset cannot be derived (e.g. market closed), set `MT5_SERVER_UTC_OFFSET_HOURS` in `.env`.
5. Confirm that a breakout places exactly ONE order, with SL and TP set, in the demo terminal.
6. Confirm that a wide-spread case (spread above `max_spread_points`, e.g. temporarily set it very
   low) is blocked and no order appears.

Result (fill in after running): _not yet performed_

## Known limitations (as of this build)

1. Closed-trade PnL IS reconciled into the daily/weekly loss guards at the start of every pass
   (`fxbot/reconcile.py`: broker deal history via `history_deals_get`, matched to the `trades` row by
   position ticket, net of commission/swap/fee, dated by the UTC close time). The lock only fires AFTER
   a stop-out is booked, so one round of stops can still overshoot the cap. If the history call fails,
   new entries are blocked for that pass. The live deal-history path (`LiveMT5Client.get_closed_deals`)
   is not unit-tested: verify on the demo account that a stopped-out trade appears in `trades`
   (`closed=1`, `pnl`, `pnl_pct`) and in `daily_risk`.
2. All stop rules are usable (`or_mid` / `or_low` / `or_high`, plus `pct` / `atr` with a
   `stop_param`). Because the daily lock only fires after the losses are booked, the config
   loader still refuses setups where one round of stops across the enabled symbols could exceed it.
3. `flat_close` closes ALL positions on a traded symbol via the broker - run the bot on a
   DEDICATED account with no manual positions on those symbols.
4. The duplicate-order latch is in-memory and is lost on a process restart. (A clean
   `success=False` order rejection, e.g. a requote, does not latch; an exception or a placed order does.)
5. The MetaTrader5 package reports bar/tick/position times in the BROKER SERVER's clock (often
   UTC+2/+3), not UTC. `LiveMT5Client` normalizes everything to true UTC: on `connect()` it derives the
   server-to-UTC offset once (fresh tick vs. the local UTC clock, rounded to the hour) or reads the
   `MT5_SERVER_UTC_OFFSET_HOURS` override, and `connect()` fails if neither works. The offset is fixed
   per run, so restart the bot after the broker's DST change. This path is not unit-tested (only the pure
   helpers are): verify on the demo account that slot 0 lands at the real 08:00 London.
