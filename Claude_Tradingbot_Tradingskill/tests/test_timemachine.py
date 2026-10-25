import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from fxbot.config import RiskConfig, SessionConfig, StrategyConfig, SymbolConfig
from fxbot.domain import Bar, Direction
from fxbot.sessions import group_by_session_day, session_slots
from fxbot.strategy import OrbTrigger, plan_exit
from fxbot.timemachine import build_pool, history_replay, run_time_machine, simulate

LONDON = ZoneInfo("Europe/London")
N_SLOTS = 60  # small synthetic session for the pure-simulation tests


def _synthetic_session(day: date, n_slots: int, rng: random.Random, base: float = 1.10,
                       open_hhmm: str = "08:00", tz=LONDON) -> list[Bar]:
    """One deterministic, full session of 5-minute bars (random walk, o == previous close)."""
    hh, mm = (int(x) for x in open_hhmm.split(":"))
    open_dt = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
    bars, prev = [], base
    for slot in range(n_slots):
        o = prev
        c = o * (1 + rng.uniform(-0.0006, 0.0006))
        h = max(o, c) * (1 + rng.uniform(0.0, 0.0004))
        l = min(o, c) * (1 - rng.uniform(0.0, 0.0004))
        t = (open_dt + timedelta(minutes=5 * slot)).astimezone(timezone.utc)
        bars.append(Bar(time=t, open=o, high=h, low=l, close=c, volume=100.0))
        prev = c
    return bars


def _past_weekdays(day: date, count: int) -> list[date]:
    out, d = [], day
    while len(out) < count:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return sorted(out)


def _sessions(count: int, n_slots: int, seed: int = 5) -> list[list[Bar]]:
    rng = random.Random(seed)
    return [_synthetic_session(d, n_slots, rng) for d in _past_weekdays(date(2026, 4, 20), count)]


POOL = build_pool(_sessions(25, N_SLOTS), N_SLOTS)

# every bar gaps and trades far below any sensible stop
GAP_DOWN_POOL = [[]] + [[(0.80, 0.81, 0.70, 0.75)] * 3 for _ in range(9)]
GAP_UP_POOL = [[]] + [[(1.20, 1.30, 1.19, 1.25)] * 3 for _ in range(9)]


# ---------------------------------------------------------------- build_pool

def test_build_pool_shape_and_ratios():
    sessions = _sessions(3, 10)
    pool = build_pool(sessions, 10)
    assert len(pool) == 10
    assert pool[0] == []
    assert all(len(pool[i]) == 3 for i in range(1, 10))
    s = sessions[0]
    pc = s[2].close
    o, h, l, c = pool[3][0]
    assert o == pytest.approx(s[3].open / pc)
    assert h == pytest.approx(s[3].high / pc)
    assert l == pytest.approx(s[3].low / pc)
    assert c == pytest.approx(s[3].close / pc)


# ---------------------------------------------------------------- simulate

def test_simulate_is_deterministic_for_seed():
    a = simulate(POOL, 1.10, 1.095, 1.11, 3, 50, Direction.BUY, replays=2000, seed=19)
    b = simulate(POOL, 1.10, 1.095, 1.11, 3, 50, Direction.BUY, replays=2000, seed=19)
    assert a["p_target"] == b["p_target"]
    assert a == b


def test_simulate_seed_changes_result():
    a = simulate(POOL, 1.10, 1.098, 1.102, 3, 50, Direction.BUY, replays=2000, seed=19)
    b = simulate(POOL, 1.10, 1.098, 1.102, 3, 50, Direction.BUY, replays=2000, seed=20)
    assert a["p_target"] != b["p_target"]


def test_probabilities_sum_to_one():
    r = simulate(POOL, 1.10, 1.095, 1.11, 3, 50, Direction.BUY, replays=5000, seed=19)
    assert abs(r["p_target"] + r["p_stop"] + r["p_neither"] - 1.0) < 1e-9
    assert 0.0 <= r["p_green"] <= 1.0
    assert r["r_at_target"] == pytest.approx(2.0)


