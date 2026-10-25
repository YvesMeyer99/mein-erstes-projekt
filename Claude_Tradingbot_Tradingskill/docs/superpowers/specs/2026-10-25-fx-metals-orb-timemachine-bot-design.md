# FX/Metals ORB + Time Machine Bot — Design / Spec

**Status:** approved decisions from planning session 2026-10-25
**Author:** YvesMeyer99 (+ Claude)

## 1. Goal

A new, standalone Python trading bot that ports the ideas of the `day-trader`
Claude skill (Opening-Range-Breakout entry + Monte-Carlo "Time Machine") from
US stocks to **FX pairs and Gold/Silver (XAUUSD/XAGUSD)**, trades **fully
automatically through MetaTrader 5**, and can be **backtested** on history
pulled directly from MT5 or loaded from CSV.

It reuses the proven primitives of the existing `Claude Tradingbot` project
(MT5 connection, %-risk lot sizing, daily/weekly risk guards) but is a separate
codebase: no human-in-the-loop confirmation (the original skill required a
typed "yes"); the risk engine is the hard gate instead.

## 2. Locked decisions (from the planning Q&A)

| Decision | Choice |
| --- | --- |
| Project | **New standalone project** in this repo (`fxbot/` package). Reuses patterns from `Claude Tradingbot`, copied + adapted, not imported. |
| Strategy | **Port ORB + Time Machine.** Opening-Range-Breakout entry; Monte-Carlo Time Machine as an *optional pre-trade filter* and as an analysis command. |
| Risk model | **%-based.** Risk per trade in % of balance; max daily loss in % (and optional weekly %). |
| Session anchor | **London open (08:00 Europe/London).** Opening range = first `or_minutes` after the London open, per trading day, DST-aware via `zoneinfo`. |

## 3. Scope

**In scope**
- `config.json` for trading parameters incl. a **selectable list of symbols**
  (any FX pair + `XAUUSD`/`XAGUSD`), each with a per-symbol override block.
