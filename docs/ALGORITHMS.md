# Algorithms and research contract

## Strategy rules actually implemented

| Strategy | Mode / bars | Rule family | Default max holding period |
|---|---|---|---|
| Trend pullback | Swing / daily | Close above EMA20 above EMA50; controlled pullback, positive candle and RSI bounds. | 10 bars |
| Range breakout | Swing / daily | Break prior 20-bar high with trend and relative-volume confirmation. | 10 bars |
| Position trend | Delivery / daily | Price above EMA50 above EMA200, positive 20-bar momentum, bounded RSI. Price-only, no fundamentals. | 20 bars |
| Opening-range breakout | Intraday / 15m | Break the actual first 30-minute range, above VWAP, volume confirmation, time restriction. | 6 bars or session end |
| VWAP continuation | Intraday / 15m | Uptrend, controlled VWAP pullback, positive continuation and relative volume. | 6 bars or session end |

Source code is the exact specification. All are long-only cash-equity hypotheses, not validated
commercial strategies. No short borrow, futures margin, option-premium ML or automatic orders.
Indicator warm-up and corporate-action assumptions must be inspected on each real dataset.
Intraday volume compares with previous sessions at the same time slot, rather than mechanically
comparing a morning candle with a closing candle. No learned market-regime classifier is included;
regime labels are transparent EMA-based rules.

## The target

For an eligible signal at completed bar t, enter hypothetically at the next bar's open if the gap
passes the configured ATR filter. Stop distance is 1.5 ATR by default; target is 2 times this risk.
Label 1 means the target is reached before the stop within the horizon. Label 0 includes stops and
timeouts. **A profitable timeout is still label 0.** Thus this is not a probability of net profit.
Latest-bar probabilities are conditional on the future next-open entry qualifying. A model score
alone does not create an executable instruction or override a failed current rule.

## Candidate models and selection

The prior baseline is the calibration period's smoothed target-hit prevalence. ML candidates are:
standardized logistic regression, ExtraTreesClassifier (120 trees, max depth 5, min leaf 12), and
HistGradientBoostingClassifier (100 iterations, depth 3, 7 leaves, learning rate .05, L2=3).
A fifth candidate is a fixed equal-weight soft vote of the three separately sigmoid-calibrated
members. Its aggregate is NOT separately calibrated; reliability is evaluated rather than assumed.
No LSTM, transformer, reinforcement-learning policy, Optuna search, XGBoost or LightGBM is hidden
behind the UI. These are not necessarily inferior or superior: they are simply not implemented.

Fifteen past-only price/volume/volatility features are built in `strategies.py`. Scaling is fitted
inside the logistic training pipeline. Non-baseline probabilities are sigmoid-calibrated using a
separate logistic model on calibration observations. A fit does not ensure calibration on new data.

Split contiguous bar history: 50% training, 18% calibration, 15% champion selection, 17% final test.
Purge events whose label outcome crosses a split boundary. Training may retain overlapping events;
calibration, selection and reported final reliability examples are nonoverlapping. This reduces
some overlap but does not establish independent identically distributed financial observations.

Minimum eligible events: 60 training / 16 calibration / 15 selection / 15 final. Both outcomes
need representation. Insufficient evidence gives no estimate, not a fallback invented probability.
The champion minimizes **selection-period Brier score**. The final test never selects the champion.
Brier measures overall probabilistic prediction quality, not calibration alone. Calibration bins,
base-rate comparison and economic outcomes are separate checks.

The main model uses one four-way chronological holdout. The optional v2 walk-forward report uses
three disjoint test windows, covering bars 55-70%, 70-85% and 85-100%. Earlier history expands for
training, calibration and selection, with label purging at boundaries. Each window trains new
models and selects only on its earlier selection period. Presets are fixed, not an exhaustive
nested hyperparameter search. Fold P&L is summed descriptive P&L from separately reset accounts,
not a compounded continuous trading account. The saved inference artifact comes from the main
four-stage run; walk-forward pass/fail is not an extra automatic deployment gate.

Repeated manual threshold/model experimentation consumes test independence. Freeze a specification,
then acquire genuinely untouched future history and prospectively record paper decisions.

## Simulation assumptions

Signal at bar close; next-open conditional entry; no same-close entry. Defaults: 5 basis points
adverse slippage each side; 40 basis points approximate round-trip charges, apportioned per leg.
This is a user-adjustable assumption, not current Indian statutory tax/brokerage computation.

If an open gaps below the stop, fill at the worse open with slippage. If stop and target appear
inside the same OHLC candle, assume stop first. Gap through target fills conservatively at the
target. Intraday holds do not cross sessions; affected missing-bar/partial-session events are
rejected. Positions are sequential/nonoverlapping and integer-share sized, without leverage.

The rules-only baseline and ML-filtered sequence share the final period and cost/risk assumptions.
Same-exposure buy-and-hold is also shown, but has a different risk profile. Drawdown includes a
bar-close hypothetical-liquidation curve plus closed-trade statistics, not tick-level intrabar
worst-case loss. Liquidity, spread dynamics, exchange circuits, corporate actions and queue fills
are not fully modeled. Net P&L may therefore differ materially from any real result.

## Interpretation and limits

Permutation feature sensitivity is computed on the selection period; it is not SHAP, causal
attribution or independent proof of economic value. Reliability-bin Wilson intervals are approximate
binomial intervals and do not correct for all time/stock dependence or multiple testing.

Research gates currently require model improvement over the selection prior, better final Brier
than the prior, at least 30 filtered final trades, positive net P&L and profit factor above 1.1.
These are experimental policies, not statistically sufficient commercial release criteria.
Synthetic studies remain synthetic even when gates pass. Final-test gates can be overfit by
repeatedly searching settings, stocks and periods.

Fitted estimators, calibrators, feature schema and training percentile ranges are now persisted in
trusted local joblib files with hashes and scikit-learn versions. Instrument/strategy lineage and
unchanged full training/evaluation history prefixes are required. Models older than 30 days for
daily or 7 days for intraday are marked unvalidated. Four or more features outside the training
1st-99th percentiles trigger an elementary range-shift warning. This is not formal drift detection,
not conformal prediction and not an independently measured safety guarantee.

No historical point-in-time market-wide universe, fundamentals, news/event feed, true out-of-time
India benchmark or multi-asset portfolio optimizer is included. A current provider master does not
solve historical survivorship bias. Price adjustment/corporate-action semantics require verification.
First-seen local signal logs record outputs, not independently reconciled fills or eventual results.

## Primary technical reference

Scikit-learn probability calibration (accessed 2026-11-03):
https://scikit-learn.org/stable/modules/calibration.html

Scikit-learn distinguishes reliability from discrimination and warns that lower Brier alone does
not prove better calibration. This is why the UI separately shows reliability buckets and outcomes.
