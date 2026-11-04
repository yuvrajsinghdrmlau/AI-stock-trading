# India Quant 2.1 verification report

**Windows verification: 4 November 2026. Software tests are not market-performance evidence.**

Command: `.venv\Scripts\python.exe -m pytest -q -o addopts=`

**178 passed in 8.21 seconds** on Windows with Python 3.11.9. This includes the prior regression
suite, six public-history tests and 26 conditional-plan/manual-review tests. The new coverage checks
rules-only daily plans, absent/unvalidated probability, validated-model thresholds, entry-window
expiry, quote/trade/status freshness deadlines, intraday session exit, risk vetoes, suspension series,
listing-specific CSV imports, API write-token enforcement and refusal of real orders.

JavaScript syntax checks passed for app.js, markets.js and trade_plans.js. Python backend compilation
passed. Non-failing warnings concern a Starlette/AnyIO deprecated alias and Joblib falling back from
physical to logical CPU counts on this Windows installation.

Actual external read-only checks in this work session:

- Public Upstox active/suspended masters downloaded successfully; the normalized local catalogue
  contains 36,793 preferred instrument records. Regular NSE RELIANCE is active after the series/token
  correction; suspended special series sharing its key no longer block that listing.
- Yahoo historical responses succeeded for NSE RELIANCE and BSE TCS daily and 15-minute examples.
  A BSE RELIANCE response with insufficient candles was rejected, with CSV import available instead.
- No personal broker token was used. Authenticated quotes, option-chain entitlements and broker
  history remain unverified. Public historical access is not a licensed live-data integration.

Source-workspace evidence: `artifacts/pytest_v2_1_windows.txt` and
`artifacts/test_environment_v2_1_windows.json`. The clean customer ZIP omits artifacts and runtime
records; its included tests can be rerun. A fresh-machine installer, Docker, hosted deployment,
tenant isolation, security penetration testing and actual trading profitability are not verified.

### Current browser and clean-package checks

Installed Chrome with Playwright exercised normal localhost HTTP on Windows, with the application's
CSP intact and **zero JavaScript page errors**. An isolated temporary database and visibly fictional
SIM instruments were used; eligibility analysis/date were controlled fixtures, not live signals.

Verified separate NSE/BSE search results, computed candle charts, the no-key source selector,
missing-token quote rejection, empty-chart CSV import, plan review/recheck/copy/JSON download,
broker-link destinations and attributes (without opening them), and a 390-pixel chart layout.
The latest UI check also verifies automatic first-load history attempts and the trade decision shown
directly in Chart Studio after candles become available.
Expiry clears entry levels, candidate styling, decision badges and counts, and disables copying.
The dialog click-handler collision was fixed and copy/save/close no longer navigate the workspace.
Source-workspace evidence: `artifacts/browser_smoke_v21.py`, `browser_smoke_v21.json` and
`trade_plan_v21_fixture.png`. The test server and temporary database were closed after the run.

The clean local ZIP contains 56 allowlisted files plus its SHA-256 manifest. Every manifest hash
was verified, and runtime directories, credentials, journals and fitted model files were excluded.
The extracted source passed **178 tests in 8.19 seconds**, using the existing Windows virtual
environment. This is a clean-source check, not a fresh-machine dependency-installation test.
Evidence in the source workspace: `artifacts/verify_local_package.py`,
`clean_extraction_v2_1_windows.txt` and `package_v2_1_verification.json`.

## Historical 2.0 report (separate Linux run)

The following records an earlier environment, not the latest Windows checks. Its `artifacts/` files
are available in the source workspace only, not the clean 2.1 distribution. Historical external-access
failures and platform limitations below are superseded only where the 2.1 evidence above says so.

**Executed 3 November 2026. Software tests are not market-performance evidence.**

## Automated regression suite

Command: `python -m pytest -o addopts='' -q`

**146 passed in 6.37 seconds** in the working Linux environment. Original v1 regression tests are
included; the new tests do not replace them. Actual versions are recorded in
`artifacts/test_environment.json`; raw output is in `artifacts/pytest_results.txt`.
JavaScript syntax checks passed for both frontend/app.js and frontend/markets.js.

Coverage includes: provider-catalogue parsing/identities/pagination/parameterized search; suspended
and special-series flags; cache preservation; timestamp and crossed-spread handling; stale quotes;
strict filter inputs; model absence/integrity/revised-data rejection; past-only indicators; disjoint
walk-forward windows; risk limits; missing-credential errors; stripped options POP; denied real
orders; and opt-in candle-refresh timing, freshness, session restrictions and retry cooldown.

All market inputs in automated tests are explicit fixtures or generated synthetic bars. There is
no assertion that the tested rules or ML models earn a profit on Indian stocks.

## Actual frontend/browser workflows

Chromium + Playwright exercised the frontend against the running FastAPI backend:

- Search separate NSE/BSE identities for a fictional instrument; switch cash/index category.
- Open chart with computed candles, enable EMA200 and Bollinger bands, select MACD and zoom.
- Request a quote without credentials and observe an explicit failure instead of a fake price.
- Start/poll an actual model-comparison job; persist a fitted artifact; render walk-forward results.
- Switch Intraday, Swing, Delivery and read-only F&O tabs; submit filters and review rejection cards.
- Open all original workspaces. Mobile Explorer and Chart Studio remained 390 pixels wide at a
  390-pixel viewport. Zero JavaScript page errors were observed.

The managed browser blocked direct localhost navigation with ERR_BLOCKED_BY_ADMINISTRATOR. No
policy was disabled. The exact frontend was loaded in an isolated page and fetch calls were bridged
through Python HTTP to the actual running backend. This tests frontend logic and actual API
interaction, but not normal browser-over-HTTP deployment or full browser security-header handling.
API security protections are separately covered by automated tests.

The exact environment-specific harness and fixture server are retained in artifacts/. Their
`/mnt/data/...` paths and installed Chromium location require adaptation elsewhere. They are not
normal application startup commands. Screenshots prominently show OFFLINE UI TEST FIXTURES and
SIM-* fictional instruments. They are screenshots of the application, not current market data.

## External services / tests not performed

The build container could not resolve/reach the provider asset host. No real instrument-master
file was imported; parser coverage used documented-format fixtures. No access token was supplied.
Authenticated quotes, histories, option chains and entitlements were NOT verified. The adapters
implement official documented endpoints, but real-account testing is still required.

Not verified: Windows installation or App Control approval; Python 3.11 runtime; Docker build;
normal end-user browser networking; public deployment; authentication/tenant isolation; security
penetration testing; broker execution; real-market calibration; or genuine trading returns.

The tested environment used Python 3.13.5 on Linux with scikit-learn 1.8.0. The launcher targets
Python 3.11 on Windows. Do not describe a Linux test pass as proof of Windows compatibility.

## Reproduce

Use a new data directory, install requirements-dev.txt and run `python -m pytest -q`.
For manual UI verification start `python run.py`. A fresh Market Explorer should be empty until
catalogue refresh succeeds. Synthetic original research screens should remain clearly labelled.
Use your own authorized credentials only on your machine for provider integration tests.

## Clean delivery extraction check

The delivery ZIP was extracted into a fresh directory and the same suite was run there:
**146 passed in 5.71 seconds**. JavaScript syntax checks and Python module compilation also
passed from that extraction. The raw output is `artifacts/clean_extraction_tests.txt`.
No runtime database, broker credential, trained model or downloaded vendor master is included.
