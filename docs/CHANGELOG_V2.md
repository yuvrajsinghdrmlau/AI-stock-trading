# Changes from v1 to v2

## Current branch: decision toolkit

- Indian-session entry timing with completed-bar, missing-slot and first-trigger expiry checks.
- Manual ATR/range stop scenarios, configurable target R and cost-capped share sizing.
- Cost-aware fixed-rule historical replay, recent-period reporting and seeded block resampling.
- India-focused, on-demand RSS headlines with publisher/date, event tags and official filings link.
- Persisted one-shot price alerts, recent-price checks and opt-in visible-page monitoring.
- Editable untouched practice accounts; journal results cannot be rewritten by budget edits.
- Saved scan results, original quote timestamps and remembered trade-type/universe preferences.
- Desktop/mobile browser verification of the whole toolkit flow; no new runtime dependencies.

## Current branch: beginner desk and broad discovery (4 November 2026)

- Beginner-first Delivery/Intraday/Swing/Calls & puts/Futures navigation and glossary.
- Official Nifty 50/100/200/500 membership, all regular NSE and all F&O universes;
  scan size no longer follows the 25-instrument live-watchlist limit.
- Symbol+ISIN matching, membership caching and explicitly labelled catalogue fallback.
- Ten-stock progress batches, partial results, candle caching and stop-after-batch.
- Small price graphs, paged cards, local result search and simpler broker review steps.
- Current NSE F&O contract catalogue with exact expiry, strike and lot identities.
- Bullish call, bearish put and buy/sell futures ideas. Separate underlying-only ideas
  from broker-quoted premium/futures plans; no manufactured contract prices.
- Contract quote, spread, volume, expiry and account-limit checks. No auto orders.
- Live source checks plus regression and desktop/mobile browser verification.

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

Not implemented: never-fail models, deep neural forecasts, licensed feeds bundled
with the ZIP, streaming WebSockets, full-market continuous scans, fundamental/event research,
options-premium prediction, commercial customer auth, real broker orders or verified profitability.
