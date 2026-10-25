"""Monte-Carlo "Time Machine": replay a planned ORB trade before risking it.

A port of the day-trader skill's `build_pool` / `simulate` / `history_replay`
(same random draws, same structure), with the fixed 78-bar NYSE day replaced by
the configurable session window: `n_slots = session_slots(open, flat_by)` and
slots `1..n_slots-1`.

  1. Pool: for every slot 1..n_slots-1, each past *full* session's bar as ratios
     to the previous bar's close: (open, high, low, close) / prev_close.
  2. One replay starts at the entry price and walks slots k+1..last. For bar i it
     picks slot j = i + randint(-window, window), clamped to 1..n_slots-1, then
     one past bar from pool[j] (random.choice), scaled to the current price.
     The stop is checked before the target in every bar, so a bar touching both
     counts as the stop. A gap past the stop is always exactly -1R (never a
     smaller loss, and never modelled as worse than the planned 1R).
  3. Outcomes: target / stop / neither (still open at the last slot, marked to
     that slot's simulated close). green = target first, or on the right side of
     the entry at the end. R = r_at_target at the target, -1 at the stop, else
     (price at the end - entry) / risk.
  4. History: the same ORB rule re-run on every past full session.

Same pool + same seed -> identical numbers.
"""
import random
import statistics
from datetime import date

from fxbot.config import SymbolConfig
from fxbot.domain import Bar, Direction, Signal
from fxbot.sessions import SLOT_MINUTES, group_by_session_day, session_slots
from fxbot.strategy import OrbTrigger, plan_exit

MIN_SESSIONS = 20


def build_pool(sessions: list[list[Bar]], n_slots: int) -> list[list[tuple]]:
    """pool[i] = every past session's bar i as (o, h, l, c) / bar i-1's close, in date order.

    Each session is a list of bars indexed by slot (length >= n_slots). pool[0] is
    empty: slot 0 has no previous close.
    """
    pool: list[list[tuple]] = [[] for _ in range(n_slots)]
    for day_bars in sessions:
        for i in range(1, n_slots):
            pc = day_bars[i - 1].close
            b = day_bars[i]
            pool[i].append((b.open / pc, b.high / pc, b.low / pc, b.close / pc))
    return pool


def simulate(
    pool: list[list[tuple]],
    entry: float,
    stop: float,
    target: float,
    k_slot: int,
    last_slot: int,
    side: Direction,
    replays: int = 10000,
    seed: int = 19,
    window: int = 2,
) -> dict:
    """Monte Carlo replays of slots k_slot+1..last_slot from `entry`."""
    long = side == Direction.BUY
    risk = (entry - stop) if long else (stop - entry)
    if not risk > 0:
        raise ValueError(f"non-positive risk {risk} (entry={entry}, stop={stop}, side={side})")
    r_target = round(((target - entry) if long else (entry - target)) / risk, 4)
    top = len(pool) - 1

    def slot(rng: random.Random, i: int) -> int:
        return i if window == 0 else min(top, max(1, i + rng.randint(-window, window)))

    rng = random.Random(seed)
    choice = rng.choice
    outcomes: list[str] = []
    closes: list[float] = []
    for _ in range(replays):
        p = entry
        outcome = None
        for i in range(k_slot + 1, last_slot + 1):
            _o, h, l, c = choice(pool[slot(rng, i)])
            hi, lo, cl = p * h, p * l, p * c
            if outcome is None:
                if long:
                    if lo <= stop:
                        outcome = "stop"  # both inside one bar (or a gap): count the loss
                    elif hi >= target:
                        outcome = "target"
                else:
                    if hi >= stop:
                        outcome = "stop"
                    elif lo <= target:
                        outcome = "target"
            p = cl
        outcomes.append(outcome or "neither")
        closes.append(p)

    n_target = outcomes.count("target")
    n_stop = outcomes.count("stop")
    n_neither = outcomes.count("neither")
    green = sum(
        1
        for o, p in zip(outcomes, closes)
        if o == "target" or (o == "neither" and (p > entry if long else p < entry))
    )
    # a stop is always exactly -1R, even if the bar gapped far past the stop level
    rs = [
        r_target if o == "target" else -1.0 if o == "stop" else ((p - entry) if long else (entry - p)) / risk
        for o, p in zip(outcomes, closes)
    ]
    srt = sorted(closes)

    def pct(q: float) -> float:
        return srt[min(len(srt) - 1, int(q * len(srt)))]

    return {
        "replays": replays,
        "seed": seed,
        "window": window,
        "bars_left": max(0, last_slot - k_slot),
        "p_target": n_target / replays,
        "p_stop": n_stop / replays,
        "p_neither": n_neither / replays,
        "p_green": green / replays,
        "median_close": pct(0.5),
        "p5_close": pct(0.05),
        "p95_close": pct(0.95),
        "avg_R": round(statistics.mean(rs), 4),
        "r_at_target": r_target,
    }


