# FX/Metals ORB + Time Machine Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone Python bot that trades an Opening-Range-Breakout strategy on config-selected FX pairs and Gold/Silver fully automatically through MetaTrader 5, with a Monte-Carlo "Time Machine" pre-trade filter and a backtester fed from MT5 history or CSV.

**Architecture:** A `fxbot/` package built around the existing `Claude Tradingbot` primitives (ported, not imported): frozen domain types (`Bar`/`Direction`/`Signal`), an `MT5Client` Protocol with a live adapter and a fake for tests, a session/opening-range layer (London-anchored, DST-aware), a pure ORB strategy + exit planner, a %-risk engine that is the hard gate (no human "yes"), a Monte-Carlo Time Machine, a CSV/MT5 backtester, and a live engine + runner loop.

**Tech Stack:** Python 3.11+ (needs `zoneinfo`), `MetaTrader5`, `pandas`, `numpy`, `python-dotenv`, `pytest`. Standard-library `sqlite3` for risk state.

**Spec:** `docs/superpowers/specs/2026-10-25-fx-metals-orb-timemachine-bot-design.md`

## Global Constraints

- Python **3.11+** (project uses `zoneinfo` for DST-correct session math).
- Secrets only in `.env` (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`); never in `config.json`, logs, or source.
- Timeframe is **`M5`** (5-minute bars) everywhere — live, Time Machine, backtest.
- Session anchor is **`Europe/London`**, default open `08:00`, flat-by `20:00`; all slot math converts bar timestamps (UTC from MT5) into this zone.
- Risk is **%-based**: `risk_per_trade_pct`, `max_daily_loss_pct`, optional `max_weekly_loss_pct`.
- Stop/target obey `Signal.__post_init__`: BUY needs `sl < entry < tp`, SELL needs `tp < entry < sl`.
- Stop-before-target tie-break: a bar touching both the stop and the target counts as the **stop** (conservative), in the Time Machine and the backtester.
- The risk engine only ever returns PASS/BLOCK; an order is placed only on PASS. No order is placed from historical/backtest code.
- Money math that compares to the cent (stops/targets) rounds a long's stop **down** and a short's stop **up**, away from entry.
- `MetaTrader5` imports must be guarded (`try/except ImportError`) so the package imports and tests run on non-Windows CI.

## Review Focus

1. **Broker server time ≠ London** — slotting must convert UTC bar times to `Europe/London` and stay correct across both zones' DST changes. *(Task 3 test.)*
2. **No ORB trigger on a quiet day** — range never broken ⇒ return "no trigger", never a zero-risk or crashing trade. *(Task 4 test.)*
3. **Spread wider than `max_spread_points`** at trigger ⇒ BLOCK. *(Task 6 test.)*
4. **Gap through the stop** ⇒ counts as full −1R (or worse), not a smaller loss, in both replay and backtest. *(Task 7 and Task 9 tests.)*
5. **Symbol suffix / not in Market Watch** ⇒ resolution raises a clear error, never trades the wrong/no symbol. *(Task 2 test.)*

---

### Task 1: Project scaffold, domain types, config loader

**Files:**
- Create: `fxbot/__init__.py`, `fxbot/domain.py`, `fxbot/config.py`, `requirements.txt`, `config.example.json`, `.env.example`, `pytest.ini`
- Test: `tests/__init__.py`, `tests/test_domain.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `Direction(Enum)` {`BUY="buy"`, `SELL="sell"`}; `@dataclass(frozen=True) Bar(time: datetime, open, high, low, close, volume: float)`; `@dataclass(frozen=True) Signal(direction, confidence, entry, sl, tp: float)` with `.crv` property and `__post_init__` validation (ported verbatim from `Claude Tradingbot/app/signals.py`).
- Produces: `load_settings() -> Settings` (ported from `app/config.py`: `mt5_login:int`, `mt5_password`, `mt5_server`, `db_path` default `data/fxbot.db`; drops dashboard/telegram keys).
- Produces: `@dataclass SymbolConfig(name:str, enabled:bool, risk:RiskConfig, session:SessionConfig, strategy:StrategyConfig)`, `@dataclass TradingConfig(timeframe:str, timemachine:TMConfig, symbols:list[SymbolConfig])`, and `load_config(path:str) -> TradingConfig` that applies `symbols[].overrides` onto the top-level `risk`/`session`/`strategy` blocks (per the spec §5 schema).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_domain.py
def test_buy_signal_requires_sl_below_entry_below_tp():
    with pytest.raises(ValueError): Signal(Direction.BUY, 1.0, entry=10, sl=11, tp=12)
def test_crv_is_reward_over_risk():
    assert Signal(Direction.BUY, 1.0, entry=10, sl=9, tp=12).crv == 2.0

# tests/test_config.py
def test_load_config_applies_per_symbol_overrides(tmp_path):
    cfg = load_config(_write(tmp_path, EXAMPLE_JSON))   # EXAMPLE_JSON = spec §5
    xau = next(s for s in cfg.symbols if s.name == "XAUUSD")
    assert xau.strategy.or_minutes == 30            # override
    assert xau.strategy.target_r == 2.0             # inherited top-level
def test_load_config_rejects_unknown_stop_rule(tmp_path): ...  # expect ValueError
```

- [ ] **Step 2: Run tests, verify they fail** — `pytest tests/test_domain.py tests/test_config.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement `fxbot/domain.py`** by porting `Direction`, `Bar`, `Signal` from `Claude Tradingbot/app/signals.py` (drop `MarketState`).
- [ ] **Step 4: Implement `fxbot/config.py`** with `Settings`/`load_settings` (ported) and the `TradingConfig` dataclasses + `load_config`. Validate `stop_rule ∈ {or_mid,or_low,or_high,atr,pct}`, `timeframe == "M5"`, each `symbols[].name` non-empty.
- [ ] **Step 5: Write `requirements.txt`, `config.example.json` (spec §5 verbatim), `.env.example` (the three MT5 keys), `pytest.ini` (`pythonpath = .`).**
- [ ] **Step 6: Run tests, verify pass.**
- [ ] **Step 7: Commit** — `git add fxbot tests requirements.txt config.example.json .env.example pytest.ini && git commit -m "feat: scaffold fxbot with domain types and config loader"`

---

### Task 2: MT5 types, live adapter, fake client

**Files:**
- Create: `fxbot/mt5_types.py`, `fxbot/mt5_client.py`, `fxbot/testing/__init__.py`, `fxbot/testing/fake_mt5_client.py`
- Test: `tests/test_mt5_client.py`, `tests/test_fake_mt5_client.py`

**Interfaces:**
- Consumes: `Bar`, `Direction` (Task 1).
- Produces: `@dataclass(frozen=True) SymbolInfo(name, volume_step, volume_min, volume_max, contract_size, point, digits)`, `Position(...)`, `OrderResult(success, ticket, comment)`, and `MT5Client(Protocol)` — ported from `app/mt5_types.py` plus three additions: `get_rates_range(symbol, timeframe, start:datetime, end:datetime) -> list[Bar]`, `get_spread_points(symbol) -> float`, and `resolve_symbol(generic:str) -> str`.
- Produces: `LiveMT5Client(login, password, server)` (ported from `app/mt5_connector.py`) with: `resolve_symbol` (exact match, else first symbol whose name starts with the generic among `symbols_get()`, else `ValueError` naming the generic and the candidates); `get_rates_range` via `mt5.copy_rates_range`; `get_spread_points` from `symbol_info`. `send_order` keeps the `_resolve_filling_mode` logic.
- Produces: `FakeMT5Client(bars_by_symbol, balance, symbol_info, spread_points=0.0)` implementing the Protocol in memory; `send_order` appends to `.sent_orders` and returns a success `OrderResult`; `get_open_positions` reflects sent-but-unclosed orders.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_fake_mt5_client.py
def test_send_order_records_and_opens_position():
    c = FakeMT5Client({"EURUSD":[...]}, balance=10_000, symbol_info=INFO)
    r = c.send_order("EURUSD", Direction.BUY, 0.1, sl=1.09, tp=1.12)
    assert r.success and len(c.sent_orders) == 1
    assert c.get_open_positions("EURUSD")[0].direction == Direction.BUY

# tests/test_mt5_client.py  (no live terminal: test only the pure resolver)
def test_resolve_symbol_raises_clear_error_when_absent():
    with pytest.raises(ValueError, match="XAUUSD"):
        resolve_symbol_in(["EURUSD","GBPUSD"], "XAUUSD")     # Review Focus #5
def test_resolve_symbol_matches_broker_suffix():
    assert resolve_symbol_in(["XAUUSD.m","EURUSD"], "XAUUSD") == "XAUUSD.m"
```

- [ ] **Step 2: Run tests, verify fail.**
- [ ] **Step 3: Implement `fxbot/mt5_types.py`** (port + the three new Protocol methods).
- [ ] **Step 4: Implement `fxbot/mt5_client.py`** — extract the pure `resolve_symbol_in(available:list[str], generic:str)->str` helper (unit-testable), have `LiveMT5Client.resolve_symbol` call it; port the rest from `app/mt5_connector.py`, adding `get_rates_range`/`get_spread_points`. Guard `import MetaTrader5`.
- [ ] **Step 5: Implement `fxbot/testing/fake_mt5_client.py`.**
- [ ] **Step 6: Run tests, verify pass.**
- [ ] **Step 7: Commit** — `feat: MT5 client protocol, live adapter, fake client`

---

### Task 3: Session windows & opening range (London, DST-aware)

**Files:**
- Create: `fxbot/sessions.py`
- Test: `tests/test_sessions.py`

**Interfaces:**
- Consumes: `Bar` (Task 1).
- Produces: `session_day(bar_time:datetime, tz:str) -> date` — the London-local date a UTC bar belongs to.
- Produces: `slot_index(bar_time:datetime, day:date, tz:str, open_hhmm:str) -> int | None` — 5-minute slot number from the session open (0-based); `None` if the bar is before the open.
- Produces: `session_slots(open_hhmm:str, flat_by_hhmm:str) -> int` — number of 5-minute slots in the window.
- Produces: `opening_range(day_bars:dict[int,Bar], or_minutes:int) -> tuple[float,float] | None` — `(high, low)` of slots `0..or_minutes/5-1`, `None` if any are missing.
- Produces: `group_by_session_day(bars:list[Bar], tz:str, open_hhmm:str) -> dict[date, dict[int, Bar]]`.

- [ ] **Step 1: Write failing tests** (Review Focus #1)

```python
# tests/test_sessions.py  — bars timestamped in UTC
def test_slot_zero_is_london_open_in_summer():         # BST = UTC+1
    t = datetime(2026,7,1, 7,0, tzinfo=timezone.utc)   # 08:00 London
    assert slot_index(t, date(2026,7,1), "Europe/London", "08:00") == 0
def test_slot_zero_is_london_open_in_winter():         # GMT = UTC+0
    t = datetime(2026,1,5, 8,0, tzinfo=timezone.utc)   # 08:00 London
    assert slot_index(t, date(2026,1,5), "Europe/London", "08:00") == 0
def test_opening_range_first_three_bars():
    hi, lo = opening_range(THREE_BARS_8_00_TO_8_15, or_minutes=15)
    assert (hi, lo) == (expected_high, expected_low)
def test_session_slots_08_to_20_is_144():
    assert session_slots("08:00","20:00") == 144
```

- [ ] **Step 2: Run tests, verify fail.**
- [ ] **Step 3: Implement `fxbot/sessions.py`** using `zoneinfo.ZoneInfo(tz)`; convert each bar's UTC time to the session zone, compute minutes since open, `// 5` for the slot.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat: London-anchored session slotting and opening range`

---

### Task 4: ORB entry detection

**Files:**
- Create: `fxbot/strategy.py` (entry half)
- Test: `tests/test_strategy_entry.py`

**Interfaces:**
- Consumes: `Bar`, `Direction` (Task 1); `opening_range` (Task 3).
- Produces: `@dataclass(frozen=True) OrbTrigger(direction:Direction, entry:float, trigger_time:datetime, slot:int, or_high:float, or_low:float)`.
- Produces: `detect_orb_trigger(day_bars:dict[int,Bar], or_minutes:int, allow_short:bool) -> OrbTrigger | None` — first closed bar at a slot after the opening-range slots whose close `> or_high` (BUY) or `< or_low` (SELL, only if `allow_short`); returns the first side to fire; `None` if none fire or the opening range is missing.

- [ ] **Step 1: Write failing tests** (Review Focus #2 is the `None` case)

```python
# tests/test_strategy_entry.py
def test_buy_trigger_on_first_close_above_range():
    t = detect_orb_trigger(DAY_WITH_UPSIDE_BREAK, or_minutes=15, allow_short=True)
    assert t.direction == Direction.BUY and t.entry == BREAK_BAR_CLOSE
def test_sell_trigger_when_allowed():
    assert detect_orb_trigger(DAY_WITH_DOWN_BREAK, 15, allow_short=True).direction == Direction.SELL
def test_no_short_when_disallowed_returns_none_if_only_downside():
    assert detect_orb_trigger(DAY_WITH_DOWN_BREAK, 15, allow_short=False) is None
def test_quiet_day_no_trigger_returns_none():          # Review Focus #2
    assert detect_orb_trigger(DAY_INSIDE_RANGE, 15, allow_short=True) is None
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `detect_orb_trigger`. Step 4: Run, verify pass. Step 5: Commit** — `feat: ORB entry detection (long/short)`

---

### Task 5: Exit planner (stop + target → Signal)

**Files:**
- Modify: `fxbot/strategy.py` (exit half)
- Create: `fxbot/indicators.py` (ATR only, ported from `app/market_data.py:compute_atr` adapted to `list[Bar]`)
- Test: `tests/test_strategy_exit.py`

**Interfaces:**
- Consumes: `OrbTrigger` (Task 4), `Bar`, `Direction`, `Signal` (Task 1).
- Produces: `plan_exit(trigger:OrbTrigger, stop_rule:str, target_r:float, session_bars:list[Bar]|None=None, stop_param:float|None=None) -> Signal` — stop by rule (`or_mid`=cents-away midpoint, `or_low`/`or_high`, `pct`=`stop_param`% of entry, `atr`=`stop_param`×ATR14 of `session_bars` up to the trigger), target = `entry ± target_r*risk`; rounds a long's stop down / short's up (away from entry); raises `ValueError` if the rule needs data it wasn't given, or if risk ≤ 0.
- Produces: `atr14(bars:list[Bar], period:int=14) -> float` in `fxbot/indicators.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_strategy_exit.py
def test_or_mid_stop_and_2r_target_for_buy():
    s = plan_exit(BUY_TRIGGER_or_hi_1p11_lo_1p10_entry_1p111, "or_mid", 2.0)
    assert s.sl == 1.105 and round(s.tp,3) == round(1.111 + 2*(1.111-1.105),3)
def test_sell_uses_or_high_stop_above_entry():
    s = plan_exit(SELL_TRIGGER, "or_high", 2.0); assert s.sl > s.entry > s.tp
def test_atr_stop_requires_session_bars():
    with pytest.raises(ValueError): plan_exit(BUY_TRIGGER, "atr", 2.0, stop_param=1.5)
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `atr14` + `plan_exit`. Step 4: Run, verify pass. Step 5: Commit** — `feat: ORB exit planner with or/atr/pct stops`

---

### Task 6: Risk sizing, daily/weekly guards, pre-trade risk engine

**Files:**
- Create: `fxbot/risk.py`, `fxbot/db.py`
- Test: `tests/test_risk.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: `Signal`, `Direction` (Task 1); `SymbolInfo`, `Position` (Task 2); `RiskConfig` (Task 1).
- Produces: `calculate_lot_size(balance, risk_pct, sl_distance, contract_size, volume_step, volume_min, volume_max) -> float` and `round_down_to_volume_step(volume, step) -> float` — **ported verbatim** from `app/risk_manager.py`.
- Produces: `DailyRiskGuard(conn, max_daily_risk_pct, daily_win_stop_pct=None)` and `WeeklyRiskGuard(conn, max_weekly_risk_pct)` with `realized_pnl_pct`, `record_pnl`, `is_locked` — ported from `app/risk_manager.py`.
- Produces: `init_db(path) -> sqlite3.Connection` creating `daily_risk`, `weekly_risk`, `trades` tables (port the old bot's schema; `trades` keyed by symbol + entry_time).
- Produces: `@dataclass RiskDecision(ok:bool, reasons:list[str])` and `RiskEngine(conn, cfg:RiskConfig).check(signal, symbol, *, spread_points, max_spread_points, open_positions:list[Position], trades_today:int, now_utc, session_open_utc, session_flat_by_utc, server_date:str, week_start:str) -> RiskDecision` — BLOCK on: daily/weekly lock, trades/day cap, `spread_points > max_spread_points` (Review Focus #3), an existing open position on the symbol, `signal.crv < min_reward_risk`, or `now_utc` outside `[session_open_utc, session_flat_by_utc)`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_risk.py
def test_lot_size_matches_ported_formula():
    assert calculate_lot_size(10_000,1.0,0.0050,100_000,0.01,0.01,100.0) == 0.2
def test_block_when_spread_too_wide():                 # Review Focus #3
    d = engine.check(SIG, "EURUSD", spread_points=40, max_spread_points=30,
                     open_positions=[], trades_today=0, ...)
    assert not d.ok and any("spread" in r for r in d.reasons)
def test_block_when_position_already_open():
    assert not engine.check(SIG,"EURUSD",...,open_positions=[POS_EURUSD],...).ok
def test_block_when_daily_locked(): ...
def test_pass_on_clean_trade(): assert engine.check(SIG,"EURUSD",...).ok
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `fxbot/db.py` then `fxbot/risk.py`. Step 4: Run, verify pass. Step 5: Commit** — `feat: %-risk sizing, daily/weekly guards, pre-trade risk engine`

---

### Task 7: Time Machine (Monte-Carlo replay + ORB history)

**Files:**
- Create: `fxbot/timemachine.py`
- Test: `tests/test_timemachine.py`
- Test fixture: `tests/fixtures/timemachine/eurusd-60d-5m.json` (synthetic ≥20 full London sessions)

**Interfaces:**
- Consumes: `Bar`, `Direction` (Task 1); `group_by_session_day`, `session_slots`, `opening_range` (Task 3); `OrbTrigger`/`Signal` (Tasks 4,5).
- Produces: `build_pool(sessions:list[list[Bar]], n_slots:int) -> list[list[tuple]]` — bar `i` as `(o,h,l,c)/prev_close`, slots `1..n_slots-1`.
- Produces: `simulate(pool, entry, stop, target, k_slot, last_slot, side:Direction, replays=10000, seed=19, window=2) -> dict` — ported from the skill's `simulate` (stop-before-target; outcomes target/stop/neither; `p_target/p_stop/p_neither/p_green/avg_R/r_at_target`). A gap past the stop inside a bar is a full −1R (Review Focus #4).
- Produces: `history_replay(sessions, or_minutes, stop_rule, target_r, last_slot, side) -> dict` — the ORB rule on each past session (triggered/target/stop/close/avg_R).
- Produces: `run_time_machine(bars:list[Bar], day:date, trigger:OrbTrigger, signal:Signal, cfg:SymbolConfig) -> dict` — assembles the pool from the ≥20 full sessions before `day`, runs `simulate` + `history_replay`, returns a verdict dict incl. `p_green`. Raises `ValueError` if < 20 full sessions or the entry slot isn't in that day.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_timemachine.py
def test_simulate_is_deterministic_for_seed():
    a = simulate(POOL, 1.10, 1.095, 1.11, 3, 50, Direction.BUY, replays=2000, seed=19)
    b = simulate(POOL, 1.10, 1.095, 1.11, 3, 50, Direction.BUY, replays=2000, seed=19)
    assert a["p_target"] == b["p_target"]
def test_probabilities_sum_to_one():
    r = simulate(POOL, 1.10,1.095,1.11,3,50,Direction.BUY,replays=5000,seed=19)
    assert abs(r["p_target"]+r["p_stop"]+r["p_neither"] - 1.0) < 1e-9
def test_gap_through_stop_counts_full_minus_one_r():   # Review Focus #4
    # a pool whose only move gaps far below the stop ⇒ avg_R ≈ -1, never > -1
    assert simulate(GAP_DOWN_POOL, 1.10,1.095,1.11,0,5,Direction.BUY,replays=1000,seed=1)["avg_R"] <= -1.0 + 1e-6
def test_run_refuses_with_too_few_sessions():
    with pytest.raises(ValueError): run_time_machine(FEW_BARS, DAY, TRIG, SIG, CFG)
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `fxbot/timemachine.py`** porting `build_pool`/`simulate`/`history_replay` with slot count from `session_slots` instead of the fixed 78. **Step 4: Run, verify pass. Step 5: Commit** — `feat: Monte-Carlo Time Machine for the London session`

---

### Task 8: Bar loaders — CSV and MT5 history

**Files:**
- Create: `fxbot/data.py`
- Test: `tests/test_data.py`
- Test fixture: `tests/fixtures/data/eurusd-sample.csv`

**Interfaces:**
- Consumes: `Bar` (Task 1); `MT5Client` (Task 2).
- Produces: `bars_from_csv(path:str) -> list[Bar]` — columns `time,open,high,low,close,volume`; `time` as ISO-8601 (UTC) or epoch seconds; sorted ascending; raises `ValueError` naming a missing column.
- Produces: `bars_from_mt5(client:MT5Client, symbol:str, timeframe:str, start:datetime, end:datetime) -> list[Bar]` — thin wrapper over `client.resolve_symbol` + `client.get_rates_range`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_data.py
def test_csv_loads_and_sorts_bars():
    bars = bars_from_csv(FIXTURE_CSV)
    assert bars[0].time < bars[-1].time and bars[0].open > 0
def test_csv_missing_column_raises():
    with pytest.raises(ValueError, match="close"): bars_from_csv(BAD_CSV)
def test_bars_from_mt5_uses_resolved_symbol():
    bars_from_mt5(FakeMT5Client(...), "XAUUSD", "M5", START, END)   # returns fake bars
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `fxbot/data.py`. Step 4: Run, verify pass. Step 5: Commit** — `feat: CSV and MT5 history bar loaders`

---

### Task 9: Backtester (ORB-per-day over 5-minute history)

**Files:**
- Create: `fxbot/backtester.py`
- Test: `tests/test_backtester.py`

**Interfaces:**
- Consumes: `Bar` (1); sessions (3); `detect_orb_trigger`/`plan_exit` (4,5); `calculate_lot_size` (6).
- Produces: `@dataclass(frozen=True) BacktestResult(equity_curve, win_rate, avg_crv, max_drawdown, expectancy, n_trades, profit_factor, tp_hits, sl_hits, flat_hits)` (mirrors `app/backtester.py`, `be/trailing` dropped, `flat_hits` added).
- Produces: `run_backtest(bars:list[Bar], cfg:SymbolConfig, starting_balance=10_000.0, contract_size=100_000.0) -> BacktestResult` — per session day: opening range → `detect_orb_trigger` → `plan_exit` → simulate the rest of the session bar-by-bar (stop-before-target; flat at `flat_by`), size with %-risk on the running balance, accrue PnL. A day with no trigger is skipped.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_backtester.py
def test_single_winning_day_hits_target():
    r = run_backtest(ONE_DAY_UP_TO_TARGET, CFG_EURUSD, starting_balance=10_000)
    assert r.n_trades == 1 and r.tp_hits == 1 and r.equity_curve[-1] > 10_000
def test_gap_through_stop_is_full_risk_loss():         # Review Focus #4
    r = run_backtest(ONE_DAY_GAP_BELOW_STOP, CFG_EURUSD, starting_balance=10_000)
    assert r.sl_hits == 1
    assert (10_000 - r.equity_curve[-1]) >= 10_000 * CFG_EURUSD.risk.risk_per_trade_pct/100 - 1e-6
def test_quiet_day_makes_no_trade():
    assert run_backtest(ONE_QUIET_DAY, CFG_EURUSD).n_trades == 0
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `fxbot/backtester.py`. Step 4: Run, verify pass. Step 5: Commit** — `feat: ORB backtester with stop-before-target and flat-by exit`

---

### Task 10: Live trading engine (decide → filter → risk → size → order)

**Files:**
- Create: `fxbot/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: `@dataclass TradeOutcome(symbol, action:str, reasons:list[str], order:OrderResult|None)` where `action ∈ {"placed","blocked","no_trigger","filtered","flat_close"}`.
- Produces: `LiveEngine(client:MT5Client, conn, cfg:TradingConfig).run_symbol_once(symbol_cfg:SymbolConfig, now_utc:datetime) -> TradeOutcome` — pulls `M5` bars via `client.get_rates` (enough to cover today plus, when the Time Machine filter is enabled, ≥60 prior sessions for the pool — e.g. `count = session_slots * 65`), groups by session day, detects the ORB trigger on the last **closed** bar's day, plans the exit, optionally runs `run_time_machine` and drops the trade if `p_green < min_p_green` (action `filtered`), runs `RiskEngine.check`, sizes with `calculate_lot_size` on `client.get_account_balance()`, and on PASS calls `client.send_order` and records the trade row. At/after `flat_by` it closes any open position on the symbol (action `flat_close`).
- Produces: `LiveEngine.run_all_once(now_utc) -> list[TradeOutcome]` over enabled symbols.

- [ ] **Step 1: Write failing tests** (all against `FakeMT5Client` — no live terminal)

```python
# tests/test_engine.py
def test_places_order_on_clean_breakout():
    out = engine.run_symbol_once(CFG_EURUSD, NOW_AFTER_BREAK)
    assert out.action == "placed" and client.sent_orders[-1].symbol == "EURUSD"
def test_no_trigger_places_nothing():
    assert engine.run_symbol_once(CFG_EURUSD, NOW_QUIET).action == "no_trigger"
def test_risk_block_places_nothing():
    assert engine.run_symbol_once(CFG_WIDE_SPREAD, NOW_AFTER_BREAK).action == "blocked"
def test_timemachine_filter_drops_bad_odds():
    assert engine.run_symbol_once(CFG_TM_FILTER_ON, NOW_AFTER_BREAK).action in {"filtered","placed"}
def test_flat_by_closes_open_position():
    assert engine.run_symbol_once(CFG_EURUSD, NOW_AT_FLAT_BY).action == "flat_close"
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `fxbot/engine.py`. Step 4: Run, verify pass. Step 5: Commit** — `feat: fully automatic live trading engine`

---

### Task 11: Runner, CLI, and manual MT5 verification

**Files:**
- Create: `fxbot/main.py`, `fxbot/backtest_cli.py`, `README.md`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: Tasks 1,2,6,8,9,10.
- Produces: `build_engine(settings:Settings, cfg:TradingConfig) -> LiveEngine` (wires `LiveMT5Client` + `init_db`), and `run_loop(engine, poll_seconds:int, clock=..., stop=...)` that calls `run_all_once` once per closed `M5` bar until the stop flag is set.
- Produces: `fxbot/backtest_cli.py` — `python -m fxbot.backtest_cli --symbol EURUSD --source csv --file eurusd.csv` or `--source mt5 --from 2026-07-01 --to 2026-10-01`, prints the `BacktestResult`.
- Produces: `README.md` with install, `.env`/`config.json` setup, a **Manual verification** section (connect to an MT5 **demo**, run one `run_all_once`, confirm the order appears in the demo terminal), and the fully-automatic-trading risk warning.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_main.py
def test_build_engine_wires_db_and_client(monkeypatch): ...   # injects FakeMT5Client
def test_run_loop_runs_once_then_stops_on_flag():
    # a fake clock advancing one M5 bar, a stop flag set after the first pass
    assert len(calls) == 1
```

- [ ] **Step 2: Run, verify fail. Step 3: Implement `main.py` + `backtest_cli.py` + `README.md`. Step 4: Run `pytest -q` (whole suite green). Step 5: Commit** — `feat: runner loop, backtest CLI, README with MT5 demo verification`
- [ ] **Step 6: Manual verification (human, demo account):** set `.env` to an MT5 **demo**, enable one symbol, run `python -m fxbot.main`, confirm a breakout places exactly one order with SL/TP in the demo terminal and that a wide-spread case is blocked. Record the result in the README.

---

## Notes for the implementer

- Port, don't reinvent: `domain.py`, `calculate_lot_size`, the risk guards, the MT5 adapter and the backtest skeleton come from `C:\Users\Yves Meier\Documents\claude-code\Claude Tradingbot\app\`. Match that code's style.
- The only genuinely new logic is London-anchored slotting (Task 3), long/short ORB detection (Task 4), the session-window Time Machine (Task 7) and the live wiring (Task 10). Spend the care there.
- Live-terminal paths (`LiveMT5Client`, real `order_send`) are **not** unit-tested; they are covered by the Task 11 manual demo verification. Everything else runs offline against `FakeMT5Client` and fixtures.
