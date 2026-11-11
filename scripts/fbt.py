"""fbt: futures backtester with realistic fills, costs, a look-ahead audit and
out-of-sample / null-hypothesis checks. Research only: never sends orders.

Usage:
  python -I fbt.py --data bars.csv --symbol NQ --strategy my_strat.py --out out/run1
       [--contracts 1 | --risk-usd 500] [--slip-ticks 1] [--commission 2.25]
       [--oos-frac 0.3] [--start 2025-01-01] [--end 2026-06-30] [--params '{"k": 2}']
       [--walk-forward 5] [--naive] [--seed 7]

bars.csv: ts,open,high,low,close[,volume]   (ts parseable by pandas; keep the tz)
Strategy file: defines signals(df, **params) -> DataFrame with columns
  entry  (+1 long / -1 short / 0) decided at the CLOSE of that bar
  stop   (price, required for every entry)    target (price or NaN)
  max_bars (optional int, exit at close after this many bars)
and text constants HYPOTHESIS, REGIME, FAILURE_CONDITIONS. Optional PARAMS, PARAM_GRID.
"""
import argparse, hashlib, importlib.util, itertools, json, math, os, sys, time
import numpy as np
import pandas as pd

VERSION = "1.2.1"
HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- inputs
def load_specs():
    return json.load(open(os.path.join(HERE, "..", "assets", "contract_specs.json")))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def load_bars(path, start=None, end=None):
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["ts"], utc=True) if df["ts"].astype(str).str.contains(r"[+-]\d\d:\d\d$|Z$").any() \
        else pd.to_datetime(df["ts"])
    df.index = ts
    df = df[[c for c in ("open", "high", "low", "close", "volume") if c in df.columns]].astype(float)
    if start: df = df[df.index >= pd.Timestamp(start, tz=df.index.tz)]
    if end: df = df[df.index <= pd.Timestamp(end, tz=df.index.tz)]
    return df