def test_gap_through_stop_counts_full_minus_one_r():
    r = simulate(GAP_DOWN_POOL, 1.10, 1.095, 1.11, 0, 5, Direction.BUY, replays=1000, seed=1)
    assert r["avg_R"] <= -1.0 + 1e-6
    assert r["avg_R"] >= -1.0 - 1e-6  # never a *bigger* loss than the planned 1R either
    assert r["p_stop"] == 1.0
    assert r["p_green"] == 0.0


def test_gap_through_stop_short_counts_full_minus_one_r():
    r = simulate(GAP_UP_POOL, 1.10, 1.105, 1.09, 0, 5, Direction.SELL, replays=1000, seed=1)
    assert r["avg_R"] == pytest.approx(-1.0)
    assert r["p_stop"] == 1.0


def test_stop_checked_before_target_in_same_bar():
    # one bar that touches both stop and target: counts as the stop
    pool = [[]] + [[(1.0, 1.02, 0.98, 1.0)] * 2 for _ in range(5)]
    r = simulate(pool, 1.00, 0.99, 1.01, 0, 3, Direction.BUY, replays=200, seed=3)
    assert r["p_stop"] == 1.0
    assert r["p_target"] == 0.0


def test_target_hit_pays_r_at_target():
    pool = [[]] + [[(1.0, 1.03, 1.0, 1.02)] * 2 for _ in range(5)]
    r = simulate(pool, 1.00, 0.99, 1.02, 0, 3, Direction.BUY, replays=200, seed=3)
    assert r["p_target"] == 1.0
    assert r["r_at_target"] == pytest.approx(2.0)
    assert r["avg_R"] == pytest.approx(2.0)
    assert r["p_green"] == 1.0


def test_neither_marks_to_close_and_green_follows_side():
    # drifts up 0.1% a bar, never reaches stop/target
    pool = [[]] + [[(1.0, 1.001, 1.0, 1.001)] * 2 for _ in range(5)]
    up = simulate(pool, 1.00, 0.90, 1.10, 0, 3, Direction.BUY, replays=100, seed=3)
    assert up["p_neither"] == 1.0 and up["p_green"] == 1.0 and up["avg_R"] > 0
    dn = simulate(pool, 1.00, 1.10, 0.90, 0, 3, Direction.SELL, replays=100, seed=3)
    assert dn["p_neither"] == 1.0 and dn["p_green"] == 0.0 and dn["avg_R"] < 0


def test_simulate_rejects_non_positive_risk():
    with pytest.raises(ValueError):
        simulate(POOL, 1.10, 1.10, 1.11, 3, 50, Direction.BUY, replays=10)


# ---------------------------------------------------------------- history_replay

def _fixed_session(day: date, closes_highs_lows: list[tuple[float, float, float, float]]) -> list[Bar]:
    open_dt = datetime(day.year, day.month, day.day, 8, 0, tzinfo=LONDON)
    out = []
    for slot, (o, h, l, c) in enumerate(closes_highs_lows):
        t = (open_dt + timedelta(minutes=5 * slot)).astimezone(timezone.utc)
        out.append(Bar(time=t, open=o, high=h, low=l, close=c, volume=1.0))
    return out


def test_history_replay_target_stop_and_untriggered():
    base = (1.00, 1.01, 0.99, 1.00)
    # OR = slots 0..2 -> high 1.01 low 0.99; slot 3 closes 1.02 -> BUY entry 1.02
    # or_low stop 0.99 -> risk 0.03, target (2R) 1.08
    hit_t = [base] * 3 + [(1.0, 1.03, 1.0, 1.02), (1.02, 1.09, 1.01, 1.08), (1.08, 1.09, 1.07, 1.08)]
    hit_s = [base] * 3 + [(1.0, 1.03, 1.0, 1.02), (1.02, 1.03, 0.98, 1.0), (1.0, 1.01, 0.99, 1.0)]
    none_ = [base] * 6
    both = [base] * 3 + [(1.0, 1.03, 1.0, 1.02), (1.02, 1.09, 0.98, 1.0), (1.0, 1.0, 1.0, 1.0)]  # stop first
    sessions = [_fixed_session(date(2026, 4, 1) + timedelta(days=i), s)
                for i, s in enumerate([hit_t, hit_s, none_, both])]
    r = history_replay(sessions, 15, "or_low", 2.0, 5, Direction.BUY)
    assert r["sessions"] == 4
    assert r["triggered"] == 3
    assert r["target"] == 1
    assert r["stop"] == 2
    assert r["close"] == 0
    assert r["avg_R"] == pytest.approx((2.0 - 1.0 - 1.0) / 3, abs=1e-3)


