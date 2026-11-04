# India Quant 2.1 - conditional trade research and manual broker workflow

**Local single-user developer release | 4 November 2026 | Python API + browser UI**

This release extends the actual v1 application with a provider-backed instrument directory,
quote-snapshot research boards, chart controls, saved model inference and walk-forward testing.
It does not promise returns, publish sure-shot calls, or place broker orders. No profitable pretrained
model is bundled. More model complexity is not proof of a trading advantage.

## Version 2.1: local product workflow

Daily Trade Desk now ranks **CONDITIONAL BUY**, **WAIT**, **BLOCKED** and **EXPIRED** research plans.
Each eligible plan shows its next-open entry range, reference stop/target, formulas to recalculate
levels from the actual fill, source, deadline and rule/model evidence. Rules-only daily plans can
work without a personal broker API; they do not carry a validated profit probability. Intraday
plans still require fresh broker quotes, normal-market status and validated model evidence.

**Review plan / open broker** rechecks the setup and offers a dated research record to copy or save.
Broker buttons open Zerodha Kite, Upstox or Dhan without sending an order or broker credentials.
Users can place trades manually on any broker. Holiday/special-session calendars and company events
are not verified; expired next-open plans are not moved to a later day automatically.

Catalogue suspension checks now distinguish exchange series and tokens. A suspended block-deal or
special series no longer falsely suspends an active regular equity sharing its ISIN-based key.
An older catalogue needs one refresh to apply this correction.

For local distribution, run `python build_local_package.py` to create `dist/IndiaQuant-Local-2.1.zip`
without credentials, databases, journals or fitted models. See `docs/COMMERCIAL_ROADMAP.md` for the
local-first / hosted-later product plan and official data alternatives. Paid recommendations need
applicable regulatory review and data rights. A hosted subscription service is not included.

## Windows: start here

1. Extract this ZIP into a NEW folder. Keep your old project and journal unchanged.
2. Install Python 3.11 64-bit and the Python Launcher when necessary.
3. Double-click `START_WINDOWS.bat` in the folder containing `run.py`.
4. Open `http://127.0.0.1:8765`. Stop the server with Ctrl+C in its terminal.
5. Market Explorer downloads the public Upstox NSE/BSE catalogue on first use when the local
   catalogue is empty. Use **Refresh NSE + BSE catalogue** later to update it. Search needs no token.
6. Search a name, symbol or ISIN, choose the correct exchange, add it to your watchlist and
   open **Chart & Filter Studio**. Missing candles load automatically once for the selected
   stock/timeframe/source; **Load / refresh candles** remains available for manual updates. Without a
   broker token, the app requests Yahoo Finance historical bars for regular cash equities.
   Yahoo's endpoint is unofficial and can be delayed, restricted, or unavailable. You can import
   your own OHLCV CSV directly on the selected stock's chart, including when offline.
7. For authorized broker quotes, option chains, and broker history, copy `.env.example` to `.env`,
   put your own `UPSTOX_ACCESS_TOKEN` there, and restart. Never share credentials.
8. Select **Compare models + walk-forward**. Inspect the final test, costs, calibration and
   failed checks. A result can legitimately have no eligible trades or no usable estimate.
9. Open **Daily Trade Desk**, choose Swing or Delivery, and select **Refresh data + find setups**.
   Open **Review plan / open broker** on a result. A rule match is conditional on the next opening
   price and other checks; it is never an instruction to buy at an old close. Intraday qualified
   plans require authorized live data. Broker auto-refresh is optional while the page is open.

After a chart loads, Chart & Filter Studio shows the current **CONDITIONAL BUY**, **WAIT**,
**BLOCKED** or **EXPIRED** decision directly above the graph. A failed strategy rule shows WAIT with
the exact reasons instead of hiding the decision or manufacturing a buy recommendation.

CSV and fictional SIM-* history remain available in the original research workspaces without
credentials. A CSV imported on a selected stock's chart is linked to that exact listing; a CSV
imported in the original Data workspace is not automatically linked. Neither is verified live data.
The screenshot catalogue is a separate test fixture and is not bundled into your real directory.

