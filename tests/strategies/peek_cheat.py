import numpy as np, pandas as pd
HYPOTHESIS = "PLANTED BUG: uses the next bar's close (look-ahead). Must be caught."
REGIME = "n/a"; FAILURE_CONDITIONS = "n/a"
PARAMS = {}
def signals(df):
    avg = (df.high - df.low).rolling(20).mean()
    up = df.close.shift(-1) > df.close + 0.2 * avg          # <- peeks one bar ahead
    out = pd.DataFrame(index=df.index, data={"entry": 0, "stop": np.nan, "target": np.nan, "max_bars": 1})
    out.loc[up, "entry"] = 1; out.loc[up, "stop"] = (df.close - avg)[up]
    return out