def test_history_replay_close_outcome_and_sell():
    base = (1.00, 1.01, 0.99, 1.00)
    # BUY entry 1.02, stop 0.99 (risk .03); drifts to 1.035 at last slot: R = 0.5
    drift = [base] * 3 + [(1.0, 1.03, 1.0, 1.02), (1.02, 1.04, 1.01, 1.03), (1.03, 1.04, 1.02, 1.035)]
    r = history_replay([_fixed_session(date(2026, 4, 1), drift)], 15, "or_low", 2.0, 5, Direction.BUY)
    assert r["triggered"] == 1 and r["close"] == 1
    assert r["avg_R"] == pytest.approx(0.5, abs=1e-3)
    # SELL: first close below OR low 0.99 -> entry 0.98, stop or_high 1.01 (risk .03), target 0.92
    short = [base] * 3 + [(1.0, 1.0, 0.97, 0.98), (0.98, 0.985, 0.91, 0.92), (0.92, 0.93, 0.91, 0.92)]
    rs = history_replay([_fixed_session(date(2026, 4, 1), short)], 15, "or_high", 2.0, 5, Direction.SELL)
    assert rs["triggered"] == 1 and rs["target"] == 1
    assert rs["avg_R"] == pytest.approx(2.0, abs=1e-3)


def test_history_replay_no_trigger_gives_none_avg():
    base = (1.00, 1.01, 0.99, 1.00)
    r = history_replay([_fixed_session(date(2026, 4, 1), [base] * 6)], 15, "or_low", 2.0, 5, Direction.BUY)
    assert r["triggered"] == 0 and r["avg_R"] is None


# ---------------------------------------------------------------- run_time_machine

CFG = SymbolConfig(name="EURUSD", enabled=True, risk=RiskConfig(), session=SessionConfig(),
                   strategy=StrategyConfig(or_minutes=15, stop_rule="or_low", target_r=2.0))
DAY = date(2026, 4, 20)  # past 25 weekdays span the 29 Mar GMT -> BST switch
FULL_SLOTS = session_slots(CFG.session.open, CFG.session.flat_by)  # 144


def _london_bars(days: list[date], n_slots: int, seed: int = 11) -> list[Bar]:
    rng = random.Random(seed)
    out: list[Bar] = []
    for d in days:
        out.extend(_synthetic_session(d, n_slots, rng))
    return out


def _trigger_and_signal(bars: list[Bar]):
    day_bars = group_by_session_day(bars, CFG.session.timezone, CFG.session.open)[DAY]
    slot = 6
    b = day_bars[slot]
    trig = OrbTrigger(direction=Direction.BUY, entry=b.close, trigger_time=b.time, slot=slot,
                      or_high=b.close - 0.0002, or_low=b.close - 0.0020)
    return trig, plan_exit(trig, CFG.strategy.stop_rule, CFG.strategy.target_r)


