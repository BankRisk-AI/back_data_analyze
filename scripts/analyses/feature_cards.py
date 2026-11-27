"""Feature cards: the evidence for each candidate feature and a selection rule fixed in advance.

Everything used to decide comes from training periods (<= 2020-12) only: coverage, drift
inside training (<= 2017 vs 2018-2020), AUC with a bank-cluster bootstrap CI, stability of
the AUC direction across training years, redundancy with a stronger feature.
The test period (2022-2024) is reported next to it but never used to decide.
Also: correlation between features, VIF of the kept set, and what each kept feature covers.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

from scripts.analyses.dataset import TEST_END, TEST_START, TRAIN_END
from scripts.analyses.draw_graph import DEFAULT_INDICATORS
from scripts.analyses.features import VARIANTS

EARLY_END = date(2017, 12, 31)
BOOTSTRAP = 500
RULE = {
    "min_coverage": 0.5,          # present in at least half of the training rows
    "min_auc_ci_low": 0.5,        # lower end of the 95% bank-cluster CI above 0.5
    "min_sign_stability": 0.6,    # same direction in at least 60% of training years
    "max_ks_within_train": 0.15,  # stable inside training (<= 2017 vs 2018-2020)
    "redundant_rho": 0.8,         # |Spearman| with a stronger kept feature = redundant
}
# check these names against the category table used for H5 in chapter 3
CATEGORY = {
    "cet1_ratio": "Capital",
    "tier1_ratio": "Capital",
    "total_capital_ratio": "Capital",
    "leverage_ratio": "Capital",
    "npl_ratio": "Asset quality",
    "stage2_share": "Asset quality",
    "roe_annualised": "Earnings",
    "loan_growth_yoy": "Growth",
    "loan_growth_qoq": "Growth",
    "nace_hhi": "Concentration",
    "sovereign_hhi": "Concentration",
}


# ---------- helpers ----------

def _auc(positive, negative) -> float:
    """Rank-based AUC: probability that an event value is higher than a non-event value."""
    from scipy.stats import rankdata
    n1, n0 = len(positive), len(negative)
    if n1 < 5 or n0 < 5:
        return float("nan")
    ranks = rankdata(np.concatenate([positive, negative]))
    return float((ranks[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _value(features: dict, item: dict, name: tuple):
    return features.get((item["bank_id"], item["period"]), {}).get(name)


def _key(feature: str) -> tuple:
    """'cet1_ratio:rz' -> ('cet1_ratio', 'rz')."""
    indicator, variant = feature.split(":")
    return indicator, variant


def _labelled(items: list[dict]):
    """Labelled training rows (<= 2020) and labelled test rows (2022-2024)."""
    known = [i for i in items if i["event"] is not None]
    train = [i for i in known if i["period"] <= TRAIN_END]
    test = [i for i in known if TEST_START <= i["period"] <= TEST_END]
    return train, test


def _pos_neg(features: dict, group: list[dict], name: tuple):
    """Arrays of feature values for event rows and non-event rows."""
    pos, neg = [], []
    for i in group:
        v = _value(features, i, name)
        if v is not None:
            (pos if i["event"] else neg).append(v)
    return np.array(pos, dtype=float), np.array(neg, dtype=float)


def _present(features: dict, group: list[dict], name: tuple) -> list[float]:
    values = (_value(features, i, name) for i in group)
    return [v for v in values if v is not None]


def _bootstrap_ci(features: dict, group: list[dict], name: tuple, seed: int = 0):
    """95% CI of the AUC when whole banks are resampled."""
    by_bank = defaultdict(lambda: ([], []))
    for i in group:
        v = _value(features, i, name)
        if v is not None:
            by_bank[i["bank_id"]][0 if i["event"] else 1].append(v)
    banks = [(np.array(p, dtype=float), np.array(n, dtype=float))
             for p, n in by_bank.values()]
    rng = np.random.default_rng(seed)
    results = []
    for _ in range(BOOTSTRAP):
        chosen = rng.integers(0, len(banks), len(banks))
        pos = np.concatenate([banks[k][0] for k in chosen])
        neg = np.concatenate([banks[k][1] for k in chosen])
        results.append(_auc(pos, neg))
    results = np.array(results)
    results = results[~np.isnan(results)]
    if len(results) == 0:
        return float("nan"), float("nan")
    low, high = np.percentile(results, [2.5, 97.5])
    return float(low), float(high)


def _yearly_aucs(features: dict, train: list[dict], name: tuple) -> list[float]:
    """AUC in each training year with at least 5 events and 5 non-events."""
    by_year = defaultdict(list)
    for i in train:
        by_year[i["period"].year].append(i)
    aucs = []
    for year in sorted(by_year):
        value = _auc(*_pos_neg(features, by_year[year], name))
        if not np.isnan(value):
            aucs.append(value)
    return aucs


def _rho(features: dict, train: list[dict], a: dict, b: dict) -> float:
    """Spearman correlation of two features on training rows where both exist."""
    from scipy.stats import spearmanr
    xs, ys = [], []
    for i in train:
        x = _value(features, i, (a["indicator"], a["variant"]))
        y = _value(features, i, (b["indicator"], b["variant"]))
        if x is not None and y is not None:
            xs.append(x)
            ys.append(y)
    return float(spearmanr(xs, ys)[0]) if len(xs) >= 30 else 0.0


# ---------- cards ----------

def _card(features: dict, train: list[dict], test: list[dict], ind: str, variant: str):
    """All evidence for one feature; None when training has too few values."""
    from scipy.stats import ks_2samp
    name = (ind, variant)
    pos_tr, neg_tr = _pos_neg(features, train, name)
    pos_te, neg_te = _pos_neg(features, test, name)
    if len(pos_tr) < 5 or len(neg_tr) < 5:
        return None
    auc_train = _auc(pos_tr, neg_tr)
    auc_test = _auc(pos_te, neg_te)
    low, high = _bootstrap_ci(features, train, name)
    yearly = _yearly_aucs(features, train, name)
    flip = auc_train < 0.5
    if flip:
        auc_train, auc_test = 1 - auc_train, 1 - auc_test
        low, high = 1 - high, 1 - low
        yearly = [1 - a for a in yearly]
    early = _present(features, [i for i in train if i["period"] <= EARLY_END], name)
    late = _present(features, [i for i in train if i["period"] > EARLY_END], name)
    all_train = np.concatenate([pos_tr, neg_tr])
    all_test = np.concatenate([pos_te, neg_te])
    nan = float("nan")
    ks_in = ks_2samp(early, late).statistic if early and late else nan
    ks_out = ks_2samp(all_train, all_test).statistic if len(all_test) else nan
    return {
        "feature": f"{ind}:{variant}",
        "indicator": ind,
        "variant": variant,
        "category": CATEGORY.get(ind, "-"),
        "direction": "lower = risk" if flip else "higher = risk",
        "coverage_train": len(all_train) / len(train),
        "coverage_test": len(all_test) / len(test) if test else nan,
        "ks_within_train": float(ks_in),
        "ks_train_test": float(ks_out),
        "auc_train": auc_train,
        "ci_low": low,
        "ci_high": high,
        "sign_stability": float(np.mean([a > 0.5 for a in yearly])) if yearly else nan,
        "years": len(yearly),
        "auc_test": auc_test,
        "events_train": len(pos_tr),
        "events_test": len(pos_te),
    }


def _apply_rule(cards: list[dict], features: dict, train: list[dict]) -> None:
    """Decision per card: keep, or drop with the reasons."""
    for c in cards:
        reasons = []
        if not c["coverage_train"] >= RULE["min_coverage"]:
            reasons.append("coverage")
        if not c["ci_low"] > RULE["min_auc_ci_low"]:
            reasons.append("no signal")
        if not c["sign_stability"] >= RULE["min_sign_stability"]:
            reasons.append("unstable direction")
        if np.isnan(c["ks_within_train"]):
            reasons.append("drift not measurable")
        elif c["ks_within_train"] >= RULE["max_ks_within_train"]:
            reasons.append("drifts")
        c["decision"] = "drop: " + ", ".join(reasons) if reasons else "keep"
    candidates = [c for c in cards if c["decision"] == "keep"]
    candidates.sort(key=lambda c: -c["auc_train"])
    chosen = []
    for c in candidates:
        twin = None
        for k in chosen:
            if abs(_rho(features, train, c, k)) >= RULE["redundant_rho"]:
                twin = k
                break
        if twin:
            c["decision"] = f"drop: redundant with {twin['feature']}"
        else:
            chosen.append(c)


def feature_cards(features: dict, items: list[dict],
                  indicators: tuple[str, ...] = DEFAULT_INDICATORS) -> list[dict]:
    """One card per (indicator, variant), with the decision of the rule."""
    train, test = _labelled(items)
    cards = []
    for ind in indicators:
        for variant in VARIANTS:
            card = _card(features, train, test, ind, variant)
            if card is not None:
                cards.append(card)
    _apply_rule(cards, features, train)
    return cards


# ---------- output: cards ----------

def print_cards(cards: list[dict]) -> None:
    """The cards as a table, then the kept features."""
    rule = ", ".join(f"{k}={v}" for k, v in RULE.items())
    print(f"\nSelection rule (training periods only): {rule}")
    print("Test columns are reported only; they are not used to decide.\n")
    print(f"{'feature':30s} {'category':13s} {'cov tr':>6s} {'cov te':>6s} "
          f"{'KS in tr':>8s} {'KS tr-te':>8s}  {'AUC tr [95% CI]':17s} "
          f"{'stab':>5s} {'AUC te':>6s}  decision")
    previous = None
    for c in cards:
        if previous and previous != c["indicator"]:
            print()
        previous = c["indicator"]
        print(f"{c['feature']:30s} {c['category']:13s} "
              f"{c['coverage_train']:6.0%} {c['coverage_test']:6.0%} "
              f"{c['ks_within_train']:8.2f} {c['ks_train_test']:8.2f}  "
              f"{c['auc_train']:.2f} [{c['ci_low']:.2f}, {c['ci_high']:.2f}] "
              f"{c['sign_stability']:5.0%} {c['auc_test']:6.2f}  {c['decision']}")
    kept = [c["feature"] for c in cards if c["decision"] == "keep"]
    print(f"\nkept {len(kept)} of {len(cards)}: {', '.join(kept) or 'none'}")


def write_cards_csv(cards: list[dict], path: str) -> None:
    """All cards as CSV (thesis appendix)."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(cards[0]))
        writer.writeheader()
        writer.writerows(cards)


