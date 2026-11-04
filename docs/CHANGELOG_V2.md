# Changes from v1 to v2

- Provider-backed NSE/BSE catalogue, instrument-key identity, search/pagination, suspended states.
- Local 25-instrument watchlist; catalogue-wide search is not restricted to those instruments.
- Read-only quote snapshots with feed/trade ages, spread and exchange-status checks.
- Incremental completed-bar history loading and opted-in intraday refresh while the page is open.
- Daily boards for Intraday, Swing, Delivery, plus a separate read-only option-chain tab.
- Chart workspace: EMA20/50/200, Bollinger bands, prior levels, VWAP, RSI, MACD, hover and zoom.
- Fixed soft-vote challenger, serialized local artifacts, lineage/hash/version checks and inference.
- Three disjoint expanding-history walk-forward windows in the research report.
- First-seen local signal audit; stale signals expire visibly; risk vetoes cannot be overridden by p.
- Regression tests increased from 66 to 146. Actual browser checks and explicit fixture previews.

Not implemented: never-fail models, deep neural forecasts, current stock tips, licensed feeds bundled
with the ZIP, streaming WebSockets, full-market continuous scans, fundamental/event research,
options-premium prediction, commercial customer auth, real broker orders or verified profitability.