def load_strategy(path):
    spec = importlib.util.spec_from_file_location("strategy", path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    if not hasattr(m, "signals"):
        raise SystemExit("strategy file must define signals(df, **params)")
    return m


# ---------------------------------------------------------------- data checks
def data_checks(df, spec):
    issues = []
    def add(level, what, n, ex=None):
        if n: issues.append({"level": level, "check": what, "count": int(n), "example": ex})
    add("ERROR", "duplicate timestamps", df.index.duplicated().sum())
    add("ERROR", "timestamps not increasing", (np.diff(df.index.asi8) <= 0).sum())
    nan = df[["open", "high", "low", "close"]].isna().any(axis=1)
    add("ERROR", "NaN prices", nan.sum(), str(df.index[nan.values][0]) if nan.any() else None)
    bad = (df.low > df[["open", "close"]].min(axis=1) + 1e-9) | (df.high < df[["open", "close"]].max(axis=1) - 1e-9)
    add("ERROR", "OHLC inconsistent (low>min(o,c) or high<max(o,c))", bad.sum(),
        str(df.index[bad.values][0]) if bad.any() else None)
    tick = spec["tick"]
    off = (np.abs(df.close / tick - np.round(df.close / tick)) > 0.01)
    add("WARN", "close not on tick grid (feed may be adjusted/averaged)", off.sum())
    if "volume" in df:
        add("WARN", "zero-volume bars", (df.volume <= 0).sum())
    rng = (df.high - df.low).rolling(50, min_periods=10).median()
    gap = (df.open - df.close.shift(1)).abs()
    jumps = gap > 8 * rng
    add("WARN", "open-vs-prev-close jumps > 8x median range (roll / data hole / news)", jumps.sum(),
        [str(t) for t in df.index[jumps.values][:5]])
    return issues


# ---------------------------------------------------------------- simulator
def simulate(df, sig, spec, slip_ticks, commission, contracts=1, risk_usd=None, naive=False, worst_case=True,
             touch=False):
    """Bar-by-bar. Signal at bar i -> fill at OPEN of bar i+1 (+slippage).
    Stop and target are resting orders checked on each bar's high/low; if both
    are hit in the same bar the stop is assumed first (worst_case).
    Targets are snapped to the tick FARTHER from entry and, unless touch=True,
    need a 1-tick trade-through to fill."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    ent = sig["entry"].fillna(0).to_numpy().astype(int)
    stp = sig["stop"].to_numpy(dtype=float)
    tgt = sig["target"].to_numpy(dtype=float) if "target" in sig else np.full(len(df), np.nan)
    mxb = sig["max_bars"].to_numpy(dtype=float) if "max_bars" in sig else np.full(len(df), np.nan)
    pv, tick = spec["point_value"], spec["tick"]
    slip = 0.0 if naive else slip_ticks * tick
    comm = 0.0 if naive else commission
    trades, skipped = [], {"no_stop": 0, "stop_wrong_side": 0, "size_zero": 0}
    pos = 0
    n = len(df)
    for i in range(1, n):
        if pos == 0:
            j = i - 1
            if ent[j] != 0:
                side = ent[j]
                if np.isnan(stp[j]):
                    skipped["no_stop"] += 1; continue
                fill = (c[j] if naive else o[i]) + side * slip
                risk_pts = (fill - stp[j]) * side
                if risk_pts <= 0:
                    skipped["stop_wrong_side"] += 1; continue
                qty = contracts if risk_usd is None else int(risk_usd // (risk_pts * pv + 2 * comm))
                if qty <= 0:
                    skipped["size_zero"] += 1; continue
                t_px = tgt[j]
                if not naive and not np.isnan(t_px):
                    k_t = t_px / tick
                    t_px = (math.ceil(k_t - 1e-9) if side > 0 else math.floor(k_t + 1e-9)) * tick
                pos, e_px, e_i, s_px, q = side, fill, (j if naive else i), stp[j], qty
                mb = mxb[j]
        if pos != 0:
            if naive:       # naive baseline: only looks at closes
                hit_s = (c[i] - s_px) * pos <= 0
                hit_t = not np.isnan(t_px) and (c[i] - t_px) * pos >= 0
                x_px, why = (s_px, "stop") if hit_s else ((t_px, "target") if hit_t else (None, None))
            else:
                x_px = why = None
                gap_s = (o[i] - s_px) * pos <= 0
                if gap_s and i > e_i:                  # opened through the stop
                    x_px, why = o[i] - pos * slip, "stop_gap"
                else:
                    hit_s = (l[i] <= s_px) if pos > 0 else (h[i] >= s_px)
                    thr = 0.0 if touch else tick       # trade-through needed for a limit fill
                    hit_t = (not np.isnan(t_px)) and ((h[i] >= t_px + thr - 1e-9) if pos > 0
                                                       else (l[i] <= t_px - thr + 1e-9))
                    if hit_s and (worst_case or not hit_t):
                        x_px, why = s_px - pos * slip, ("stop_ambiguous" if hit_t else "stop")
                    elif hit_t:
                        x_px, why = t_px, ("target_ambiguous" if hit_s else "target")  # limit: no slippage
            held = i - e_i + (0 if naive else 1)
            if x_px is None and not np.isnan(mb) and held >= mb:
                x_px, why = c[i] - pos * slip, "time"
            if x_px is None and i == n - 1:
                x_px, why = c[i] - pos * slip, "end_of_data"
            if x_px is not None:
                pts = (x_px - e_px) * pos
                pnl = pts * pv * q - 2 * comm * q
                risk = abs(e_px - s_px) * pv * q
                trades.append({"entry_ts": str(df.index[e_i]), "exit_ts": str(df.index[i]), "side": pos, "qty": q,
                               "entry": round(e_px, 6), "stop": s_px, "target": None if np.isnan(t_px) else t_px,
                               "exit": round(x_px, 6), "reason": why, "bars": held,
                               "max_bars": None if np.isnan(mb) else int(mb), "pnl": round(pnl, 2),
                               "r": round(pnl / risk, 4) if risk > 0 else None})
                pos = 0
    return pd.DataFrame(trades), skipped


# ---------------------------------------------------------------- time helpers
def ts_series(strs):
    """Trade timestamps (strings) -> comparable Timestamps (UTC if tz-aware)."""
    s = pd.Series(list(strs))
    return pd.to_datetime(s, utc=True) if s.astype(str).str.contains(r"[+-]\d\d:\d\d$").any() else pd.to_datetime(s)


def ts_cmp(t):
    return t.tz_convert("UTC") if t.tzinfo is not None else t


def after(tr, t):
    """Trades whose entry is at/after timestamp t."""
    if len(tr) == 0:
        return tr
    return tr[(ts_series(tr.entry_ts) >= ts_cmp(t)).to_numpy()]


# ---------------------------------------------------------------- metrics
def metrics(tr, start_equity=50000.0):
    if tr is None or len(tr) == 0:
        return {"trades": 0}
    p = tr.pnl.to_numpy()
    eq = np.cumsum(p)
    dd = eq - np.maximum.accumulate(np.concatenate([[0], eq]))[1:]
    wins, losses = p[p > 0], p[p <= 0]
    streak = cur = 0
    for v in p:
        cur = cur + 1 if v <= 0 else 0; streak = max(streak, cur)
    ex = ts_series(tr.exit_ts)
    if ex.dt.tz is not None:
        ex = ex.dt.tz_convert("America/New_York")
    daily = tr.assign(d=ex.dt.date.to_numpy()).groupby("d").pnl.sum()
    sharpe = float(daily.mean() / daily.std() * math.sqrt(252)) if len(daily) > 2 and daily.std() > 0 else None
    return {
        "trades": int(len(p)), "net_usd": round(float(p.sum()), 2),
        "win_rate_pct": round(100 * len(wins) / len(p), 1),
        "avg_win_usd": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss_usd": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.sum() < 0 else None,
        "expectancy_usd": round(float(p.mean()), 2),
        "expectancy_r": round(float(tr.r.mean()), 4) if tr.r.notna().any() else None,
        "max_drawdown_usd": round(float(dd.min()), 2),
        "max_drawdown_pct_of_start": round(100 * float(dd.min()) / start_equity, 2),
        "longest_losing_streak": int(streak), "avg_bars_held": round(float(tr.bars.mean()), 2),
        "sharpe_daily_ann": round(sharpe, 3) if sharpe is not None else None,
        "exit_reasons": tr.reason.value_counts().to_dict(),
    }


def monte_carlo(tr, sims, rng):
    if len(tr) < 5:
        return None
    p = tr.pnl.to_numpy()
    nets, dds = [], []
    for _ in range(sims):
        s = rng.choice(p, size=len(p), replace=True)
        eq = np.cumsum(s); nets.append(eq[-1])
        dds.append((eq - np.maximum.accumulate(np.concatenate([[0], eq]))[1:]).min())
    q = lambda a, k: round(float(np.percentile(a, k)), 2)
    return {"sims": sims, "net_p5": q(nets, 5), "net_p50": q(nets, 50), "net_p95": q(nets, 95),
            "prob_net_le_0_pct": round(100 * float(np.mean(np.array(nets) <= 0)), 1),
            "max_dd_p50": q(dds, 50), "max_dd_p5_worst": q(dds, 5)}


def random_null(df, tr, spec, args, rng, sims=200):
    """Matched random baseline: same number of trades; each random trade copies one
    real trade's stop distance, target distance and HOLD LENGTH (sample k -> all three);
    entries are drawn only from bars whose fill lands in the same ET hours the strategy
    actually traded. Random direction. p = share of random runs with expectancy >= ours."""
    if len(tr) < 10:
        return None
    sd = (tr.entry - tr.stop).abs().to_numpy()
    td = (tr.target - tr.entry).abs().to_numpy(dtype=float) if tr.target.notna().any() else None
    # PLANNED max hold of each copied trade (v1.1.0 used the realized hold, which force-closed
    # random copies early, shrank the null's spread and let a coin flip pass with p=0.005)
    hold = tr["max_bars"].to_numpy(dtype=float) if "max_bars" in tr else np.full(len(tr), np.nan)
    fills = ts_series(tr.entry_ts)
    if fills.dt.tz is not None:
        fills = fills.dt.tz_convert("America/New_York")
    hours = sorted(set(int(x) for x in fills.dt.hour))
    et = df.index.tz_convert("America/New_York") if df.index.tz is not None else df.index
    fill_hour = np.asarray(et.hour)[1:]                    # signal bar j fills on bar j+1
    pool = np.where(np.isin(fill_hour, hours))[0]
    if len(pool) < len(tr):
        return None
    # Volatility matching: express each real trade's stop/target distance in units of the
    # 20-bar average range at its signal bar, and rescale at each random bar. Raw-point
    # distances moved to a different volatility regime make the null lose by itself
    # (v1.1.0: a coin flip with range-sized stops "beat" it with p=0.005).
    vol = (df.high - df.low).rolling(20, min_periods=5).mean().to_numpy()
    pos = df.index.get_indexer(pd.DatetimeIndex(ts_series(tr.entry_ts)).tz_convert(df.index.tz)
                               if df.index.tz is not None else pd.DatetimeIndex(ts_series(tr.entry_ts)))
    sig_vol = vol[np.clip(pos - 1, 0, len(df) - 1)]
    ok_v = np.isfinite(sig_vol) & (sig_vol > 0) & (pos > 0)
    if ok_v.sum() < 10:
        return None
    sd = sd[ok_v] / sig_vol[ok_v]
    td = None if td is None else td[ok_v] / sig_vol[ok_v]
    hold = hold[ok_v]
    pool = pool[np.isfinite(vol[pool]) & (vol[pool] > 0)]
    # Compare in R (P&L / initial risk), not dollars, so trade SIZE differences between the
    # strategy and the random copies can't masquerade as edge (independent review, 1.2.1).
    ours = tr.r.mean(); ours_usd = tr.pnl.mean(); better = 0; exps = []; exps_usd = []
    c = df.close.to_numpy(); n = len(df)
    for _ in range(sims):
        e = np.zeros(n); s = np.full(n, np.nan); t = np.full(n, np.nan); mb = np.full(n, np.nan)
        idx = np.sort(rng.choice(pool, size=min(len(pool), len(tr) * 3), replace=False))
        k = rng.integers(0, len(sd), size=len(idx)); d = rng.choice([-1, 1], size=len(idx))
        e[idx] = d; s[idx] = c[idx] - d * sd[k] * vol[idx]; mb[idx] = hold[k]
        if td is not None:
            tt = np.nan_to_num(td[k], nan=np.inf); t[idx] = c[idx] + d * tt * vol[idx]
            t[np.isinf(t)] = np.nan
        sig = pd.DataFrame({"entry": e, "stop": s, "target": t, "max_bars": mb}, index=df.index)
        rt, _ = simulate(df, sig, spec, args.slip_ticks, args.commission, args.contracts, args.risk_usd,
                         touch=args.touch_fills)
        if len(rt) == 0: continue
        rt = rt.iloc[: len(tr)]
        exps.append(rt.r.mean()); exps_usd.append(rt.pnl.mean()); better += rt.r.mean() >= ours
    return {"sims": len(exps), "compared_in": "R (P&L / initial risk)",
            "our_expectancy_r": round(float(ours), 4), "null_expectancy_r_p50": round(float(np.median(exps)), 4),
            "null_expectancy_r_p95": round(float(np.percentile(exps, 95)), 4),
            "our_expectancy_usd": round(float(ours_usd), 2),
            "null_expectancy_usd_p50": round(float(np.median(exps_usd)), 2),
            "p_value": round((better + 1) / (len(exps) + 1), 4),
            "matched_on": f"ET fill hours {hours}; per-trade stop/target in 20-bar-range units; planned max hold"}


# ---------------------------------------------------------------- look-ahead audit
def lookahead_audit(df, strat, params, cuts=8):
    full = strat.signals(df, **params)
    cols = [k for k in ("entry", "stop", "target", "max_bars") if k in full]
    n = len(df); bad = []
    for c in np.linspace(n * 0.3, n - 2, cuts).astype(int):
        part = strat.signals(df.iloc[:c].copy(), **params)
        for k in cols:
            a = full[k].iloc[:c].to_numpy(dtype=float); b = part[k].to_numpy(dtype=float)
            diff = ~((a == b) | (np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-9))
            if diff.any():
                r = int(np.argmax(diff))
                bad.append({"cut_at_row": int(c), "column": k, "first_changed_row": r,
                            "ts": str(df.index[r]), "full_data": a[r], "truncated": b[r]})
                break
    return {"cuts": cuts, "pass": not bad, "violations": bad[:5]}


# ---------------------------------------------------------------- walk-forward
def walk_forward(df, strat, spec, args, folds):
    grid = getattr(strat, "PARAM_GRID", None)
    if not grid:
        return {"skipped": "strategy has no PARAM_GRID"}
    keys = list(grid); combos = [dict(zip(keys, v)) for v in itertools.product(*grid.values())]
    n = len(df); edges = np.linspace(0, n, folds + 2).astype(int)
    oos_trades, chosen = [], []
    for f in range(folds):
        tr_df, te_df = df.iloc[edges[f]:edges[f + 1]], df.iloc[edges[f + 1]:edges[f + 2]]
        best, best_score = None, -np.inf
        for p in combos:
            t, _ = simulate(tr_df, strat.signals(tr_df.copy(), **p), spec, args.slip_ticks, args.commission,
                            args.contracts, args.risk_usd, touch=args.touch_fills)
            if len(t) >= 10 and t.pnl.mean() > best_score:
                best, best_score = p, t.pnl.mean()
        if best is None:
            chosen.append({"fold": f, "params": None}); continue
        # signals on train+test so indicators are warm, keep test-period trades only
        both = df.iloc[edges[f]:edges[f + 2]]
        t, _ = simulate(both, strat.signals(both.copy(), **best), spec, args.slip_ticks, args.commission,
                        args.contracts, args.risk_usd, touch=args.touch_fills)
        t = after(t, te_df.index[0])
        oos_trades.append(t); chosen.append({"fold": f, "params": best, "test_trades": int(len(t)),
                                             "test_net": round(float(t.pnl.sum()), 2)})
    allt = pd.concat(oos_trades) if oos_trades else pd.DataFrame()
    return {"folds": folds, "chosen": chosen, "oos": metrics(allt)}


# ---------------------------------------------------------------- verdict
def verdict(audit, checks, is_m, oos_m, null, cost, mc, wf, amb=None, trials=1):
    reasons = []
    if not audit["pass"]:
        return "INVALID_LOOKAHEAD", ["signals change when future bars are removed -> the strategy peeks ahead"]
    if any(i["level"] == "ERROR" for i in checks):
        return "INVALID_DATA", ["data integrity errors, fix the data first"]
    if oos_m.get("trades", 0) < 30:
        return "INSUFFICIENT_DATA", [f"only {oos_m.get('trades', 0)} out-of-sample trades (< 30)"]
    if oos_m["expectancy_usd"] <= 0:
        if amb and (amb.get("best_case_oos_expectancy_usd") or 0) > 0 and amb["pct_of_trades"] >= 5:
            return "INCONCLUSIVE_INTRABAR", [f"worst case {oos_m['expectancy_usd']} but best case "
                                             f"{amb['best_case_oos_expectancy_usd']} USD/trade: {amb['pct_of_trades']}% of trades "
                                             "hit stop and target in one bar; re-test on lower-timeframe bars"]
        return "REJECTED", [f"out-of-sample expectancy {oos_m['expectancy_usd']} USD/trade <= 0 after costs"]
    ok = True
    alpha = 0.05 / max(1, trials)
    if null is None or null["p_value"] >= alpha:
        ok = False; reasons.append(f"not better than matched random entries (p={None if null is None else null['p_value']}, "
                                   f"needs < {alpha:.4g} for {trials} trial(s))")
    worst = cost[-1]
    if worst["oos_expectancy_usd"] is None or worst["oos_expectancy_usd"] <= 0:
        ok = False; reasons.append(f"edge disappears at {worst['slip_ticks']} ticks slippage")
    if mc and mc["prob_net_le_0_pct"] > 10:
        ok = False; reasons.append(f"Monte Carlo: {mc['prob_net_le_0_pct']}% chance net <= 0")
    if wf and "oos" in wf and wf["oos"].get("trades", 0) and wf["oos"]["expectancy_usd"] <= 0:
        ok = False; reasons.append("walk-forward out-of-sample expectancy <= 0")
    if is_m.get("expectancy_usd", 0) > 0 and oos_m["expectancy_usd"] < 0.3 * is_m["expectancy_usd"]:
        reasons.append("out-of-sample expectancy < 30% of in-sample (possible overfit)")
    if ok:
        return "CANDIDATE_PAPER_TRADE", reasons + ["passed backtest gates; NOT a validated edge until paper trading confirms it"]
    return "BACKTESTED_NOT_VALIDATED", reasons


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True); ap.add_argument("--symbol", required=True)
    ap.add_argument("--strategy", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--params", default=None, help="JSON dict, overrides strategy PARAMS")
    ap.add_argument("--contracts", type=int, default=1)
    ap.add_argument("--risk-usd", type=float, default=None, help="size by risk instead of fixed contracts")
    ap.add_argument("--slip-ticks", type=float, default=1.0, help="per side on market/stop fills")
    ap.add_argument("--commission", type=float, default=None, help="USD per contract per side (default: specs)")
    ap.add_argument("--oos-frac", type=float, default=0.3)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--walk-forward", type=int, default=0, help="number of folds (needs PARAM_GRID)")
    ap.add_argument("--mc-sims", type=int, default=2000)
    ap.add_argument("--null-sims", type=int, default=200)
    ap.add_argument("--naive", action="store_true", help="baseline only: close fills, no costs, close-only stops")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--touch-fills", action="store_true",
                    help="targets fill on a touch (optimistic; default needs a 1-tick trade-through)")
    ap.add_argument("--trials", type=int, default=1,
                    help="hypotheses tried so far (ledger count); null gate uses alpha 0.05/trials (Bonferroni)")
    args = ap.parse_args()
    t0 = time.time()
    specs = load_specs()
    if args.symbol not in specs:
        raise SystemExit(f"unknown symbol {args.symbol}; known: {list(specs)}")
    spec = specs[args.symbol]
    if args.commission is None:
        args.commission = spec["commission_per_side_default"]
    df = load_bars(args.data, args.start, args.end)
    px = df[["open", "high", "low", "close"]]
    off = (px / spec["tick"] - np.round(px / spec["tick"])).abs().to_numpy().max()
    if 0 < off < 0.01:            # float noise (e.g. Yahoo 2000.1000002): snap to the tick grid
        df[["open", "high", "low", "close"]] = np.round(px / spec["tick"]) * spec["tick"]
    strat = load_strategy(args.strategy)
    params = dict(getattr(strat, "PARAMS", {}))
    if args.params: params.update(json.loads(args.params))
    rng = np.random.default_rng(args.seed)

    checks = data_checks(df, spec)
    audit = lookahead_audit(df, strat, params)
    sig = strat.signals(df.copy(), **params)
    tr, skipped = simulate(df, sig, spec, args.slip_ticks, args.commission, args.contracts, args.risk_usd,
                           naive=args.naive, touch=args.touch_fills)
    split_ts = df.index[int(len(df) * (1 - args.oos_frac))]
    oos_tr = after(tr, split_ts)
    is_tr = tr.drop(oos_tr.index) if len(tr) else tr
    res = {"tool": "futures-backtesting", "version": VERSION, "mode": "naive" if args.naive else "realistic",
           "command": " ".join(sys.argv), "symbol": args.symbol, "spec": spec,
           "data": {"file": os.path.abspath(args.data), "sha16": sha(args.data), "bars": len(df),
                    "first": str(df.index[0]), "last": str(df.index[-1]), "oos_starts": str(split_ts)},
           "strategy": {"file": os.path.abspath(args.strategy), "sha16": sha(args.strategy), "params": params,
                        "hypothesis": getattr(strat, "HYPOTHESIS", "MISSING"),
                        "regime": getattr(strat, "REGIME", "MISSING"),
                        "failure_conditions": getattr(strat, "FAILURE_CONDITIONS", "MISSING")},
           "costs": {"slip_ticks_per_side": args.slip_ticks, "commission_per_side": args.commission,
                     "sizing": f"risk {args.risk_usd} USD" if args.risk_usd else f"{args.contracts} contract(s)",
                     "target_fills": "touch" if args.touch_fills else "1-tick trade-through", "trials": args.trials},
           "data_checks": checks, "lookahead_audit": audit, "skipped_signals": skipped,
           "all": metrics(tr), "in_sample": metrics(is_tr), "out_of_sample": metrics(oos_tr)}
    if not args.naive:
        cost = []
        for s in sorted({0, args.slip_ticks, 2 * max(args.slip_ticks, 1), 3 * max(args.slip_ticks, 1)}):
            t2, _ = simulate(df, sig, spec, s, args.commission, args.contracts, args.risk_usd, touch=args.touch_fills)
            o2 = after(t2, split_ts)
            cost.append({"slip_ticks": s, "all_net_usd": round(float(t2.pnl.sum()), 2) if len(t2) else 0.0,
                         "oos_expectancy_usd": round(float(o2.pnl.mean()), 2) if len(o2) else None})
        res["cost_sensitivity"] = cost
        # same-bar stop+target: order unknown on these bars. Report the optimistic bound too.
        amb = int((tr.reason == "stop_ambiguous").sum()) if len(tr) else 0
        tb, _ = simulate(df, sig, spec, args.slip_ticks, args.commission, args.contracts, args.risk_usd, worst_case=False,
                         touch=args.touch_fills)
        ob = after(tb, split_ts)
        res["intrabar_ambiguity"] = {
            "trades_with_stop_and_target_in_same_bar": amb,
            "pct_of_trades": round(100 * amb / len(tr), 1) if len(tr) else 0.0,
            "worst_case_oos_expectancy_usd": res["out_of_sample"].get("expectancy_usd"),
            "best_case_oos_expectancy_usd": round(float(ob.pnl.mean()), 2) if len(ob) else None,
            "note": "verdict uses worst case; if the bounds straddle 0, re-test on lower-timeframe data"}
        res["monte_carlo_oos"] = monte_carlo(oos_tr, args.mc_sims, rng)
        oos_df = df[df.index >= split_ts]
        res["random_entry_null_oos"] = random_null(oos_df, oos_tr, spec, args, rng, args.null_sims)
        res["walk_forward"] = walk_forward(df, strat, spec, args, args.walk_forward) if args.walk_forward else None
        v, why = verdict(audit, checks, res["in_sample"], res["out_of_sample"], res["random_entry_null_oos"],
                         cost, res["monte_carlo_oos"], res["walk_forward"], res["intrabar_ambiguity"], args.trials)
    else:
        v, why = "NAIVE_BASELINE", ["naive mode: no costs, close fills; not a valid test"]
    res["verdict"] = v; res["verdict_reasons"] = why
    res["seconds"] = round(time.time() - t0, 2)
    os.makedirs(args.out, exist_ok=True)
    tr.to_csv(os.path.join(args.out, "trades.csv"), index=False)
    json.dump(res, open(os.path.join(args.out, "report.json"), "w"), indent=2, default=str)
    write_md(res, os.path.join(args.out, "report.md"))
    o = res["out_of_sample"]
    print(json.dumps({"verdict": v, "trades": res["all"].get("trades", 0), "net_usd": res["all"].get("net_usd"),
                      "oos_trades": o.get("trades", 0), "oos_expectancy_usd": o.get("expectancy_usd"),
                      "lookahead_pass": audit["pass"], "seconds": res["seconds"]}))


def write_md(r, path):
    L = [f"# Backtest report: {r['symbol']} ({r['mode']})", "",
         f"**Verdict: {r['verdict']}**", ""] + [f"- {x}" for x in r["verdict_reasons"]] + ["",
         "## Hypothesis", r["strategy"]["hypothesis"], "", f"Regime: {r['strategy']['regime']}", "",
         f"Failure conditions: {r['strategy']['failure_conditions']}", "",
         "## Reproduce", "```", r["command"], "```",
         f"data sha16 {r['data']['sha16']} · strategy sha16 {r['strategy']['sha16']} · fbt {r['version']}", "",
         f"Bars {r['data']['bars']} from {r['data']['first']} to {r['data']['last']}; out-of-sample from {r['data']['oos_starts']}.",
         f"Costs: {r['costs']}", "", "## Results", "| metric | all | in-sample | out-of-sample |", "|---|---|---|---|"]
    keys = [k for k in r["all"] if k != "exit_reasons"] if r["all"].get("trades") else ["trades"]
    for k in keys:
        L.append(f"| {k} | {r['all'].get(k)} | {r['in_sample'].get(k)} | {r['out_of_sample'].get(k)} |")
    L += ["", f"Look-ahead audit: {'PASS' if r['lookahead_audit']['pass'] else 'FAIL'} {r['lookahead_audit']['violations'] or ''}",
          f"Data checks: {r['data_checks'] or 'clean'}", f"Skipped signals: {r['skipped_signals']}"]
    for k in ("intrabar_ambiguity", "cost_sensitivity", "monte_carlo_oos", "random_entry_null_oos", "walk_forward"):
        if r.get(k) is not None:
            L += ["", f"## {k}", "```", json.dumps(r[k], indent=1, default=str), "```"]
    L += ["", "_Backtest results are not a validated edge. Next step for a CANDIDATE is paper trading with the same rules._"]
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
