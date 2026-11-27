# Hypotheses - data/ml/R1_golden

Selected model: **LR**

## H1a - ML vs LR (dPR-AUC)
- RF_vs_LR: -0.0583 CI95 [-0.147, 0.029] p_holm=1.0000
- XGB_vs_LR: -0.0781 CI95 [-0.166, 0.003] p_holm=1.0000

## H1b - ML vs R1 recall at equal alert volume (final test)
- ML 1.000 vs R1 0.872; diff +0.128 CI95 [0.000, 0.333]; supported=False

## H2 - lead time before R0 breach
- evaluated 0 of 8 breach banks; median L = None quarters; Wilcoxon exploratory

## H3 - levels+trends vs levels only
- dPR -0.0005 CI95 [-0.106, 0.133]

## H5 - SHAP families
- status: computed
- ranking: Asset_quality (0.007), Capital (0.003), Earnings (0.001), Growth (0.001), Concentration (0.000)
- Capital and Earnings rank 1-2: False

## H4 - pending - Stage 7 (BNM pilot)