def cards_figure(cards: list[dict]):
    """Forest plot: training AUC with 95% CI (green = kept), test AUC as an open circle."""
    order = sorted(cards, key=lambda c: (c["category"], -c["auc_train"]))
    fig, ax = plt.subplots(figsize=(10, 0.26 * len(order) + 1.8))
    for k, c in enumerate(order):
        colour = "tab:green" if c["decision"] == "keep" else "grey"
        ax.plot([c["ci_low"], c["ci_high"]], [k, k], color=colour, linewidth=2)
        ax.plot(c["auc_train"], k, "o", color=colour, markersize=5)
        ax.plot(c["auc_test"], k, "o", markerfacecolor="none",
                markeredgecolor="tab:orange", markersize=5)
    ax.axvline(0.5, color="black", linewidth=0.8)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([f"{c['feature']}  ({c['category']})" for c in order], fontsize=7)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3)
    handles = [
        Line2D([], [], color="tab:green", marker="o", label="kept: training AUC, 95% CI"),
        Line2D([], [], color="grey", marker="o", label="dropped: training AUC, 95% CI"),
        Line2D([], [], color="tab:orange", marker="o", markerfacecolor="none",
               linestyle="", label="test AUC (reported only)"),
    ]
    ax.legend(handles=handles, fontsize=7, frameon=False, loc="lower right")
    ax.set(xlabel="AUC (direction fixed on training; 0.5 = no separation)",
           title="Feature cards: evidence on training periods, decision by a fixed rule")
    fig.tight_layout()
    return fig, len(order)


