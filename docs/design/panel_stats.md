# Panel descriptive statistics

Computed directly from the 4,367 production `panel_row` rows after the
Stage 3d-fix rebuild on 2026-11-15. Missing percentages use all rows.
Stored outlier flags use per-period median +/- 3 MAD, with at least 20
non-null banks in the period and feature. No values are imputed or winsorised.

| feature | N | missing % | mean | median | p5 | p95 | min | max | k=3 raw flags |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cet1_ratio |4359|0.18|0.202982|0.159765|0.116909|0.357209|0.015046|5.303164|548|
| tier1_ratio |4359|0.18|0.214260|0.169712|0.122102|0.374244|0.015046|5.303164|531|
| total_capital_ratio |4359|0.18|0.236790|0.193238|0.141167|0.384521|0.027597|5.303164|532|
| leverage_ratio |4097|6.18|0.071909|0.061560|0.038700|0.127430|0.005780|0.995587|423|
| npl_ratio |3995|8.52|0.047170|0.025911|0.001690|0.193315|0.000000|0.547251|478|
| stage2_share |3003|31.23|0.090920|0.079155|0.009789|0.184106|0.000000|0.762518|203|
| roe_annualised (RoCET1) |4013|8.11|0.086925|0.088495|-0.050002|0.235219|-7.062032|1.456932|403|
| loan_growth_qoq |2769|36.59|0.013735|0.008005|-0.054487|0.081772|-0.761961|3.000000|395|
| loan_growth_yoy |2884|33.96|0.059696|0.028099|-0.142058|0.198568|-0.784888|16.000000|425|
| nace_hhi |2605|40.35|0.230134|0.151989|0.100798|0.681693|0.079932|1.000000|559|
| sovereign_hhi |2122|51.41|0.467857|0.432343|0.122063|0.968390|0.065049|1.000000|15|

## Median and mean by year

The 2023 YoY median is `0.015227`, versus a QoQ median of `0.003789`.
This table was generated directly from `panel_row`; the query is reproduced
in the appendix.

| year | YoY median | YoY mean | QoQ median |
|---:|---:|---:|---:|
|2014|—|—|—|
|2015|0.025879|0.041012|—|
|2016|-0.001868|0.079156|—|
|2017|0.026329|0.136251|—|
|2018|0.026114|0.039287|-0.004615|
|2019|0.033402|0.054795|0.009323|
|2020|0.032893|0.050736|0.003442|
|2021|0.028441|0.037082|0.008842|
|2022|0.046300|0.053013|0.010386|
|2023|0.015227|0.032304|0.003789|
|2024|0.026596|0.072175|0.007785|
|2025|0.044931|0.081217|0.012407|

## Independent growth verification

The first implementation compared the wrong loan base and had **3,235 YoY
and 2,843 QoQ mismatches** against an independent calendar-join query. The
builder now sums only `Perf_Status=0`, joins YoY by `(year, month)`, and joins
QoQ by calendar month only from 201812 onward. The corrected verification
result is **0 YoY and 0 QoQ mismatches** at absolute tolerance `1e-9`.
201809 is deliberately not QoQ: 201806 is the final semi-annual observation.

| bank | period | loans | stored QoQ | stored YoY | SQL QoQ | SQL YoY |
|---|---|---:|---:|---:|---:|---:|
| ABN AMRO Bank N.V. | 202506 | 310506.709 | 0.0154 | 0.0254 | 0.0154 | 0.0254 |
| THE BANK OF NEW YORK MELLON | 202312 | 1127.863 | -0.1338 | -0.2999 | -0.1338 | -0.2999 |
| Revolut Holdings Europe UAB | 202506 | 7113.626 | 0.4572 | 1.5298 | 0.4572 | 1.5298 |

There are 18 `extreme_growth` rows. Only one bank has more than three:
Revolut Holdings Europe UAB (`485100FX5Y9YLAQLNP12`), with eight rows from
202309 through 202506. Its raw total loans rise from 610.490 to 7,113.626
over that interval (610.490, 1,530.405, 1,731.755, 2,811.883, 3,272.600,
4,289.312, 4,881.726, 7,113.626), consistent with rapid business growth and
not a missing-data `-1.0` artifact. The remaining extreme rows are sparse
bank-entry, merger, or scope-change observations and remain explicitly
flagged.

## Leverage review

The three zero leverage observations (201612) have raw leverage ratio,
Tier 1 numerator, and exposure all equal to zero. They are reporting errors,
not genuine zero leverage, and are now NULL with `implausible_value`.
High values are confirmed by the raw Tier 1 / exposure facts: for example,
C.R.H. is `553.415 / 555.868 = 0.995587`, State Street Luxembourg is
`480.735 / 598.848 = 0.8028`, and Banque centrale de compensation is
`215.142 / 349.322 = 0.6159`. These are genuine specialist/clearing-bank
observations and were retained.

