import numpy as np, pandas as pd
HYPOTHESIS = "CONTROL: pseudo-random direction every 6 bars, no edge by construction."
REGIME = "All hours"; FAILURE_CONDITIONS = "Should never pass."
PARAMS = {"every": 6, "seed": None}
def signals(df, every=6, seed=None):
    avg = (df.high - df.low).rolling(20).mean()
    h = pd.util.hash_array(df.index.asi8.astype("int64")) % 2       # depends only on the bar's own timestamp
    d = np.where(h == 0, 1, -1)
    if seed is not None:   # prefix-stable random stream: row i always gets the same draw (causal)
        d = np.random.default_rng(seed).integers(0, 2, size=len(df)) * 2 - 1
    on = (np.arange(len(df)) % every == 0) & avg.notna().to_numpy()
    # position-in-file is causal under truncation because rows only get appended
    out = pd.DataFrame(index=df.index, data={"entry": 0, "stop": np.nan, "target": np.nan, "max_bars": 4})
    out.loc[on, "entry"] = d[on]
    out.loc[on, "stop"] = (df.close - d * avg)[on]
    out.loc[on, "target"] = (df.close + d * avg)[on]
    return out
