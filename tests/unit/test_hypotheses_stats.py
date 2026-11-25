"""scripts/hypotheses/stats.py: bank-cluster bootstrap, Wilcoxon, Holm."""
import numpy as np
from sklearn.metrics import average_precision_score

from scripts.hypotheses.stats import (
    bootstrap_metric_difference, bootstrap_recall_difference, holm_adjust, wilcoxon_one_sided)


def test_bootstrap_estimate_matches_direct():
    rng = np.random.default_rng(99)
    y = rng.integers(0, 2, 40)
    cand, ref = rng.random(40), rng.random(40)
    banks = np.array(["a"] * 20 + ["b"] * 20)
    result = bootstrap_metric_difference(y, cand, ref, banks, "pr", seed=0, replicates=100)
    expected = average_precision_score(y, cand) - average_precision_score(y, ref)
    assert abs(result["estimate"] - expected) < 1e-10
    assert result["ci95"][0] <= result["ci95"][1]


def test_bootstrap_recall_difference_returns_ordered_interval():
    rng = np.random.default_rng(42)
    y = rng.integers(0, 2, 50)
    a, b = rng.random(50) > .5, rng.random(50) > .5
    banks = rng.integers(0, 5, 50).astype(str)
    ci = bootstrap_recall_difference(y, a, b, banks, seed=1, replicates=100)
    assert len(ci) == 2 and ci[0] <= ci[1]


def test_wilcoxon_too_few_returns_exploratory():
    assert wilcoxon_one_sided([1.0, 2.0], 5)["status"] == "exploratory"


def test_wilcoxon_sufficient_data():
    result = wilcoxon_one_sided([1.0, 2.0, 3.0, 4.0, 5.0], 5)
    assert result["status"] == "exact" and 0 <= result["p"] <= 1


def test_holm_adjust_known_values():
    assert holm_adjust([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
