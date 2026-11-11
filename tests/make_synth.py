"""Synthetic hourly futures bars with an optional PLANTED edge (known answer).
Edge: after a bar that falls > 1.5x the 20-bar average range, the next 3 bars drift
up by +drift x avg range each. --drift 0 = no edge (control).
Usage: python -I make_synth.py --out bars.csv --drift 0.25 --seed 1 [--bars 12000] [--tick 0.25]"""
import argparse
import numpy as np, pandas as pd
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--drift", type=float, default=0.25)
ap.add_argument("--seed", type=int, default=1); ap.add_argument("--bars", type=int, default=12000); ap.add_argument("--tick", type=float, default=0.25)
a = ap.parse_args(); rng = np.random.default_rng(a.seed)
px, rows, ranges, boost = 20000.0, [], [], 0
for i in range(a.bars):
    avg = np.mean(ranges[-20:]) if ranges else 40.0
    mu = a.drift * avg / 4 if boost > 0 else 0.0
    vol = 12.0 * (1 + 0.5 * np.sin(i / 400))            # slow volatility regimes
    steps = rng.normal(mu, vol, 4); path = px + np.cumsum(steps)
    o, c = px, path[-1]; h = max(o, path.max()); l = min(o, path.min())
    q = lambda v: round(round(v / a.tick) * a.tick, 4)
    o, h, l, c = q(o), q(h), q(l), q(c)
    rows.append((o, h, l, c)); ranges.append(h - l); px = c
    boost = 3 if (o - c) > 1.5 * avg else max(0, boost - 1)
idx = pd.date_range("2024-01-01 00:00", periods=a.bars, freq="h", tz="America/New_York")
pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"]).rename_axis("ts").to_csv(a.out)
print("wrote", a.out)
