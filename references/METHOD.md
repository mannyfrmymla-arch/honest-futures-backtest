# Method, gates and sources

## Gates behind the verdict (checked in this order)
1. **Look-ahead audit.** The strategy is re-run on the data cut at 8 points between 30 % and 100 % of the sample. Every signal, stop and target before each cut must match the full-data run exactly. Any mismatch means INVALID_LOOKAHEAD. This catches `.shift(-1)`, centred windows, whole-sample statistics and future-dated joins without reading the code. It cannot catch look-ahead in the data itself, such as revised prints or a back-adjusted series built with future roll dates.
2. **Data checks.** ERROR level: duplicate timestamps, non-increasing timestamps, NaN prices, or low/high inconsistent with open/close. WARN level: closes off the tick grid, zero volume, or open-vs-previous-close jumps over 8× the median 50-bar range (rolls, data holes, news).
3. **Out-of-sample split.** The split is chronological, with the last 30 % (`--oos-frac`) as out-of-sample. All verdict gates use out-of-sample trades. In-sample numbers are shown only for comparison: OOS below 30 % of IS expectancy is flagged as a possible overfit.
4. **Minimum sample.** At least 30 out-of-sample trades are required.
5. **Expectancy.** OOS mean P&L per trade, after slippage and commission, must be > 0.
6. **Matched random-entry null (OOS).** This makes 200 runs with the same number of trades. Each random trade copies one real trade's stop and target distance, **measured in units of the 20-bar average range at its signal bar and rescaled to the volatility at the random bar** (v1.2.0), plus its **planned** max hold (v1.2.0; v1.1.0 wrongly used the realized hold). Entries are drawn only from bars whose fill lands in the **same ET hours** the strategy traded, with random direction. The p-value is the share of random runs with expectancy ≥ ours, using the (k+1)/(n+1) form. Expectancy is compared in R (P&L / initial risk), so position size can't fake an edge (v1.2.1). The gate requires p < 0.05/trials (Bonferroni over the trials ledger). v1.0.0 drew from any hour and gave every random trade the longest hold, which is unmatched; The same bug in an earlier private study overstated an edge by 28 %.
7. **Cost stress.** The strategy is re-run at 0, 1×, 2× and 3× slippage ticks. OOS expectancy must stay > 0 at the highest level.
8. **Monte Carlo (OOS).** OOS trades are resampled with replacement 2000 times. The gate requires P(net ≤ 0) ≤ 10 %. It also reports drawdown percentiles, which answer "how bad could the drawdown be with these same trades".
9. **Walk-forward** (`--walk-forward K`, needs `PARAM_GRID`). The data is split into K+1 windows. For each fold, the run picks the best grid point on window k (≥ 10 trades) and trades it on window k+1. Indicators are warmed on the training window, and only test-window entries are kept. The concatenated test trades must have expectancy > 0.

A strategy that passes every gate becomes CANDIDATE_PAPER_TRADE. There is deliberately no "VALIDATED" label: validation needs data the idea has never seen, which means live or paper trading under the same rules.

## Why these choices
- **Next-bar-open fills.** Filling at the signal bar's close is the most common silent bias in hand-written backtests. Our naive baseline does it, and on the no-edge controls it inflated net P&L by about $5–11k per run.
- **Worst-case intrabar order**, with the best case reported alongside. Bars don't tell you whether the high or the low came first. Assuming the favourable order inflates results, so the verdict uses the unfavourable one and shows the bound.
- **A null model instead of a Sharpe threshold.** A positive backtest in a trending market can come from direction bias alone. The coin flip on NQ made +$87/trade OOS in testing, and the null test caught it (p not < 0.05).
- **Pre-registered failure conditions** (`FAILURE_CONDITIONS` in the strategy file) stop the goalposts from moving after the results come in.

## Sources (methods, not code)
- Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting" (2014), and López de Prado, *Advances in Financial Machine Learning* (2018), ch. 11–12: multiple-testing and overfitting risk, and walk-forward limits.
- Harvey & Liu, "Backtesting" (2015): haircut Sharpe ratios for the number of trials. This motivates logging every hypothesis tried.
- Aronson, *Evidence-Based Technical Analysis* (2006): data-mining bias, and the use of randomised null tests for rule-based signals.
- CME contract specs, via broker spec pages that quote CME: GC 100 oz with a $0.10 tick = $10, MGC 10 oz = $1/tick, NQ $20 × index with a 0.25 tick = $5, MNQ $2 × index = $0.50/tick.

## Library survey (2026-11-08, GitHub API)
| Project | License | Last push | Verdict |
|---|---|---|---|
| nautilus_trader 1.231.0 | LGPL-3.0 | 2026-11 | **strongest next step** for order-book and tick realism (Rust core, event-driven, futures and roll aware). Heavy install; worth it once we have tick or MBP data |
| vectorbt 1.2.0 | Apache-2.0 **+ Commons Clause** | 2026-11 | fast parameter sweeps. Commons Clause bars selling anything built on it, so internal research only. Vectorised fills invite the close-fill bias, so check the fill settings |
| backtrader | GPL-3.0 | 2024-08 (inactive) | mature but unmaintained; GPL. Not adopted |
| backtesting.py | AGPL-3.0 | 2026-08 | simple, but AGPL is viral if ever served. Not adopted |
| QuantConnect Lean | Apache-2.0 | 2026-11 | professional futures support, but C#/.NET and heavy. Option if you move to a hosted research stack |
| zipline-reloaded | Apache-2.0 | 2026-11 | equities-first. Not adopted |
| tradermonty/claude-trading-skills `backtest-expert` | MIT | 2026-11 | a methodology skill with no engine and no futures contract math. Its "find what breaks least" philosophy matches ours, and the ideas are absorbed here |

We wrote our own small engine (~450 lines, numpy and pandas) because none of these combine permissive licensing, futures dollar math, the look-ahead audit and the verdict gates in one file that one person can read end to end.
