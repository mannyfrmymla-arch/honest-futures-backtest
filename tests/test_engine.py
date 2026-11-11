"""Known-answer tests for fbt.py: every dollar figure below was worked out by hand.
Run: python -I tests/test_engine.py   (exit 0 = all pass)"""
import os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import fbt  # noqa: E402

SPECS = fbt.load_specs()
fails = 0


def check(name, got, want, tol=1e-6):
    global fails
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got} want {want}")
    fails += 0 if ok else 1


def frame(rows):
    idx = pd.date_range("2026-01-05 09:30", periods=len(rows), freq="h", tz="America/New_York")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)


# NQ: tick 0.25, $20/pt, commission 2.50/side, slippage 1 tick on market/stop fills
bars = frame([
    [100, 101, 99, 100],          # 0 signal LONG  stop 98  target 104
    [100.5, 102, 100, 101.5],     # 1 fill 100.75
    [101.5, 104.5, 101, 104],     # 2 target 104 -> +60 ; signal SHORT stop 106 target 96
    [103.75, 106.5, 103, 106],    # 3 fill 103.5, stop -> 106.25 -> -60 ; signal LONG stop 105 tgt 110
    [105.5, 106, 105.25, 105.5],  # 4 fill 105.75
    [104, 104.5, 103, 104],       # 5 GAP below stop: exit at open 104-0.25 -> -45 ; signal LONG stop 102 tgt 106
    [104, 106.5, 101.5, 105],     # 6 fill 104.25; stop AND target in bar -> stop 101.75 -> -55 ; signal LONG stop 100, max_bars 2
    [105, 105.5, 104.5, 105.25],  # 7 fill 105.25 (held 1)
    [105.25, 106, 105, 105.75],   # 8 held 2 -> exit close 105.75-0.25=105.5 -> 0
    [105.75, 106, 105.5, 105.75],
])
sig = pd.DataFrame(index=bars.index, data={"entry": 0, "stop": np.nan, "target": np.nan, "max_bars": np.nan})
for i, e, s, t, mb in [(0, 1, 98, 104, np.nan), (2, -1, 106, 96, np.nan), (3, 1, 105, 110, np.nan),
                       (5, 1, 102, 106, np.nan), (6, 1, 100, np.nan, 2)]:
    sig.iloc[i] = [e, s, t, mb]

tr, sk = fbt.simulate(bars, sig, SPECS["NQ"], slip_ticks=1, commission=2.50)
check("NQ trade count", len(tr), 5)
check("NQ t1 long target pnl", tr.pnl[0], 60.0)
check("NQ t1 R", tr.r[0], round(60 / 55, 4))
check("NQ t2 short stop pnl", tr.pnl[1], -60.0)
check("NQ t3 gap-through-stop pnl", tr.pnl[2], -45.0)
check("NQ t3 reason", tr.reason[2], "stop_gap")
check("NQ t4 stop+target same bar -> stop (flagged ambiguous)", tr.reason[3], "stop_ambiguous")
check("NQ t4 pnl", tr.pnl[3], -55.0)
check("NQ t5 time exit pnl", tr.pnl[4], 0.0)
check("NQ t5 bars held", tr.bars[4], 2)
check("NQ total", tr.pnl.sum(), -100.0)

tro, _ = fbt.simulate(bars, sig, SPECS["NQ"], slip_ticks=1, commission=2.50, worst_case=False)
check("NQ t4 optimistic bound -> target 106 (+30)", tro.pnl[3], 30.0)

trn, _ = fbt.simulate(bars, sig, SPECS["NQ"], slip_ticks=1, commission=2.50, naive=True)
check("naive t1 (close fill, no costs) pnl", trn.pnl[0], 80.0)

# GC risk sizing: $100/pt, tick 0.10, commission 2.50/side
g = frame([[2000, 2001, 1999, 2000.0], [2000.0, 2002, 1999.5, 2001], [2001, 2010.5, 2000.5, 2010]])
gs = pd.DataFrame(index=g.index, data={"entry": [1, 0, 0], "stop": [1995.0, np.nan, np.nan],
                                       "target": [2010.0, np.nan, np.nan]})
t1, _ = fbt.simulate(g, gs, SPECS["GC"], slip_ticks=1, commission=2.50, risk_usd=1000)
check("GC risk $1000 -> qty (risk 5.1pt*100+5=515/contract)", t1.qty[0], 1)
t4, _ = fbt.simulate(g, gs, SPECS["GC"], slip_ticks=1, commission=2.50, risk_usd=2100)
check("GC risk $2100 -> qty", t4.qty[0], 4)
check("GC 4 lots target pnl (9.9pt*100*4 - 20)", t4.pnl[0], 3940.0)

# MGC / MNQ point values
check("MGC point value", SPECS["MGC"]["point_value"], 10.0)
check("MNQ tick value", SPECS["MNQ"]["tick"] * SPECS["MNQ"]["point_value"], 0.5)

# stop on the wrong side after the fill -> trade skipped, not silently taken
bad = sig.copy(); bad.iloc[0] = [1, 101, 104, np.nan]   # long, stop 101 above fill 100.75
tb, skb = fbt.simulate(bars.iloc[:3], bad.iloc[:3], SPECS["NQ"], 1, 2.50)
check("stop above long fill is skipped", skb["stop_wrong_side"], 1)

# 1.1.0 target rules (independent review 2026-11-08): 1-tick trade-through by default, touch as a flag,
# targets snapped to the tick FARTHER from entry.
tb = frame([[100, 100.5, 99.5, 100], [100, 101, 99.75, 100.5], [100.5, 102, 100.25, 101.5], [101.5, 102, 101, 101.75]])
ts_ = pd.DataFrame(index=tb.index, data={"entry": [1, 0, 0, 0], "stop": [98.0, np.nan, np.nan, np.nan],
                                         "target": [102.0, np.nan, np.nan, np.nan], "max_bars": [np.nan] * 4})
tt, _ = fbt.simulate(tb, ts_, SPECS["NQ"], 1, 2.50)
check("touch only (high == target 102) -> no fill by default", tt.reason[0], "end_of_data")
tt2, _ = fbt.simulate(tb, ts_, SPECS["NQ"], 1, 2.50, touch=True)
check("touch flag -> fills at 102 (+(102-100.25)*20-5 = 30)", tt2.pnl[0], 30.0)
snap = ts_.copy(); snap.iloc[0, 2] = 101.6                 # long target off-grid -> 101.75 (farther)
ts1, _ = fbt.simulate(tb, snap, SPECS["NQ"], 1, 2.50)
check("long target 101.6 snaps to 101.75, needs 102 -> fills bar 2", ts1.target[0], 101.75)
check("snapped target exit price", ts1.exit[0], 101.75)
sh = frame([[100, 100.5, 99.5, 100], [100, 100.25, 98.5, 99], [99, 99.5, 97.5, 98]])
ss = pd.DataFrame(index=sh.index, data={"entry": [-1, 0, 0], "stop": [102.0, np.nan, np.nan],
                                        "target": [98.6, np.nan, np.nan]})
st, _ = fbt.simulate(sh, ss, SPECS["NQ"], 1, 2.50)
check("short target 98.6 snaps DOWN to 98.5", st.target[0], 98.5)
check("short needs 98.25: bar1 low 98.5 no fill, bar2 fills", st.exit_ts[0], str(sh.index[2]))

print("ALL PASS" if fails == 0 else f"{fails} FAILED")
sys.exit(1 if fails else 0)
