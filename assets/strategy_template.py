"""Strategy template for fbt.py. Copy, rename, fill every constant.

Rules: signals() may only use bar t and EARLIER bars to set row t
(no .shift(-1), no centered rolling windows, no full-sample min/max/mean,
no future-dated joins). fbt's look-ahead audit re-runs this on truncated
data and fails the test if any past signal changes.
"""
import numpy as np
import pandas as pd

HYPOTHESIS = "One sentence: what inefficiency, why it should exist, what you expect to see."
REGIME = "When this should work (session, trend/range, volatility filter) and when it is switched off."
FAILURE_CONDITIONS = "What result would prove the idea wrong (e.g. OOS expectancy <= 0, p >= 0.05, dies at 2 ticks slippage)."
PARAMS = {"lookback": 20, "rr": 2.0, "max_bars": 8}
PARAM_GRID = {"lookback": [10, 20, 40], "rr": [1.5, 2.0]}   # for --walk-forward; keep it small


def signals(df: pd.DataFrame, lookback=20, rr=2.0, max_bars=8) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index, data={"entry": 0, "stop": np.nan, "target": np.nan, "max_bars": max_bars})
    hi = df.high.rolling(lookback).max().shift(1)      # PRIOR bars only
    lo = df.low.rolling(lookback).min().shift(1)
    long_ = df.close > hi
    out.loc[long_, "entry"] = 1
    out.loc[long_, "stop"] = df.low[long_]
    risk = (df.close - df.low)[long_]
    out.loc[long_, "target"] = df.close[long_] + rr * risk
    return out
