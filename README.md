# honest-futures-backtest

A small backtesting engine for futures ideas (GC, MGC, NQ, MNQ, ES, MES) that is built to **reject** bad ideas instead of making them look good. It also works as a Claude Code skill (`SKILL.md`).

One file (`scripts/fbt.py`, about 480 lines, numpy and pandas only). No broker access, no API keys, no orders. Research only.

## Why

Most quick backtests flatter the idea: they fill at the close they just saw, skip costs, peek at future bars by accident, and report one lucky sample. This tool runs the checks that catch those mistakes and then gives a plain verdict.

| Verdict | Meaning |
|---|---|
| `INVALID_LOOKAHEAD` | signals change when future bars are removed: every number is fake |
| `INVALID_DATA` | duplicate, out-of-order, NaN or broken bars |
| `INSUFFICIENT_DATA` | fewer than 30 out-of-sample trades |
| `REJECTED` | out-of-sample expectancy is zero or negative after costs |
| `INCONCLUSIVE_INTRABAR` | result depends on whether stop or target came first inside one bar |
| `BACKTESTED_NOT_VALIDATED` | profitable, but fails a gate (random-entry test, cost stress, Monte Carlo, walk-forward) |
| `CANDIDATE_PAPER_TRADE` | passed every gate: paper trade the same rules next. Still not proof of an edge |

## What it checks

- Next-bar fills: a signal at the close of bar t fills at the open of bar t+1, with slippage.
- Tick-accurate dollar P&L with commission, from `assets/contract_specs.json`.
- Look-ahead audit: re-runs the strategy on cut-off data and compares signals.
- Out-of-sample split, random-entry null test (with a multiple-testing correction via `--trials`), cost stress, Monte Carlo and walk-forward.

## Quick start

```
pip install -r requirements.txt

# self-test: hand-computed checks, must print ALL PASS
python tests/test_engine.py

# synthetic market with a planted edge (known answer), then test a strategy on it
python tests/make_synth.py --out bars.csv --drift 0.25 --seed 1
python scripts/fbt.py --data bars.csv --symbol NQ --strategy tests/strategies/big_down_bar_long.py --out out/demo
```

Expected on that demo: `CANDIDATE_PAPER_TRADE`. With `--drift 0` (no edge) the same strategy is `BACKTESTED_NOT_VALIDATED`, and `tests/strategies/peek_cheat.py` (which looks one bar ahead) is `INVALID_LOOKAHEAD` even though it "makes" over two million dollars.

Your own data: a CSV with `ts,open,high,low,close[,volume]`, timezone kept in `ts`. Your own idea: copy `assets/strategy_template.py`. See `references/DATA.md` for free and paid data sources.

## Use as a Claude Code skill

Copy this folder to `~/.claude/skills/futures-backtesting/`. Claude will then follow the loop in `SKILL.md` when you ask it to test a trading idea.

## Validation

Known-answer results are in `references/VALIDATION.md`: bad strategies (no-edge twins, coin flips, look-ahead cheats) approved 0 of 9, while a naive backtest looked profitable on 6 of 9; a planted edge was found in 5 of 5 seeds. One known false positive is kept on record there.

## Limits

Bars only: no order book, no queue position. Continuous-contract data has roll gaps. Nothing here predicts the market, and a candidate can still fail in paper trading. Full list at the end of `SKILL.md`.

## Licence

MIT. This is research software, not financial advice.
