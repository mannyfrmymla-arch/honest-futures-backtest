---
name: futures-backtesting
description: Backtest a futures trading idea (GC, MGC, NQ, MNQ, ES, MES) with realistic next-bar fills, tick-accurate dollar P&L, slippage and commission, a look-ahead audit, out-of-sample split, random-entry null test, cost stress, Monte Carlo and walk-forward, then label it REJECTED / NOT VALIDATED / CANDIDATE instead of calling it an edge. Use whenever someone wants to test, check, validate or compare a trading strategy or setup on historical data, asks "does this setup work", "backtest this", "what's the win rate / expectancy", "is this an edge", or wants numbers for a gold or Nasdaq futures hypothesis, even if they don't say "backtest". Research only, never places orders.
license: MIT. Uses numpy and pandas (BSD-3).
compatibility: Python 3.10+ with numpy and pandas (yfinance optional, for free Yahoo data). No brokerage access, no API keys.
metadata:
  author: honest-futures-backtest contributors
  version: "1.2.1"
  created: "2026-11-08"
  status: "released"
---

# Futures backtesting

The goal is to find out whether an idea works, not to make it look good. A backtest can only **reject** an idea or promote it to paper trading. It never proves an edge.

Known-answer validation (see `references/VALIDATION.md`):
- **Bad strategies** (no-edge twins, coin flips, look-ahead cheats): this skill approved **0 of 9**. A naive backtest looked profitable on **6 of 9**, including a look-ahead cheat showing +$4.5M.
- **Planted edge** (synthetic market with a real edge): the skill marked it CANDIDATE in **5 of 5** seeds.

## The scientific loop (follow it in order)

1. **Hypothesis.** Write one sentence: what inefficiency, why it should exist, and what you expect to see.
2. **Rules.** Turn the idea into code in a strategy file copied from `assets/strategy_template.py`. Every entry needs a stop. Fill in `HYPOTHESIS`, `REGIME` and `FAILURE_CONDITIONS` *before* running. Decide now what result kills the idea.
3. **Data.** Get bars as `ts,open,high,low,close[,volume]` and keep the timezone. Run on the timeframe the idea needs: a 1-minute setup cannot be tested on hourly bars. Data sources are in `references/DATA.md`.
4. **Backtest:**
   ```
   python -I scripts/fbt.py --data bars.csv --symbol NQ --strategy my_idea.py --out out/my_idea_v1 --walk-forward 4
   ```
   Set `--commission` to the real all-in cost per side, use `--risk-usd 500` for risk-based sizing, and use `--params '{"rr": 2}'` to override. It prints one JSON line and writes `report.md`, `report.json` and `trades.csv`.
5. **Read the verdict, then the reasons.**

   | Verdict | Meaning | Next |
   |---|---|---|
   | INVALID_LOOKAHEAD | signals change when future bars are removed | fix the code; every number in the report is fake |
   | INVALID_DATA | duplicate, out-of-order, NaN or broken OHLC bars | fix the data |
   | INSUFFICIENT_DATA | fewer than 30 out-of-sample trades | more history; don't loosen the rules to get more trades |
   | REJECTED | out-of-sample expectancy ≤ 0 after costs | document it as a failed idea |
   | INCONCLUSIVE_INTRABAR | the worst case loses but the best case wins, because stop and target sit in the same bar | re-test on lower-timeframe bars |
   | BACKTESTED_NOT_VALIDATED | profitable, but fails a gate (random-entry p ≥ 0.05, dies at higher slippage, MC P(loss) > 10 %, or walk-forward ≤ 0) | treat it as luck until shown otherwise |
   | CANDIDATE_PAPER_TRADE | passed every gate | paper trade the **same rules** for a set number of trades; still not an edge |
6. **Report honestly.** Copy the numbers from `report.md` with the command and the data/strategy sha16 values. Say which label applies. A failed idea gets written up as failed. Never "improve" it with filters fitted to the same out-of-sample data. That turns the test set into a training set. If you change the rules, it is a new hypothesis and needs new, unseen data.
7. **Log it.** Each hypothesis gets one entry in the trials ledger: hypothesis, rules version, data range, verdict, and the key numbers. Pass the ledger count as `--trials N`. The random-entry gate then needs p < 0.05/N (Bonferroni). Without it, about 1 in 20 no-edge ideas would pass by luck.


## How fills work (and why)

- A signal is decided at the **close** of bar t and fills at the **open of bar t+1**, ± slippage. You cannot trade a close you have only just seen.
- Stops and targets are resting orders, checked against each bar's high and low. Stops get slippage.
- **Targets** are snapped to the tick farther from entry. They need a **1-tick trade-through** to fill. `--touch-fills` makes them fill on a touch instead, which is optimistic and only for comparisons.
- If the bar **opens through the stop**, the exit fills at the open, which is worse than the stop.
- If **stop and target are both inside one bar**, the order is unknown. The verdict uses the stop (worst case). `intrabar_ambiguity` reports the best case and how many trades were affected.
- Time exit happens at the close of bar `max_bars`, counting the entry bar as bar 1. There is one position at a time, and signals that arrive while in a trade are ignored.
- P&L = points × point value × contracts − commission × 2 × contracts. Specs are in `assets/contract_specs.json` (GC $100/pt, MGC $10, NQ $20, MNQ $2). The default commissions are estimates, so set the real ones.

## Rules for strategy code

- Row t may use only bar t and earlier bars. Watch for `.shift(-1)`, `rolling(center=True)`, whole-sample `min()/max()/mean()`, `bfill()`, and joins on dates that are not known yet (e.g. a session high before the session ends). The audit catches these by re-running on cut-off data, but write the code right in the first place.
- Use **previous complete** sessions for PDH/PDL and similar levels. The CME session runs 18:00–17:00 ET.
- Don't infer order flow (delta, absorption, footprint) from OHLC bars. Without tick or bid/ask data, say it can't be tested.

## Self-test (after any change to `scripts/fbt.py`)
```
python -I tests/test_engine.py        # 25 hand-computed checks, must print ALL PASS
```

## Limits

- **Bars only.** There is no order book or queue position, so limit fills assume touch = fill (optimistic for targets).
- **Continuous-contract data has roll gaps.** Yahoo's `GC=F`/`NQ=F` are not back-adjusted. The data check lists big open gaps, so look at them.
- The random-entry null keeps the strategy's stop and target distances but randomises timing and direction. It tests whether *timing* adds value, not whether the risk model is good.
- The walk-forward picks the best parameter on each training window by mean P&L (minimum 10 trades). Keep `PARAM_GRID` small: every combination you add raises the false-discovery risk.
- No margin, overnight-hold rules, daily loss limits or prop-firm rules. Those are outside the scope of this tool.
- Nothing here predicts the market. A CANDIDATE can still fail in paper trading, and that result counts too.

Method details and sources: `references/METHOD.md`. Data sources: `references/DATA.md`. Validation numbers: `references/VALIDATION.md`.