## New workspaces

| Workspace | Implemented behavior |
|---|---|
| Market Explorer | Search the downloaded NSE/BSE cash-segment and index master by company, symbol or ISIN; exchange/category filters, pagination, separate exchange identities, suspended flags, persistent watchlist. |
| Daily Trade Desk | Separate Intraday, Swing, Delivery and read-only F&O tabs. Cash tabs evaluate strategy/watchlist combinations with quote timestamps, model evidence, risk plans and reasons for rejection. |
| Chart & Filter Studio | Candlesticks, volume, EMA20/50/200, Bollinger bands, prior 20-bar levels, intraday session VWAP, RSI/MACD, hover and 60/120/180-bar zoom. |
| AI strategy lab | Prior baseline, logistic regression, Extra Trees, histogram gradient boosting and a fixed equal-weight soft vote. Separate calibration/selection/test; optional three-window expanding-history test; actual fitted artifacts saved locally. |

The original strategy library, local terminal, paper journal, options-payoff calculator, CSV/history
imports and risk/audit console remain. This is not a rewrite using Streamlit: no Streamlit, pandas or
PyArrow is required. Other compiled dependencies may still encounter Windows application-control
policies; have an authorized administrator review the exact blocked binary. Do not disable security.

## What "all stocks" means

The directory ingests the provider's NSE_EQ/BSE_EQ and NSE_INDEX/BSE_INDEX segments,
preferring active regular equity when multiple series share a key and retaining suspended-only keys.
It is not a certified reconciliation of every current NSE/BSE
security. New listings, special series and provider availability can differ. The master can contain
funds or other cash-segment products; searchability does not imply trade eligibility.

Cash trade research deliberately requires a conservative regular-equity scope: suitable instrument
type, INE-prefixed ISIN, lot size 1 and not suspended. Other records remain searchable and chartable
when the provider supplies history, but cannot become cash-trade candidates. F&O contracts are
queried by underlying and exact expiry; there is no general derivatives-contract search directory.

**Search is not capped at 25 instruments.** The local quote/strategy watchlist is capped at 25 to
bound requests and processing. This release does not scan every listed security live every day.

## What "live" means in this release

- Broker-authorized REST quote snapshots, not a tick-by-tick WebSocket feed. No broker connection
  was authenticated in the build environment; current entitlements must be checked in your account.
- No-key Yahoo Finance data supplies historical candles only. It does not supply the fresh quote,
  two-sided spread or exchange status needed for a qualified trade candidate. The daily desk can
  show a **CONDITIONAL BUY** research plan for a qualifying daily setup before its next-open window.
  It explicitly withholds live qualification and any unvalidated probability.
- Optional snapshots are refreshed every 20 seconds while Daily Trade Desk is open. They expire
  visibly even if the next refresh fails. No overnight scheduling, email alerts or automatic trading.
- Initial daily/15-minute history is loaded manually. During the supported intraday session, opted-in
  polling requests new completed bars for already-loaded watched equities. Daily history is manually
  refreshed. Refresh jobs are rate-limited, serialized and retried only on subsequent requests.
- Feed timestamp, last-trade age, bid/ask spread, market session, catalogue age and bar age are checked.
  Receiving a response now does not make an old last trade fresh. Missing data is never synthesized.
- Normal intraday setup validity is deliberately narrow: 75 seconds after a completed 15-minute bar,
  and no new setup after the implemented entry cutoff. This may produce many NO TRADE outputs.
- Daily setups model a conditional next-session-open entry. Their displayed LTP is not the assumed
  entry price; a NEXT OPEN RESEARCH WATCH is not an instruction to buy at the current quote.
- The F&O tab fetches exact-expiry option-chain prices, OI, IV and Greeks. It withholds profit
  confidence, excludes the provider's unvalidated POP field and does not borrow the cash model.
  It displays receipt time, not verified exchange freshness for every option quote.

## Confidence, models and filters

The target is reaching a specified target before a stop within the strategy horizon, conditional
on the next-open entry rule. It is NOT the probability of positive net P&L. A profitable timeout
still counts as target failure. A checklist score is NOT a probability.