def history_replay(
    sessions: list[list[Bar]],
    or_minutes: int,
    stop_rule: str,
    target_r: float,
    last_slot: int,
    side: Direction,
    stop_param: float | None = None,
) -> dict:
    """The ORB rule on every past full session.

    Entry = the first bar after the opening range whose close breaks it (in
    `side`'s direction, up to `last_slot`); stop by `stop_rule`, target at
    `target_r` x risk; then bar by bar, stop first, else the close at `last_slot`.
    """
    long = side == Direction.BUY
    first = or_minutes // SLOT_MINUTES
    trades: list[dict] = []
    for D in sessions:
        if first < 1 or len(D) <= last_slot or first > last_slot:
            continue
        or_high = max(b.high for b in D[:first])
        or_low = min(b.low for b in D[:first])
        kk = next(
            (i for i in range(first, last_slot + 1) if (D[i].close > or_high if long else D[i].close < or_low)),
            None,
        )
        if kk is None:
            continue
        trig = OrbTrigger(direction=side, entry=D[kk].close, trigger_time=D[kk].time, slot=kk,
                          or_high=or_high, or_low=or_low)
        try:
            sig = plan_exit(trig, stop_rule, target_r, session_bars=D[: kk + 1], stop_param=stop_param)
        except ValueError:
            continue  # non-positive risk / missing data: no trade
        e, s, t = sig.entry, sig.sl, sig.tp
        risk = (e - s) if long else (s - e)
        outcome = None
        for b in D[kk + 1 : last_slot + 1]:
            if (b.low <= s) if long else (b.high >= s):
                outcome = "stop"
                break
            if (b.high >= t) if long else (b.low <= t):
                outcome = "target"
                break
        cl = D[last_slot].close
        if outcome == "target":
            r = ((t - e) if long else (e - t)) / risk
        elif outcome == "stop":
            r = -1.0
        else:
            r = ((cl - e) if long else (e - cl)) / risk
        trades.append({"time": D[kk].time, "entry": e, "stop": s, "target": t,
                       "outcome": outcome or "close", "R": round(r, 4)})
    return {
        "sessions": len(sessions),
        "triggered": len(trades),
        "target": sum(1 for x in trades if x["outcome"] == "target"),
        "stop": sum(1 for x in trades if x["outcome"] == "stop"),
        "close": sum(1 for x in trades if x["outcome"] == "close"),
        "green": sum(1 for x in trades if x["R"] > 0),
        "avg_R": round(statistics.mean(x["R"] for x in trades), 4) if trades else None,
        "trades": trades,
    }


def run_time_machine(
    bars: list[Bar],
    day: date,
    trigger: OrbTrigger,
    signal: Signal,
    cfg: SymbolConfig,
    replays: int = 10000,
    seed: int = 19,
    window: int = 2,
) -> dict:
    """Replay `signal` (entered at `trigger.slot` on `day`) over the rest of the session.

    The pool is every full session (all `n_slots` slots present) strictly before
    `day`. Raises ValueError if fewer than 20 full sessions exist, if the entry
    slot is not in `day`'s data, or if no slots remain after the entry.
    """
    sess = cfg.session
    n_slots = session_slots(sess.open, sess.flat_by)
    last = n_slots - 1
    k = trigger.slot
    if not 0 <= k < last:
        raise ValueError(f"entry slot {k} leaves no slots to replay (session has {n_slots} slots)")

    days = group_by_session_day(bars, sess.timezone, sess.open)
    if k not in days.get(day, {}):
        raise ValueError(f"entry slot {k} is not in the data for {day}")

    full_days = [d for d in sorted(days) if d < day and all(i in days[d] for i in range(n_slots))]
    full = [[days[d][i] for i in range(n_slots)] for d in full_days]
    if len(full) < MIN_SESSIONS:
        raise ValueError(f"only {len(full)} full session(s) before {day}; the time machine needs at least {MIN_SESSIONS}")

    pool = build_pool(full, n_slots)
    mc = simulate(pool, signal.entry, signal.sl, signal.tp, k, last, signal.direction,
                  replays=replays, seed=seed, window=window)

    # History uses the configured stop rule; pct/atr have no config parameter, so
    # replay them as a percent-of-entry stop equal to this signal's own distance.
    rule = cfg.strategy.stop_rule
    stop_param = None
    if rule in ("pct", "atr"):
        rule = "pct"
        stop_param = 100.0 * abs(signal.entry - signal.sl) / signal.entry
    history = history_replay(full, cfg.strategy.or_minutes, rule, cfg.strategy.target_r, last,
                             signal.direction, stop_param=stop_param)

    return dict(
        mc,
        n_slots=n_slots,
        pool_sessions=len(full),
        pool_from=full_days[0],
        pool_to=full_days[-1],
        history=history,
    )