# ---------- correlation between features ----------

def _shortlist(cards: list[dict]) -> list[str]:
    """Kept features, then the best variant (highest training AUC) of every other indicator."""
    best = {}
    for c in cards:
        current = best.get(c["indicator"])
        if current is None or c["auc_train"] > current["auc_train"]:
            best[c["indicator"]] = c
    names = [c["feature"] for c in cards if c["decision"] == "keep"]
    names += [c["feature"] for c in best.values() if c["feature"] not in names]
    return names


def feature_correlation(features: dict, items: list[dict], names: list[str]) -> np.ndarray:
    """Spearman correlation between features on training rows where both exist."""
    from scipy.stats import spearmanr
    train, _ = _labelled(items)
    n = len(names)
    matrix = np.eye(n)
    for a in range(n):
        for b in range(a + 1, n):
            xs, ys = [], []
            for i in train:
                x = _value(features, i, _key(names[a]))
                y = _value(features, i, _key(names[b]))
                if x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
            rho = spearmanr(xs, ys)[0] if len(xs) >= 30 else np.nan
            matrix[a, b] = matrix[b, a] = rho
    return matrix


def kept_vif(features: dict, items: list[dict], cards: list[dict]):
    """VIF of the kept features (on ranks), on training rows where all of them exist."""
    from scipy.stats import rankdata
    train, _ = _labelled(items)
    names = [c["feature"] for c in cards if c["decision"] == "keep"]
    rows = []
    for i in train:
        values = [_value(features, i, _key(name)) for name in names]
        if all(v is not None for v in values):
            rows.append(values)
    if len(names) < 2 or len(rows) < 30:
        return names, len(rows), [float("nan")] * len(names)
    data = np.array(rows, dtype=float)
    ranks = np.column_stack([rankdata(data[:, k]) for k in range(len(names))])
    vif = np.diag(np.linalg.inv(np.corrcoef(ranks, rowvar=False)))
    return names, len(rows), [float(v) for v in vif]


