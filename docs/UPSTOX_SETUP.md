# Authorized data setup and troubleshooting

## Credentials stay on your machine

Use your own authorized Upstox API access and verify market-data entitlements. The app implements
read-only endpoints; it does not implement OAuth login, refresh tokens, broker balances or orders.
Follow the provider authentication process. Do not give this application someone else's credentials.

1. Stop India Quant. Copy `.env.example` to `.env` beside `run.py` (not `.env.txt`).
2. Set `UPSTOX_ACCESS_TOKEN=your_own_token` without sending it to anyone.
3. Restart using START_WINDOWS.bat. TOKEN CONFIGURED means a value exists, NOT that authentication
   succeeded. An unauthorized/expired token will produce an error; renew it through your broker.
4. Market Explorer: Refresh NSE + BSE catalogue, then search a real company/symbol/ISIN. Check exchange.
5. Add to watchlist. Chart & Filter Studio: choose strategy, Load / refresh candles. Select an
   intraday strategy for 15-minute data or swing/delivery for daily data.
6. AI strategy lab: run the chronological comparison, with walk-forward enabled. An experiment is
   bound to that instrument/strategy/history, not transferable to every stock. It may lack sufficient
   setup events or fail evidence gates. Do not weaken filters to force recommendations.
7. Daily Trade Desk: refresh snapshots. Optional auto-refresh polls while the page stays open.
   Already-loaded intraday bars refresh when due; daily bars and initial history require manual load.
8. F&O: watch an eligible underlying or index, open F&O, request available expiries and choose the
   exact date, then fetch its chain. Some underlyings have no listed contracts. No confidence model.

## Expected limitations and failures

- Catalogue refresh uses documented provider asset URLs. An asset-host outage, proxy or permission
  restriction can block the download. The old cache is preserved and marked stale when necessary.
  Both catalogue and suspension downloads must succeed. Never turn missing data into sample prices.
- With no catalogue, the directory intentionally contains zero securities. SIM-* rows in the original
  terminal are explicitly synthetic and are never masqueraded as an NSE/BSE master.
- A security appearing in search may not have sufficient historical data, ordinary cash-equity
  eligibility, liquidity or permissions for research. SME/special series may be searchable but blocked.
- Missing token, HTTP 401/403, rate limits, illiquid/missing quotes and stale last-trade timestamps
  produce errors or NO TRADE. Token expiration is not repaired automatically.
- Outside the normal session there will not be an executable intraday candidate. The app consults
  provider market status; special sessions and exchange conventions need separate review.
- Daily training initially requests up to roughly eight years; 15-minute training up to roughly one
  year in bounded chunks. Data availability depends on provider/instrument. New listings or sparse
  setups can fail minimum-sample rules. Network requests can take time; progress is shown.
- History revisions/corporate actions that alter the frozen model's stored prefix require retraining.
  This is intentional. Reusing an incompatible artifact would make the evidence misleading.
- CSV import works in the legacy lab but is not automatically mapped into the live catalogue. Use
  the provider loader for catalogue-bound models in this release.
- No stop orders, targets or paper exits are automatic. The kill switch blocks new paper entries;
  it is not a real broker cancel-all mechanism.

## Official references checked 3 November 2026

Instrument master and unique keys: https://upstox.com/developer/api-documentation/instruments/
Authentication: https://upstox.com/developer/api-documentation/authentication/
Full quote snapshots: https://upstox.com/developer/api-documentation/get-full-market-quote/
Historical candles: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
Intraday candles: https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/
Exchange status: https://upstox.com/developer/api-documentation/get-market-status/
Option contracts: https://upstox.com/developer/api-documentation/get-option-contracts/
Option chain: https://upstox.com/developer/api-documentation/get-pc-option-chain/
Rate limits: https://upstox.com/developer/api-documentation/rate-limiting/

Provider APIs and permissions can change. This version was tested offline with fixtures, not with
an authenticated real broker account. API access alone is not a commercial redistribution license.
