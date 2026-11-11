import numpy as np, pandas as pd
HYPOTHESIS = "After a bar that falls more than 1.5x the average range, price bounces over the next 3 bars."
REGIME = "All hours; synthetic test market."
FAILURE_CONDITIONS = "OOS expectancy <= 0, random-entry p >= 0.05, or dies at 2 ticks slippage."
PARAMS = {"k": 1.5, "rr": 1.0, "max_bars": 3}
PARAM_GRID = {"k": [1.25, 1.5, 2.0], "rr": [1.0, 1.5]}
def signals(df, k=1.5, rr=1.0, max_bars=3):
    avg = (df.high - df.low).rolling(20).mean().shift(1)
    trig = (df.open - df.close) > k * avg
    out = pd.DataFrame(index=df.index, data={"entry": 0, "stop": np.nan, "target": np.nan, "max_bars": max_bars})
    out.loc[trig, "entry"] = 1
    out.loc[trig, "stop"] = (df.close - avg)[trig]
    out.loc[trig, "target"] = (df.close + rr * avg)[trig]
    return out