def print_feature_correlation(features: dict, items: list[dict], cards: list[dict],
                              covers: float = 0.5) -> None:
    """Correlation matrix of the shortlist, VIF of the kept features, and what each one covers."""
    train, _ = _labelled(items)
    names = _shortlist(cards)
    matrix = feature_correlation(features, items, names)
    kept = [c for c in cards if c["decision"] == "keep"]
    kept_names = {c["feature"] for c in kept}
    labels = [("* " if n in kept_names else "  ") + n for n in names]
    width = max(len(label) for label in labels) + 1
    print("\nSpearman correlation between features (training rows; * = kept; "
          "others = best variant of each indicator)")
    print(" " * width + "".join(f"{k + 1:>6d}" for k in range(len(names))))
    for k, (label, line) in enumerate(zip(labels, matrix)):
        cells = "".join(f"{v:6.2f}" for v in line)
        print(f"{label:{width}s}{cells}  ({k + 1})")
    vif_names, n_rows, vif = kept_vif(features, items, cards)
    print(f"\nVIF of the kept features ({n_rows} training rows with all of them; "
          f"< 5 fine, > 10 a problem)")
    for name, value in zip(vif_names, vif):
        print(f"  {name:30s} {value:5.2f}")
    print(f"\nwhat each kept feature also stands for (other features with |rho| >= {covers}):")
    for c in kept:
        twins = []
        for d in cards:
            if d is c:
                continue
            rho = _rho(features, train, c, d)
            if abs(rho) >= covers:
                twins.append((abs(rho), rho, d["feature"]))
        twins.sort(reverse=True)
        text = ", ".join(f"{name} {rho:+.2f}" for _, rho, name in twins) or "nothing"
        print(f"  {c['feature']:30s} {text}")


def feature_correlation_figure(features: dict, items: list[dict], cards: list[dict]):
    """Heat map of the shortlist correlations; kept features marked with *."""
    names = _shortlist(cards)
    matrix = feature_correlation(features, items, names)
    kept = {c["feature"] for c in cards if c["decision"] == "keep"}
    labels = [("* " if n in kept else "") + n for n in names]
    size = 0.55 * len(names) + 3
    fig, ax = plt.subplots(figsize=(size + 1.5, size))
    image = ax.imshow(matrix, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=7)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(labels, fontsize=7)
    for y in range(len(names)):
        for x in range(len(names)):
            value = matrix[y, x]
            if not np.isnan(value):
                colour = "white" if abs(value) > 0.6 else "black"
                ax.text(x, y, f"{value:.2f}", ha="center", va="center", fontsize=6,
                        color=colour)
    fig.colorbar(image, ax=ax, fraction=0.04, label="Spearman rho (training rows)")
    ax.set_title("Correlation between features (* = kept by the rule)", fontsize=10)
    fig.tight_layout()
    return fig, len(names)