## Outlier sensitivity

Counts are feature-period flags, with positive values only for log transforms.

| feature | k=3 raw | k=3 log | k=5 raw | k=5 log |
|---|---:|---:|---:|---:|
| cet1_ratio |548|461|348|249|
| tier1_ratio |531|464|353|246|
| total_capital_ratio |532|449|333|236|
| leverage_ratio |423|276|174|79|
| npl_ratio |478|390|274|105|
| stage2_share |203|222|67|95|
| roe_annualised |403|362|178|89|
| loan_growth_qoq |395|146|173|27|
| loan_growth_yoy |425|219|185|74|
| nace_hhi |559|417|406|186|
| sovereign_hhi |15|48|0|0|

Sovereign HHI is evaluated only in June and December, where it has 2,122
values. Its k=3 raw rule produces 15 flags; the earlier zero count came from
the incorrect global rule. Periods with fewer than 20 banks are excluded by
design.

## 2016 NPL continuity proof

The 2016 workbook is unavailable, but code `0` (total) and code `2`
(non-performing) pass the continuity proof for 78 common banks. Spearman
correlations against 2015-06 and 2016-12 are `0.986166` and `0.993121`;
median absolute differences are `0.005127` and `0.003749`. The proof and
dimension meanings are recorded in `config/dimensions/2016.yaml`, and 2016
NPL is populated.

## Stage 3d data checks

The 202006 finding is a permanent definition change, not a one-period source
anomaly. In the 2019, 2020S, and 2020A dimension dictionaries, `Exposure=0`
is the only 2520603 row present for total portfolio/country/status/NACE
dimensions; no separate cash-balances or demand-deposits exposure row exists.
The 2020A SDD label still says “Gross carrying amount on Loans and advances
(including at amortised cost and fair value)”, so the SDD label alone does not
record the break. This rules out a reproducible subtraction adjustment.

The version-controlled specialist list contains 7 banks: one central
counterparty, two custody banks, two public funding agencies, one
covered-bond/refinancing institution, and one additional custody bank. The
list is based on the median-ratio screen (median leverage above 0.25 or CET1
above 0.5) plus name-based institutional evidence; values are unchanged and
all rows carry `specialist_institution`. C.R.H.'s 202106 leverage is
0.995587, with total leverage exposure 555.868. The available `tr_oth` facts
contain no Total Assets observation for C.R.H. in that period, so the 5%
test cannot be established; the value is retained and is not marked
`implausible_value`.

## 2020 loans definition change

The independent check confirms a **permanent definition change** in `tr_cre`.
quarter-by-quarter median and IQR below use banks present in both quarters;
`tr_cre` is master 2520603 with total dimensions and `Perf_Status=0`.
`tr_oth` is the independent sum of masters 2521017 and 2521019 across
`ASSETS_Stages=1,2,3` and total remaining dimensions.

| period | tr_cre N | tr_cre median | tr_cre IQR | tr_oth N | tr_oth median | tr_oth IQR |
|---|---:|---:|---:|---:|---:|---:|
|201812|113|-0.004615|[-0.028058,0.019851]|110|0.001532|[-0.020072,0.015090]|
|201903|115|0.023605|[0.002479,0.046891]|112|0.016482|[0.003263,0.037766]|
|201906|117|0.003120|[-0.014084,0.020324]|114|0.008101|[-0.009249,0.024463]|
|201909|113|0.010464|[-0.005576,0.025087]|110|0.007765|[-0.006721,0.021629]|
|201912|115|0.006432|[-0.029317,0.028604]|112|-0.002174|[-0.024361,0.011912]|
|202003|113|0.017115|[-0.011700,0.048064]|110|0.008039|[-0.010730,0.029897]|
|202006|119|-0.097369|[-0.161752,-0.055345]|116|0.003595|[-0.017617,0.026576]|
|202009|99|-0.001930|[-0.022943,0.012715]|96|-0.004475|[-0.023316,0.012155]|
|202012|102|0.002214|[-0.020572,0.020155]|99|0.003400|[-0.019763,0.020954]|
|202103|102|0.010558|[-0.000609,0.029851]|99|0.010748|[-0.001463,0.028766]|
|202106|106|0.006689|[-0.011850,0.023662]|103|0.005237|[-0.017421,0.021772]|
|202109|97|0.005459|[-0.006627,0.015550]|94|0.005409|[-0.004123,0.015534]|
|202112|101|0.011331|[-0.003827,0.025324]|98|0.012147|[-0.003660,0.025358]|
|202203|102|0.014853|[0.001545,0.037276]|99|0.014928|[0.002833,0.036940]|
|202206|106|0.017981|[0.002052,0.034281]|103|0.017078|[0.003854,0.037046]|
|202209|105|0.009825|[-0.008484,0.022208]|102|0.010922|[-0.004660,0.023311]|
|202212|109|-0.005631|[-0.029911,0.014083]|106|-0.003920|[-0.027737,0.014191]|
|202303|109|0.002268|[-0.011259,0.019227]|106|0.002048|[-0.010823,0.018625]|
|202306|109|0.005826|[-0.012944,0.019679]|106|0.006327|[-0.010136,0.019300]|
|202309|104|0.003766|[-0.010645,0.018774]|101|0.003979|[-0.009470,0.019629]|
|202312|106|0.005715|[-0.014777,0.025932]|103|0.003267|[-0.015081,0.019487]|
|202403|105|0.004121|[-0.009690,0.023645]|102|0.005278|[-0.008982,0.022569]|
|202406|108|0.011872|[0.002410,0.025565]|105|0.011564|[0.000059,0.025308]|
|202409|101|0.003211|[-0.009218,0.013874]|98|0.003955|[-0.008420,0.015303]|
|202412|104|0.013650|[-0.001406,0.032404]|101|0.015656|[-0.002596,0.033205]|
|202503|104|0.012866|[-0.002915,0.033695]|101|0.012374|[-0.003627,0.032206]|
|202506|104|0.010811|[-0.001053,0.033145]|101|0.013759|[0.000639,0.033878]|

