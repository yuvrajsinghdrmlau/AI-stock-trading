# Competitor research and product decisions

Reviewed official product/developer documentation on 3 November 2026. Public product descriptions
are vendor claims about functionality, not independent profitability audits. Prices, offers,
market eligibility and data access change; the user's comparison table is not a verified price list.
This release does not copy proprietary code/models or claim equivalence to these mature services.

| Product | What public documentation supports | Design takeaway / correction |
|---|---|---|
| TrendSpider | AI strategy documentation lists Naive Bayes, logistic regression, KNN and random forest. | Compare explicit models; complexity is not proof of an edge. |
| Trade Ideas / Holly | Strategy discovery/testing and trading alerts, including overnight evaluation described by the vendor. | Separate strategy generation, qualification and risk; proprietary full logic is not disclosed. |
| Danelfin | Explainable stock/ETF scores 1-10 assessing relative performance against a benchmark over the next 3 months; US/European coverage. | A 10 score is not 100% certainty. This is not an India intraday/F&O model. |
| TradeStation | Developer API and EasyLanguage analysis/strategy infrastructure. | Brokerage/developer infrastructure is not a ready-made universally best prediction algorithm. |
| 3Commas | Crypto DCA/Grid and execution controls. | Grid/DCA are trading/execution approaches, not evidence that future direction can be guaranteed. |
| Pionex | Crypto exchange bots and trading fees. | No separate bot subscription does not mean cost-free trades or protection against market losses. |
| Tickeron | Pattern recognition and proprietary AI/agent descriptions. | Marketing win rates or simulated results do not establish a transferable live edge. |
| Public | Generated Assets uses AI to research/build custom stock baskets. | This is not the same task as an intraday option-profit predictor; the table's custody label is not a stop-loss mechanism. |
| AlgosOne | Vendor describes AI trading and reserve-fund arrangements. | A vendor reserve-fund claim is not a guarantee or independent loss insurance. |
| SaintQuant | The inspected site markets crypto-oriented automated packages and ROI targets. | The supplied $49/month multi-asset characterization was not established; marketed ROI is not audited evidence. |

## Official sources

- TrendSpider model types: https://help.trendspider.com/kb/ai-strategies/creating-an-ai-strategy-3-type-of-the-model
- Trade Ideas Holly introduction: https://www.trade-ideas.com/hollyguide/Who_is_Holly.html
- Trade Ideas overview: https://data.trade-ideas.com/what-is-trade-ideas/
- Danelfin methodology: https://danelfin.com/how-it-works
- TradeStation API: https://developer.tradestation.com/
- TradeStation EasyLanguage: https://developer.tradestation.com/easylanguage/
- 3Commas Grid: https://3commas.io/grid-bot
- Pionex: https://www.pionex.com/
- Tickeron: https://tickeron.com/
- Public Generated Assets: https://help.public.com/en/articles/12874264-what-is-generated-assets
- AlgosOne product explanation: https://help.algosone.ai/en/articles/12261159-how-algosone-works
- SaintQuant site inspected: https://saintquant.com/

## Implemented response to this research

This build combines an inspectable scanner, multiple strategy rules, calibrated candidate-model
comparison, cost-aware historical outcomes and a separate paper risk system. It does not claim that
these selected algorithms are universally superior. It can choose a constant prior instead of ML,
and can report that no model provides enough evidence. A production investment strategy requires
licensed representative data, additional independent validation and prospective evidence.
