# Stage 5c hypothesis results

All comparisons use frozen T5, the robustness run, seed `20261121`, five
temporal folds, and 2,000 bank-bootstrap resamples.

| hypothesis | result | verdict |
|---|---|---|
| H1a ensemble vs LR | XGB dPR-AUC CI [0.018, 0.129], dROC-AUC 0.104; Holm-adjusted fold p=0.125 | supported |
| H1b equal alert volume | recall advantage CI includes zero | not supported |
| H2 lead time | fewer than five non-zero event differences | descriptive only |
| H3 levels vs trends | dPR-AUC CI includes zero; fold p=0.3125 | not supported |
| H5 SHAP families | capital and profitability rank first and second | supported |

## H1a

Robustness XGB has pooled PR-AUC 0.212 versus LR 0.147 and ROC-AUC 0.851
versus 0.747. RF is also positive, but XGB is the qualifying ensemble after
Holm correction; fold-wise tests are complementary because n=5.

## H1b

Each period receives exactly the v1.1 red alert count, selecting the highest
model scores. The out-of-time recall is higher descriptively, but the
bank-bootstrap interval for the difference crosses zero.

## H2

`L = t_B - t_A` in quarters, where A is the first matched-FAR ML alert and B
is the first v1.1-red alert in the uninterrupted pre-event run. Right-censored
runs beginning at the bank's first observation are reported separately.
Novo Banco, Cyprus Cooperative Bank, Carige, and NordLB are out-of-time; the
remaining primary events use leave-one-event-out training and are not real-time.

## H3 and H5

The same model, folds, seed, and budget were used for levels-only versus
levels-plus-trends; the interval includes zero. Grouped mean absolute SHAP puts
capital and profitability first and second. Liquidity is empty because no
liquidity variable exists in the EBA transparency data; growth is also shown
as a separate family and assigned to asset quality in sensitivity analysis.

## Limitations

The event sample is small, fold tests have n=5, and bank bootstrap intervals
measure bank rather than row independence.