- Secrets (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`) in `.env`, never in
  `config.json`.
- MT5 adapter: live price/bars, account balance, symbol info, order send with
  SL/TP, position read/modify/close; plus **history download**
  (`copy_rates_range`) for backtesting.
- ORB entry detection (long **and** short), exit planner (stop rules: `or_mid`,
  `or_low`/`or_high`, `atr:K`, `pct:X`; target `R`-multiple), %-risk lot sizing.
- Pre-trade risk engine (hard gate): per-trade loss %, daily loss %, optional
  weekly loss %, trades/day cap, session window, max spread, duplicate-position
  guard, min reward:risk, flat-by.
- Time Machine Monte-Carlo adapted to a **configurable session window** (not the
  fixed NYSE 78-bar day), from MT5 or CSV bars.
- Backtester: ORB-per-day replay over historical 5-minute bars (MT5 or CSV),
  stop/target/flat-by simulation, aggregate metrics.
- Fully automatic live engine + runner that loops over enabled symbols.

**Out of scope (non-goals)**
- Web dashboard, Telegram, ML/RL strategies (exist in the old bot; not ported).
- Options/pending orders/hedging/grid; only single market positions with SL/TP.
- News filter (may be a later plan).
- 1-minute replay pool for the Time Machine (5-minute bars only, like the skill).

## 4. Strategy definition (ORB on the London session)

- **Timeframe:** 5-minute bars (`M5`).
- **Trading day / session window:** per symbol, `session.open` (default 08:00
  Europe/London) to `session.flat_by` (default 20:00 London). The window is
  sliced into fixed 5-minute **slots** indexed from the open.
- **Opening range:** high/low of the first `or_minutes` (default 15 → 3 bars)
  after the session open.
- **Entry trigger:** the first **closed** 5-minute bar after the opening range
  whose close is **above the range high** (→ BUY) or **below the range low**
  (→ SELL). First side to trigger wins; one entry per symbol per day.
- **Exit:** stop by `stop_rule` (default `or_mid`), target = `target_r` × risk
  (default 2R). Flat by `session.flat_by`, win or lose.
- Stop below entry for a BUY, above entry for a SELL (`Signal.__post_init__`
  enforces `sl<entry<tp` / `tp<entry<sl`).

## 5. Config schema (`config.json`)

```json
{
  "timeframe": "M5",
  "risk": {
    "risk_per_trade_pct": 1.0,
    "max_daily_loss_pct": 3.0,
    "max_weekly_loss_pct": 6.0,
    "max_trades_per_day": 3,
    "min_reward_risk": 1.5,
    "max_open_positions": 3
  },
  "session": { "timezone": "Europe/London", "open": "08:00", "flat_by": "20:00" },
  "strategy": {
    "or_minutes": 15,
    "stop_rule": "or_mid",
    "target_r": 2.0,
    "allow_short": true,
    "max_spread_points": 30
  },
  "timemachine_filter": { "enabled": false, "min_p_green": 0.5, "replays": 10000, "seed": 19 },
  "symbols": [
    { "name": "EURUSD", "enabled": true },
    { "name": "GBPUSD", "enabled": true },
    { "name": "XAUUSD", "enabled": true, "overrides": { "or_minutes": 30, "max_spread_points": 50 } },
    { "name": "XAGUSD", "enabled": false }
  ]
}
```

- Any `risk`/`session`/`strategy` key may be overridden per symbol via
  `symbols[].overrides`.
- `name` is the **generic** symbol; the live adapter resolves it to the broker's
  actual symbol (suffix handling, e.g. `EURUSD.r`, `XAUUSD.m`).

## 6. Risk model

- Lot size: `calculate_lot_size(balance, risk_pct, sl_distance, contract_size,
  volume_step, volume_min, volume_max)` — ported unchanged from the old bot
  (`app/risk_manager.py`). `sl_distance` is in price units; `contract_size`
  from MT5 `symbol_info`.
- Daily/weekly guards: realized-PnL-% accumulators that lock trading when the
  loss limit is hit (ported `DailyRiskGuard`/`WeeklyRiskGuard`). State in a
  SQLite file (same as old bot) under `data/`.
- The risk engine blocks (never confirms): it returns PASS/BLOCK + reasons; the
  engine places an order only on PASS.

## 7. Time Machine adaptation

Same algorithm as the skill's `timemachine.py` (bootstrap each session's bar
`i` as `(o,h,l,c)/prev_close` ratios, Monte-Carlo replay from the entry slot to
the session end with stop-checked-before-target, percentile bands, history
replay of the ORB rule), **but**:

- "Session" = the configured London session window, sliced into N 5-minute
  slots (N = minutes between `open` and `flat_by` ÷ 5), not the fixed NYSE 78.
- "Full session" = a past day that has **all** N slots present.
- Bars come from the MT5/CSV loader (not Yahoo); timestamps are converted to the
  session timezone to assign slots.
- Minimum 20 full sessions required, as in the skill.

## 8. Backtesting

- Data source `mt5` (via `copy_rates_range`) or `csv`.
- CSV columns: `time,open,high,low,close,volume` (ISO or epoch `time`);
  one file per symbol.
- For each trading day in range: compute opening range, find the ORB trigger,
  derive stop/target, simulate the rest of the session bar-by-bar
  (stop-before-target, flat-by exit), size with %-risk on a running balance.
- Output metrics: equity curve, win rate, avg reward:risk, expectancy,
  profit factor, max drawdown, n_trades, tp/sl/flat counts.

## 9. Review focus (inputs the spec implies but a happy-path test won't catch)

1. **Broker server time ≠ London time** — slot assignment must convert via the
   session timezone and survive DST shifts on both sides.
2. **No trigger / range never broken** on a quiet day — the day must be skipped
   cleanly, not crash or open a zero-risk trade.
3. **Spread wider than `max_spread_points`** at trigger time — the trade must be
   blocked (FX/metals spreads blow out at session open and over news).
4. **Gap through the stop** in the backtest/Time Machine — must count as a full
   −1R (or worse), never as a smaller loss.
5. **Symbol suffix / symbol not in Market Watch** — resolution must fail with a
   clear message, not silently trade the wrong or no symbol.
