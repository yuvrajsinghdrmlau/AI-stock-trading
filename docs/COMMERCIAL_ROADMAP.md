# Local product first, subscription service later

Prepared 3 November 2026 for the existing India Quant application. This is a product and
engineering plan, not a certification of investment performance or regulatory approval.

## What version 2.1 delivers

- Local stock search, public historical candles or user-supplied CSV, chart research and model studies.
- Conditional long-entry plans with a next-open range, reference stop/target, formulas for the
  actual fill, a conservative expiry and visible reasons for wait/blocked decisions.
- A dated record with source, rule/model status and version; rechecking before copying a plan.
- Links to users' own broker websites. No credentials, order payloads, custody or automatic execution.
- A clean distribution ZIP built with `python build_local_package.py`. It excludes `.env`, your
  journal/database, fitted models, the virtual environment and other personal runtime files.

The five existing strategy rules are unchanged. More visible plans do not establish a profitable
edge. Rules-only plans are unvalidated and do not have a manufactured confidence percentage.
Ordinary weekday timing is implemented; a complete exchange holiday/special-session calendar,
corporate-action reconciliation and live news/earnings checks are not implemented.

## If you have no personal broker API

| Route | Works in this build | What is required for a paid service |
|---|---|---|
| Public Yahoo history / your CSV | Daily/15-minute completed bars and conditional daily research | Verify the provider's rights for the intended use. This app grants no market-data licence. |
| Your own authorized Upstox token | History, snapshots and existing market/model/risk checks | Confirm permitted use; a personal trading token does not establish customer redistribution rights. |
| Licensed NSE/BSE or authorized-vendor feed | Procurement route documented; adapter not yet implemented | A contract covering display, derived signals, storage, end-user access and any redistribution, then provider-specific integration/testing. |
| Official NSE/BSE website | Browser links for users to inspect themselves | Not an automatic free commercial feed. Website availability does not imply permission to scrape or resell data. |

NSE offers direct real-time subscriptions, authorized vendors and a stock-wise CSV product. This
means you do not need a personal Upstox account to procure data for your business, although the
chosen service will have its own delivery mechanism, credentials, entitlements and costs.
[NSE real-time products](https://www.nseindia.com/static/market-data/real-time-data-subscription)

NSE's website terms prohibit systematic/automated scraping. Its disclaimer also says displayed
market information may not be real time. Its data policy requires agreements for commercial use
and permits redistribution only as agreed.
[Website terms](https://www.nseindia.com/static/nse-terms-of-use),
[disclaimer](https://www.nseindia.com/static/nse-disclaimer),
[data policy](https://www.nseindia.com/static/market-data/nse-data-policy)

BSE describes real-time, delayed, historical and corporate data subscription products for software
vendors and other customers. Obtain the current quote and rights for your actual use.
[BSE information products](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf)

NSE's public MCP access is explicitly informational/non-commercial; it is not an alternative
licence for a commercial trading-signal service.
[NSE MCP terms](https://www.nseindia.com/nse-mcp)

## Stage 1: prepare a local product

1. Decide the exact paid service with qualified Indian securities counsel. Charging for automated
   buy/sell reports can fall within the research-analyst framework; having users place trades
   elsewhere does not itself remove recommendation-service obligations. Personalization can bring
   investment-adviser requirements into scope. A disclaimer or an "education" label is not a
   substitute for the applicable registration, disclosures and duties.
   [SEBI Research Analyst regulations](https://www.sebi.gov.in/legal/regulations/nov-2025/securities-and-exchange-board-of-india-research-analysts-regulations-2014-last-amended-on-november-25-2025-_98248.html),
   [2026 RA master circular](https://www.sebi.gov.in/legal/master-circulars/feb-2026/master-circular-for-research-analysts_99571.html)
2. Resolve data licensing before paid customer distribution. Get written terms for local customer
   use and generated signals. Do not include your personal API token in any package.
3. Validate frozen strategies on untouched periods with costs, and retain prospective paper
   records. Review failure cases, revisions, gaps and drawdown. No pass rate is an income promise.
4. Pilot installation and usability with a small number of consenting testers. Collect startup
   failures and whether users understand timestamps, conditional entries and expiry. Keep simulated
   results visibly distinct from real fills.
5. Define the commercial offer: software access, installation/support, updates and any regulated
   research service. Price after measuring support/data/compliance costs and willingness to pay.
   The software's MIT licence permits sale subject to its notice conditions; it does not license
   exchange data or grant regulatory permission. Keep LICENSE and THIRD_PARTY.md in distributions.

## Stage 2: hosted subscriptions

Keep the current loopback build local. A hosted version needs a separate deployment design with
customer authentication, tenant isolation, managed secrets, licensed shared-data entitlements,
payments/refunds, per-customer access controls, backups, durable jobs, monitoring and security
review. The current local write token is not customer authentication. SQLite audit records are
not a tamper-proof or independently verified performance record.

Users can continue manual broker execution. Deep links or a future prefilled order basket require
documented broker support, consent and a separate review; ordinary website links do not execute.
Automatic order execution is a further product decision and is outside this release.

Outstanding details requiring your decision: legal business/service classification, data vendor and
budget, intended customer group, and local licence/support pricing. Billing and hosted accounts
have not been added to version 2.1.
