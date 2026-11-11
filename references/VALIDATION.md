# v1.2.1 (2026-11-09), VERIFIED
- The random-entry p-value now compares expectancy in **R** (P&L / initial risk), not dollars, so size differences can't fake an edge (independent review). Dollars are still reported.
- Full battery re-run (`e2e_v1.2.1.log`): same results as 1.2.0. Audits 4/4 all PASS; coin seeds 0/20; no-edge 2/20; planted 5/5. Engine tests 25/25.
- Agent-level E2E (fresh headless Claude, plain-language task, no mention of skills): the agent found the skill, wrote the strategy, ran fbt (MGC, $300 risk) and reported REJECTED with numbers that match report.json. Side effect: the sandbox was under the home folder, so the agent picked up an unrelated project's CLAUDE.md and wrote 2 entries into that project's notes. They were reverted. Future agent tests must run outside the home folder.

# v1.2.0 (2026-11-09): end-to-end battery, VERIFIED
Command: `validation workspace: run_e2e.py` (log `e2e_v1.2.0.log`, summary `e2e_summary.json`).

**Independent audit** (`audit_report.py`): a separately written engine re-simulates every trade from the raw bars and the strategy's own signals. It does not import fbt.
| Config | trades | checks | result |
|---|---|---|---|
| GC 1 contract, sweep reversal, walk-forward | 276 | 25 | all PASS |
| MGC risk $300, sweep reversal | 233 | 27 | all PASS (never risks > $300 incl. fees; max whole contracts) |
| NQ 1 contract, sweep reversal, walk-forward | 367 | 25 | all PASS |
| MNQ risk $200, 2-tick slippage, $1.10 commission, coin flip | 1683 | 27 | all PASS |
Checked: entry, exit, reason, qty, P&L per trade, commission and slippage totals, net, win rate, PF, expectancy, max drawdown, OOS split and IS/OOS metrics.

**Error rates**
| Test | CANDIDATE given | should be |
|---|---|---|
| 20 random coin flips (seeded) on real MNQ, risk-sized | **0/20** | ~0–1 |
| 20 no-edge synthetic markets, risk-sized | **2/20** (10 %, 95 % CI ≈ 1–32 %) | ≈ 1 (5 %) |
| 5 planted-edge markets, risk-sized | **5/5** | 5 |
| look-ahead audit on all 20 coin seeds | 20/20 pass (no false alarms) | 20 |

**Bugs found by the E2E work and fixed in 1.2.0**
1. The null used each trade's *realized* hold as a forced time exit (introduced in 1.1.0). Now it uses the planned max hold.
2. The null reused stop/target distances in raw points at bars with different volatility, so it lost money by itself. Distances are now volatility-scaled.
3. GC prices from Yahoo carry float noise (≤ 0.0002 off the 0.10 tick on 10.9k of 13.7k bars). This is now snapped to the tick grid on load.
4. The audit harness had its own bug: it crashed mid-run, and the battery counted only "FAIL" lines and missed it. The battery now checks the exit code.

**Known false positive kept on record:** the original hash-direction coin flip on MNQ (risk $200) is still CANDIDATE (p = 0.005). Diagnosis (`diag_coin.py`): the same entry bars with 20 random direction sets average −$11.50/trade (best +$9.51); this one fixed direction sequence made +$14.85. It is a ~1-in-200 lucky sequence, not an engine error. This is why a CANDIDATE goes to paper trading and why `--trials` matters.