def test_run_time_machine_full_flow():
    bars = _london_bars(_past_weekdays(DAY, 25) + [DAY], FULL_SLOTS)
    trig, sig = _trigger_and_signal(bars)
    r = run_time_machine(bars, DAY, trig, sig, CFG, replays=1000)
    assert r["pool_sessions"] == 25
    assert r["n_slots"] == FULL_SLOTS == 144
    assert 0.0 <= r["p_green"] <= 1.0
    assert abs(r["p_target"] + r["p_stop"] + r["p_neither"] - 1.0) < 1e-9
    assert r["bars_left"] == FULL_SLOTS - 1 - trig.slot
    assert r["history"]["sessions"] == 25
    assert r["r_at_target"] == pytest.approx(2.0)
    # deterministic for the same seed
    assert r == run_time_machine(bars, DAY, trig, sig, CFG, replays=1000)


def test_run_excludes_short_sessions_and_the_day_itself():
    past = _past_weekdays(DAY, 25)
    truncated_day = past[10]  # a day inside the window with only 70 of 144 slots
    rng = random.Random(3)
    bars = _london_bars([d for d in past if d != truncated_day], FULL_SLOTS)
    bars += _synthetic_session(truncated_day, 70, rng)
    # a short Saturday session (no full session exists for that date)
    bars += _synthetic_session(date(2026, 4, 4), 30, rng)
    bars += _london_bars([DAY], FULL_SLOTS)
    bars.sort(key=lambda b: b.time)
    trig, sig = _trigger_and_signal(bars)
    r = run_time_machine(bars, DAY, trig, sig, CFG, replays=200)
    # 25 weekdays - 1 truncated = 24 full; the short Saturday and the day itself are excluded
    assert r["pool_sessions"] == 24
    assert r["history"]["sessions"] == 24
    assert r["pool_to"] < DAY
    assert r["pool_from"] == past[0]


@pytest.mark.parametrize("rule,param", [("pct", 0.15), ("atr", 3.0)])
def test_history_stop_distance_matches_signal_distance_for_pct_and_atr(rule, param):
    # pins the unit of the pct conversion: stop_param is a PERCENT of entry, not a fraction
    bars = _london_bars(_past_weekdays(DAY, 25) + [DAY], FULL_SLOTS)
    cfg = SymbolConfig(name="EURUSD", enabled=True, risk=RiskConfig(), session=SessionConfig(),
                       strategy=StrategyConfig(or_minutes=15, stop_rule=rule, target_r=2.0))
    day_bars = group_by_session_day(bars, cfg.session.timezone, cfg.session.open)[DAY]
    b = day_bars[20]  # ATR14 needs >= 15 bars up to the trigger
    trig = OrbTrigger(direction=Direction.BUY, entry=b.close, trigger_time=b.time, slot=20,
                      or_high=b.close - 0.0002, or_low=b.close - 0.0020)
    day_list = [day_bars[i] for i in range(21)]
    sig = plan_exit(trig, rule, 2.0, session_bars=day_list, stop_param=param)
    r = run_time_machine(bars, DAY, trig, sig, cfg, replays=200)
    frac = abs(sig.entry - sig.sl) / sig.entry
    assert 0 < frac < 0.01  # sanity: a sub-1% stop, so a 100x unit error would be obvious
    trades = r["history"]["trades"]
    assert r["history"]["triggered"] > 0 and trades
    for t in trades:
        assert abs(t["entry"] - t["stop"]) / t["entry"] == pytest.approx(frac, abs=1e-4)
        assert t["stop"] < t["entry"]


def test_run_refuses_with_too_few_sessions():
    bars = _london_bars(_past_weekdays(DAY, 19) + [DAY], FULL_SLOTS)
    trig, sig = _trigger_and_signal(bars)
    with pytest.raises(ValueError, match="20"):
        run_time_machine(bars, DAY, trig, sig, CFG)


def test_run_refuses_when_entry_slot_missing_from_day():
    past = _london_bars(_past_weekdays(DAY, 25), FULL_SLOTS)
    day_bars = _london_bars([DAY], 4)  # data ends before slot 6
    bars = past + day_bars
    full = _london_bars(_past_weekdays(DAY, 25) + [DAY], FULL_SLOTS)
    trig, sig = _trigger_and_signal(full)
    with pytest.raises(ValueError, match="slot"):
        run_time_machine(bars, DAY, trig, sig, CFG)
