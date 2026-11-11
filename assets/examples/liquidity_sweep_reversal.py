"""Example hypothesis: prior-day high/low liquidity sweep -> reversal.
Explicit, testable definition (no discretion):
  session  = CME trading day, 18:00 ET -> 17:00 ET (date = (ts_ET + 6h).date)
  PDH/PDL  = high/low of the PREVIOUS complete session
  short    = first bar of the session (inside the allowed hours) whose high > PDH and close < PDH
             stop = that bar's high + 1 tick, target = close - rr * (stop - close)
  long     = mirror at PDL
  exit     = stop, target, or close of bar max_bars (whichever first)
"""
import numpy as np, pandas as pd
HYPOTHESIS = ("Stops resting above the prior-day high / below the prior-day low get run; when price sweeps the "
              "level and closes back inside on the same bar, the move fails and price rotates back into the range.")
REGIME = "NY hours only (default 08:00-15:59 ET bar opens); one trade per side per session; no news filter yet."
FAILURE_CONDITIONS = ("Reject if OOS expectancy <= 0 after 1-tick slippage + commission, if random-entry p >= 0.05, "
                      "or if it dies at 2 ticks slippage. Do not rescue it by adding filters on the same data.")
PARAMS = {"rr": 1.5, "max_bars": 6, "tick": 0.25, "h0": 8, "h1": 15}
PARAM_GRID = {"rr": [1.0, 1.5, 2.0], "max_bars": [3, 6]}

def signals(df, rr=1.5, max_bars=6, tick=0.25, h0=8, h1=15):
    et = df.index.tz_convert("America/New_York") if df.index.tz is not None else df.index
    sess = (et + pd.Timedelta(hours=6)).date
    g = pd.DataFrame({"h": df.high.to_numpy(), "l": df.low.to_numpy(), "s": sess})
    per = g.groupby("s").agg(h=("h", "max"), l=("l", "min"))
    prev = per.shift(1)                                  # previous COMPLETE session only
    pdh = pd.Series(sess).map(prev.h).to_numpy(); pdl = pd.Series(sess).map(prev.l).to_numpy()
    hours = np.asarray(et.hour); ok_h = (hours >= h0) & (hours <= h1)
    hi, lo, cl = df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy()
    short = ok_h & (hi > pdh) & (cl < pdh)
    long_ = ok_h & (lo < pdl) & (cl > pdl)
    # first event per session and side (cumcount uses only earlier rows -> causal)
    s_ser = pd.Series(sess)
    short &= (pd.Series(short).groupby(s_ser).cumsum() == 1).to_numpy()
    long_ &= (pd.Series(long_).groupby(s_ser).cumsum() == 1).to_numpy()
    out = pd.DataFrame(index=df.index, data={"entry": 0, "stop": np.nan, "target": np.nan, "max_bars": max_bars})
    stop_s = hi + tick; stop_l = lo - tick
    out.loc[short, "entry"] = -1; out.loc[short, "stop"] = stop_s[short]
    out.loc[short, "target"] = (cl - rr * (stop_s - cl))[short]
    out.loc[long_, "entry"] = 1; out.loc[long_, "stop"] = stop_l[long_]
    out.loc[long_, "target"] = (cl + rr * (cl - stop_l))[long_]
    both = short & long_
    out.loc[both, ["entry", "stop", "target"]] = [0, np.nan, np.nan]   # ambiguous bar: skip
    return out