# v1.1.1 (2026-11-08), VERIFIED
- Fix: the SKILL.md description contained an unquoted ": " ("Research only: never..."), so the YAML header failed to parse and Claude Code showed only "Futures backtesting" as the description. Changed to "Research only, never...". The validator now does a real YAML parse and FAILS the old file.
- The v1.0.0 activation result (3/3 trading prompts) was measured with the broken description, so it only showed that the skill NAME triggers it. Re-run on 1.1.1: 5/5 (3 trading prompts trigger, 2 unrelated prompts don't). File: skill-forge/tests/activation_results_fb_v1.1.1.json.

# v1.1.0 changes (2026-11-08, after an independent review), VERIFIED
- Targets: snapped to the tick farther from entry, 1-tick trade-through by default (`--touch-fills` = old behaviour).
- Random-entry null: matched on ET fill hours and per-trade hold length. Bonferroni via `--trials`.
- Engine tests: 25/25 PASS (6 new: touch vs trade-through, long/short target snapping).
- Re-run of everything below on v1.1.0 gives **the same verdicts**: bad ideas approved 0/9 (naive 6/9), planted edge 5/5 CANDIDATE, look-ahead 2/2 caught. Real sweep reversal: NQ REJECTED (OOS −$708/trade, best case −$454, matched null p 1.0, matched on fill hours 9–16 ET), GC REJECTED (−$527, best case −$365, p 0.985). This agrees with an earlier independent study of the same idea.
- Output: `validation workspace: validation_v1.1.0.txt`, `runs/sweep_*_v110/`.

# Validation: futures-backtesting v1.0.0 (2026-11-08, VERIFIED, reproduced twice with identical output)

Hashes (sha256, first 16): fbt.py 7f3984269ff16b6e · test_engine.py a4493a7d3ab276c7 · make_synth.py 01d3a5224ff08b2b · liquidity_sweep_reversal.py 28cadc77c8ec582a.

## 1. Engine arithmetic: `python -I tests/test_engine.py` gives 19/19 PASS
Each case was worked out by hand: NQ long to target (+$60, R 1.0909), short stopped (−$60), gap through stop filled at the open (−$45), stop+target in one bar uses the stop (−$55, optimistic bound +$30), time exit after 2 bars ($0), naive close fill (+$80), GC risk sizing ($1000 → 1 lot, $2100 → 4 lots, +$3940), a stop on the wrong side is skipped, and the MGC/MNQ point values.

## 2. Does it tell good ideas from bad ones? (`run_validation.py`)
The realistic engine was compared with the naive baseline on the same strategy and data. The naive baseline fills at the signal close, has no costs and checks stops on closes only, the way most hand-written backtests work. "Naive says good" means net > 0 and OOS expectancy > 0.

| Case | n | Skill verdict | Naive says good |
|---|---|---|---|
| Planted edge (synthetic, real bounce after big down bars) | 5 seeds | **5/5 CANDIDATE_PAPER_TRADE** | 5/5 |
| No-edge twin (same generator, drift 0) | 5 seeds | 3 NOT_VALIDATED, 2 REJECTED, **0 CANDIDATE** | **3/5** |
| Look-ahead cheat (`shift(-1)`) on real NQ and GC 1h | 2 | **2/2 INVALID_LOOKAHEAD** | **2/2** (+$4.5M / +$4.1M "profit") |
| Coin flip on real NQ and GC 1h | 2 | 1 NOT_VALIDATED (NQ +$87/trade OOS, which is trend luck, caught by the null), 1 REJECTED, **0 CANDIDATE** | **1/2** |

Bad ideas approved: **skill 0/9, naive 6/9.** Good idea found: skill 5/5.
The naive baseline overstated net P&L on every no-edge run by $5k–$11k, which is the cost of close fills plus zero costs.

## 3. Real hypothesis: prior-day high/low sweep reversal (Yahoo 1h, 2024-06-18 → 2026-11-09, OOS from 2026-02-24)
| | NQ | GC |
|---|---|---|
| data sha16 | f5c034f1bba19ed3 | 6ffd6ad596b45471 |
| trades (all / OOS) | 367 / 102 | 276 / 89 |
| in-sample expectancy | −$258/trade, PF 0.74 | −$101/trade, PF 0.85 |
| OOS expectancy (worst case) | **−$709/trade**, win 29 % | **−$528/trade**, win 34 % |
| OOS best case (same-bar order favourable) | −$455 | −$367 |
| random-entry null p | 0.995 (worse than random) | 0.975 |
| walk-forward OOS | −$550/trade, 295 trades | −$341/trade, 221 trades |
| **verdict** | **REJECTED** | **REJECTED** |

Interpretation: as defined (hourly bars, first sweep per session, 08–15 ET, stop beyond the sweep bar), this idea has no edge on 2.4 years of data, and it is rejected even under the optimistic intrabar assumption. This does **not** test a 1-minute execution model. That needs 1m data (TradingView export or Databento) and a new, pre-registered hypothesis.

Data warnings: ~494 zero-volume bars in both files, and 6 (NQ) and 4 (GC) open gaps > 8× the median range (rolls or weekend gaps). Both are expected for Yahoo continuous contracts.

## 4. Activation (8 fresh headless Claude Code sessions, sandbox with only our 2 skills)
8/8 correct: 3/3 tracking prompts, 3/3 backtest prompts (including "does buying gold after a big red candle actually work?", which never says "backtest"), and 0/2 false triggers (a Luau tween, a CPI-time question). Results: `skill-forge/tests/activation_results.json`.

## Not yet done
- A with-skill vs without-skill A/B on full agent runs (skill-creator style with graders). The scripted naive baseline stands in for "agent without the skill" here.
- Paper-trading step (planned skill `paper-trading-simulator`).