The explicit break comparison is `tr_cre` median **-9.7369%** versus
`tr_oth` **+0.3595%** in 202006, followed by `tr_cre` **-0.1930%** and
`tr_oth` **-0.4475%** in 202009. The old-definition ratio is stable at
1.1212 (IQR 1.0616--1.2023) in 201809 and 1.1229 (1.0792--1.2455) in
202003; it becomes 1.0030 in 202006 and remains 1.0028 in 202009. The
202003 per-bank difference is therefore the old-definition excess, not an
identifiable single Exposure row. Its typical scale is about
`1 - 1/1.1229 = 10.96%`.

Representative 202003 differences (`tr_cre - tr_oth`) are:

| bank | tr_cre | tr_oth | difference |
|---|---:|---:|---:|
| Barclays Plc |972930.414|594598.862|378331.552|
| DEUTSCHE BANK AKTIENGESELLSCHAFT |834818.872|629564.748|205254.124|
| BNP Paribas |1114991.635|923631.257|191360.378|
| Société générale S.A. |691306.442|509543.751|181762.691|
| Nykredit Realkredit A/S |193857.689|15450.714|178406.975|

No difference equals a distinct 2520603 Exposure row because the decoded
total-dimension extract has only `Exposure=0`; the excess is embedded in the
old total. The cash/demand-deposit hypothesis is economically consistent
with the FINREP change, but cannot be mechanically adjusted from these facts.

The ten largest 202006 `tr_cre` drops are:

| bank | tr_cre QoQ | tr_oth QoQ |
|---|---:|---:|
| THE BANK OF NEW YORK MELLON |-0.896871|-0.249950|
| RBC Investor Services Bank S.A. |-0.559365|0.045719|
| UBS Europe SE |-0.469988|-0.225120|
| Bank of Valletta Plc |-0.438538|0.006720|
| Akciju sabiedrība "Citadele banka" |-0.423282|-0.009493|
| Citibank Holdings Ireland Limited |-0.405669|-0.076456|
| Hellenic Bank Public Company Ltd |-0.371357|-0.033868|
| DekaBank Deutsche Girozentrale |-0.353618|-0.122963|
| Precision Capital S.A. |-0.337662|-0.059275|
| Bank of Cyprus Holdings Public Limited Company |-0.318230|-0.081372|

The permanent-break handling keeps raw loan values and uses `series_break`.
It flags all pre-202006 `npl_ratio`, `loan_growth_qoq`, and
`loan_growth_yoy` values, nulls only the 202006 QoQ crossing, nulls YoY for
202006, 202009, 202012, and 202103, and restores 202009 QoQ and 202106 YoY.
The 202006 `npl_ratio` is restored because it already uses the new definition.
The 2019 NPL median is unchanged at 0.026572 before and after; no denominator
adjustment was possible.

## Appendix: reproducibility queries

The growth check uses a `loans` CTE grouped by
`master 2520603`, total dimensions, and `Perf_Status=0`, then joins the same
bank by calendar year/month for YoY and by calendar month minus three months
for QoQ. It applies the permanent-break rule to cross-definition pairs and
compares both NULL status and numeric values to `panel_row` with
`abs(diff) > 1e-9`. The yearly table uses:

```sql
SELECT v.year,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY p.loan_growth_yoy)
         FILTER (WHERE p.loan_growth_yoy IS NOT NULL) AS yoy_median,
       avg(p.loan_growth_yoy) AS yoy_mean,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY p.loan_growth_qoq)
         FILTER (WHERE p.loan_growth_qoq IS NOT NULL) AS qoq_median
FROM panel_row p
JOIN dataset_version v USING (version_id)
GROUP BY v.year
ORDER BY v.year;
```
