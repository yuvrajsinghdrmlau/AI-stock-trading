# v2 status note

Read this as a launch checklist, not an implementation claim. The local v2 build adds directory,
read-only snapshots and saved research inference. It does NOT complete commercial deployment.
Authentication/tenant isolation, licensed redistribution, broker/exchange approvals, durable jobs,
independent performance validation, security review, reconciliation and incident operations remain.
Appropriate market-data rights, an authorized source and regulatory advice are required for the
intended commercial use. Live features additionally need an entitled live feed; a local historical
research product does not universally require a live-data subscription.
The older checklist below describes target controls; anything not explicitly implemented in README
must be treated as outstanding. No customer onboarding or paid recommendation service is enabled.

# Public deployment gates - NOT completed by this ZIP

This is a local developer release, not a deployable regulated brokerage or licensed advisory service.
Do not remove the Host/Origin checks and expose it publicly as a shortcut. The optional Docker
recipe is local-only and untested; it is not cloud hosting or customer access infrastructure.

## Before customer access

1. **Legal service classification.** Engage qualified Indian securities counsel to determine the
   applicable research-advisory/algo-provider/broker obligations for the exact intended product,
   including recommendations, personalization, marketing and execution. Review current SEBI and
   exchange requirements with the partner broker. This software is not a substitute for that review.
2. **Data rights.** Acquire explicit entitlements for storage, derived use, customer display and
   redistribution. A personal API token does not by itself establish commercial redistribution rights.
3. **Identity and tenancy.** Authentication, MFA, account isolation, roles, password/session recovery,
   tenant-scoped authorization and database migration are not implemented. A local session token is
   not customer identity. Plan a managed PostgreSQL migration with tested backups and restoration.
4. **Operations.** TLS, secret management, rate limits, durable queued jobs, health/latency monitoring,
   alerting, deployment rollback, incident response, disaster recovery and security assessment.
5. **Data correctness.** Licensed live feed, timestamp/sequence checks, reconnect recovery, exchange
   calendar, corporate actions, point-in-time universe, quality SLAs and entitlement enforcement.
6. **Research approval.** Reproducible data/model artifacts, locked release policy, multi-regime
   untouched evaluation, realistic costs and liquidity, prospective timestamped paper results,
   independent review and customer-facing limitations. An attractive in-sample chart is inadequate.
7. **Execution.** Only after an approved broker integration: customer consent/permissions, required
   algorithm identifiers and controls, order state machine, partial fills, duplicate prevention,
   timeout recovery, position reconciliation and account-wide emergency controls. Current real-order
   endpoint refuses all requests and there is no brokerage execution adapter.
8. **Recordkeeping.** Exportable research/recommendation versions, immutable/retained audit storage,
   complaint procedures and applicable disclosures. Current SQLite audit records are not tamper-proof.

## Practical first product scope

A narrowly scoped, legally reviewed cash-equity research and paper-trading product is a more coherent
first engineering target than launching recommendations, options bots, custody and full execution
simultaneously. This is a design recommendation, not a legal conclusion or income forecast.
Keep the user's Rs 10,000 trading capital separate from business, data and compliance expenses.

## Primary sources to verify before launch

NSE Data Sharing and Usage Policy:
https://www.nseindia.com/static/market-data/nse-data-policy

SEBI Research Analyst master circular landing page, 6 February 2026:
https://www.sebi.gov.in/legal/master-circulars/feb-2026/master-circular-for-research-analysts_99571.html

Upstox V3 historical-candle contract:
https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/

Microsoft Application Control event explanations (for local binary blocks):
https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/event-id-explanations

Read the full currently applicable documents and broker contracts with appropriate professionals.
This file does not certify regulatory compliance or provide a legal opinion.