Trained artifact inference matches the instrument, strategy and unchanged history lineage.
Missing models, missing setups or revised data withhold an estimate. Synthetic data, failed
historical checks, stale evaluation windows and a simple feature-range shift screen prevent a
qualified research status. Unvalidated estimates may be shown with their explicit failure status;
they never override the risk gates. There is no deep neural network or LLM trading agent in v2.

Price/volume/relative-volume/RSI/trend/spread filters and model thresholds are transparent policies,
not never-fail filters. Raising a minimum probability does not improve calibration. Freeze settings
before evaluating genuinely untouched data; repeatedly tuning against the same test overfits it.

Model selection uses a separate selection period, not the final test. The three additional
walk-forward windows are reports for review, NOT automatically integrated as an extra pass/fail
condition in the saved model gate. Cohort Wilson intervals are descriptive approximations, not
per-trade confidence intervals. Member disagreement is not a statistical uncertainty interval.
See `docs/ALGORITHMS.md` for exact assumptions and limitations.

## Paper capital and execution boundaries

The virtual account starts at Rs 10,000: 0.5% planned risk per entry, 20% position exposure, 1%
combined open planned risk, two simultaneous positions and a 1% daily realized-loss stop. These are
planning controls, not guaranteed loss caps. Cash, cost/slippage estimates and existing positions
can reduce allowed quantity to zero. Costs are configurable approximations, not tax invoices.

No real orders exist: `/api/live/orders` rejects requests. Manual paper entries/exits remain manual;
stop and target fields DO NOT automatically execute exits. Paper equity is not live marked to market.
Company news, earnings events, fundamentals and suitability are not checked. Event risk is explicitly
NOT CHECKED. Do not mistake a passed mechanical screen for permission to trade real money.

## Local data, security and upgrades

`data/desk.sqlite3` and `data/models/` are created locally. Back up the entire data directory with the
app stopped. Do not overwrite your previous journal or run two app instances against the same data.
Old datasets are immutable; repeated history refreshes increase disk use. No destructive cleanup or
automatic v1 journal migration is performed by the installer.

Only locally generated model files are loaded; hashes/version checks detect accidental corruption
and incompatibility, not a hostile local user. Joblib artifacts must be treated as trusted local
code-bearing objects. Never install an untrusted model into this directory. No model upload route.

The API remains loopback-only with local Host/Origin/write-token checks. These are not commercial
authentication or tenant isolation. Do not bind it publicly. No billing, customer accounts, licensed
redistribution, security certification or broker/exchange approval is supplied.

## Verification and scope

Version 2.1 passed **178 automated tests on Windows with Python 3.11.9**, including the original
regression suite, six public-history tests and 26 conditional-plan/manual-workflow tests.
Python compilation and JavaScript syntax checks passed. The real public provider catalogue was
downloaded and normalized locally; no-key historical requests succeeded for NSE and BSE examples.
Chrome over localhost passed the no-key chart/CSV and plan review/copy/save/expiry workflow checks
with fictional fixtures and zero JavaScript errors. The clean ZIP extraction also passed 178 tests.
Tests verify software behavior, not trading returns. No personal broker connection was authenticated.

Fresh-machine installation, Docker, production hosting, genuine trading performance and security
penetration testing remain unverified. See `docs/TEST_REPORT.md` for current checks and limitations;
the older Linux/browser results are retained there as historical evidence, separately from this run.

Reproduce unit tests: `python -m pip install -r requirements-dev.txt` then `python -m pytest -q`.
Use a separate `INDIA_QUANT_DATA_DIR` for tests or experiments to preserve your own records.

## Project map

`backend/universe.py`: directory/cache/watchlist; `market.py`: read-only provider requests;
`desk.py`: filtering/risk gates; `model_registry.py`: saved artifacts/inference; `research.py`:
model comparisons/walk-forward; `v2_api.py`: new routes/jobs; `frontend/markets.js`: new UI;
`docs/UPSTOX_SETUP.md`: setup/troubleshooting; `docs/PRODUCTION_GATES.md`: remaining launch work.
