# Data sources for GC / NQ research

| Source | Timeframes / depth | Cost | Notes |
|---|---|---|---|
| Yahoo via `yfinance` 1.8.0 (Apache-2.0) | daily 10y+, 1h ≈ 730 days, 5m/1m ≈ 60/7 days | free | continuous front month `GC=F`, `NQ=F`. **Not back-adjusted**, so roll gaps stay in. Has zero-volume bars (≈ 500 of 13.7k hourly). Fine for first-pass hypotheses on 1h+, not for 1-minute setups |
| TradingView export | whatever the chart has loaded | your plan | good for 1m/5m spot checks. Export CSV with ET timestamps |
| Databento (`databento-python`, Apache-2.0) | tick, MBP-1/10 (bid/ask), 1s/1m bars, years of CME history | paid per GB | needed for **real order-flow** work (delta, imbalance, absorption) and accurate intrabar order. Needs an API key |
| CME DataMine | official tick/top-of-book | paid | most authoritative, most expensive |

## Gotchas
- **Timezones.** Keep the offset in `ts`. Session logic should convert to `America/New_York`. The CME day runs 18:00–17:00 ET.
- **Rolls.** On a non-adjusted continuous series, the roll day shows a price jump that is not a trade. Either use back-adjusted data or skip trades open over a roll. fbt lists suspicious gaps in `data_checks`.
- **Order flow.** Volume, delta, bid/ask imbalance and footprint need tick or bid/ask data. Never estimate them from OHLC and call the result order flow.
- **Bar timestamps.** Yahoo's hourly bars are stamped at the bar *open*. A signal on the bar stamped 09:00 ET is known at 10:00 ET.

## Fetch example (yfinance)
```python
import yfinance as yf
d = yf.download("NQ=F", period="730d", interval="1h", auto_adjust=False, progress=False, multi_level_index=False)
d.index.name = "ts"; d = d[["Open","High","Low","Close","Volume"]]; d.columns = ["open","high","low","close","volume"]
d.to_csv("NQ_1h_yahoo.csv")
```
