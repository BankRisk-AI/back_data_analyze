"""Candidate features built from the panel, and a first look at the evidence for them:
drift between train and test (KS) and separation of events (AUC, direction fixed on train)."""
from __future__ import annotations

from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np

from scripts.analyses.dataset import TEST_END, TEST_START, TRAIN_END
from scripts.analyses.draw_graph import DEFAULT_INDICATORS, NPL_BREAK, _month_end
from scripts.analyses.events import auc

VARIANTS = ("raw", "rank", "rz", "chg", "chg_rank", "chg_pct", "vol")
VARIANT_LABELS = {
    "raw": "level (as reported)",
    "rank": "rank among banks in the period",
    "rz": "robust z in the period",
    "chg": "12-month change of the level",
    "chg_rank": "12-month change of the rank",
    "chg_pct": "12-month relative change",
    "vol": "volatility (t, t-6, t-12)",
}
# indicators that are always positive, so a relative change makes sense
POSITIVE_LEVELS = (
    "cet1_ratio", "tier1_ratio", "total_capital_ratio", "leverage_ratio",
    "nace_hhi", "sovereign_hhi",
)
# no change or volatility across a definition break
BREAKS = {"npl_ratio": NPL_BREAK}


def _crosses_break(indicator: str, start, end) -> bool:
    """True when a definition break lies inside (start, end]."""
    brk = BREAKS.get(indicator)
    return brk is not None and start < brk <= end


def _add_changes(current: dict, year_ago, half_ago, ind: str) -> None:
    """Change, change of rank, relative change and volatility of one indicator for one row."""
    raw = (ind, "raw")
    if raw not in current or not year_ago or raw not in year_ago:
        return
    now, before = current[raw], year_ago[raw]
    current[(ind, "chg")] = now - before
    if (ind, "rank") in current and (ind, "rank") in year_ago:
        current[(ind, "chg_rank")] = current[(ind, "rank")] - year_ago[(ind, "rank")]
    if ind in POSITIVE_LEVELS and before > 0:
        current[(ind, "chg_pct")] = now / before - 1
    if half_ago and raw in half_ago:
        values = [before, half_ago[raw], now]
        current[(ind, "vol")] = float(np.std(values, ddof=1))


def build_features(rows: list[dict],
                   indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> dict:
    """{(bank_id, period): {(indicator, variant): value}} for all variants."""
    from scipy.stats import rankdata
    by_period = defaultdict(list)
    for r in rows:
        by_period[r["period"]].append(r)
    features = defaultdict(dict)
    for period, group in by_period.items():
        for ind in indicators:
            present = [r for r in group if r[ind] is not None]
            if len(present) < 5:
                continue
            values = np.array([r[ind] for r in present])
            ranks = rankdata(values) / len(values)
            median = np.median(values)
            iqr = np.percentile(values, 75) - np.percentile(values, 25)
            for r, value, rank in zip(present, values, ranks):
                f = features[(r["bank_id"], period)]
                f[(ind, "raw")] = float(value)
                f[(ind, "rank")] = float(rank)
                if iqr > 0:
                    f[(ind, "rz")] = float((value - median) / iqr)
    for (bank, period), current in list(features.items()):
        year_ago = features.get((bank, _month_end(period, -12)))
        half_ago = features.get((bank, _month_end(period, -6)))
        for ind in indicators:
            if not _crosses_break(ind, _month_end(period, -12), period):
                _add_changes(current, year_ago, half_ago, ind)
    return features


def _values_by_label(features: dict, group: list[dict], name: tuple):
    """Feature values of event rows and of non-event rows."""
    positive, negative = [], []
    for i in group:
        value = features.get((i["bank_id"], i["period"]), {}).get(name)
        if value is not None:
            (positive if i["event"] else negative).append(value)
    return positive, negative


def feature_evidence(features: dict, items: list[dict],
                     indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> list[dict]:
    """Per indicator and variant: KS train vs test, AUC on train and test."""
    from scipy.stats import ks_2samp
    known = [i for i in items if i["event"] is not None]
    train = [i for i in known if i["period"] <= TRAIN_END]
    test = [i for i in known if TEST_START <= i["period"] <= TEST_END]
    result = []
    for ind in indicators:
        for variant in VARIANTS:
            name = (ind, variant)
            pos_train, neg_train = _values_by_label(features, train, name)
            pos_test, neg_test = _values_by_label(features, test, name)
            if not (pos_train and neg_train and pos_test and neg_test):
                continue
            auc_train = auc(pos_train, neg_train)
            auc_test = auc(pos_test, neg_test)
            if auc_train < 0.5:
                auc_train, auc_test = 1 - auc_train, 1 - auc_test
            ks = ks_2samp(pos_train + neg_train, pos_test + neg_test).statistic
            result.append({
                "indicator": ind, "variant": variant, "ks": float(ks),
                "auc_train": auc_train, "auc_test": auc_test,
                "n_train": len(pos_train) + len(neg_train),
                "events_train": len(pos_train),
                "n_test": len(pos_test) + len(neg_test),
                "events_test": len(pos_test),
            })
    return result


def print_feature_evidence(evidence: list[dict]) -> None:
    """Table: drift (KS) and separation of events (AUC) for each variant."""
    print("\nKS: train vs test (lower = more stable; rank is uniform by construction)")
    print("AUC: direction fixed on train; 0.5 = no separation")
    print("indicator              variant      KS  AUC train  AUC test  events train/test")
    previous = None
    for e in evidence:
        if previous and previous != e["indicator"]:
            print()
        previous = e["indicator"]
        print(f"{e['indicator']:22s} {e['variant']:9s} {e['ks']:5.2f} "
              f"{e['auc_train']:10.2f} {e['auc_test']:9.2f}  "
              f"{e['events_train']:5d}/{e['events_test']}")


def features_figure(evidence: list[dict],
                    indicators: tuple[str, ...] = DEFAULT_INDICATORS):
    """Left: drift (KS) of level, robust z and change. Right: AUC on test per variant."""
    table = {(e["indicator"], e["variant"]): e for e in evidence}
    y = np.arange(len(indicators))
    fig, (left, right) = plt.subplots(1, 2, figsize=(14, 0.7 * len(indicators) + 2),
                                      sharey=True)

    def bars(ax, variants, key):
        height = 0.8 / len(variants)
        for k, variant in enumerate(variants):
            values = [table.get((ind, variant), {}).get(key, np.nan) for ind in indicators]
            ax.barh(y - 0.4 + height * (k + 0.5), values, height=height,
                    label=VARIANT_LABELS[variant])

    bars(left, ("raw", "rz", "chg"), "ks")
    left.set(title="Drift train -> test (KS, lower = more stable)", xlabel="KS")
    left.set_yticks(y)
    left.set_yticklabels(indicators, fontsize=8)
    left.invert_yaxis()
    left.legend(fontsize=7, frameon=False, loc="lower right")
    bars(right, VARIANTS, "auc_test")
    right.axvline(0.5, color="black", linewidth=0.8)
    right.set_xlim(0.3, 0.9)
    right.set(title="Events separated in the test period (AUC, direction from train)",
              xlabel="AUC")
    right.legend(fontsize=7, frameon=False, loc="lower right")
    fig.tight_layout()
    return fig, len(evidence)