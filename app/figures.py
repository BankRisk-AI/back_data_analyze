"""Reproducible PNG figures for the rule-engine and panel results."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from app.core.database import connect

PROFILE_LABELS = {
    "1296bd8e": "v0",
    "794ea5ad": "v0.9",
    "5a1ec1f4": "v1.0",
    "28a28fa0": "v1.1",
}
COLORS = {"green": "#4daf4a", "amber": "#ffbf00", "red": "#e41a1c", "not_evaluated": "#bdbdbd"}
LABELS = {
    "en": {"red": "Red", "amber": "Amber", "green": "Green", "not_evaluated": "Not evaluated",
           "period": "Period", "share": "Share of banks (%)", "banks": "Banks", "frequency": "Frequency"},
    "ro": {"red": "Roșu", "amber": "Chihlimbar", "green": "Verde", "not_evaluated": "Neevaluat",
           "period": "Perioadă", "share": "Ponderea băncilor (%)", "banks": "Bănci", "frequency": "Frecvență"},
}


def _matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams["svg.hashsalt"] = "eba-analyst"
    return plt


def _date(period: str) -> datetime:
    return datetime.strptime(period, "%Y%m")


def _period_marker(ax, period: str, text: str):
    x = _date(period)
    ax.axvline(x, color="#555555", linestyle="--", linewidth=0.8)
    ax.text(x, 0.96, text, transform=ax.get_xaxis_transform(), rotation=90,
            va="top", ha="right", fontsize=8)


def _profiles(cur):
    cur.execute("""SELECT profile_sha256, min(created_at)
                   FROM alert GROUP BY profile_sha256 ORDER BY min(created_at)""")
    return [(sha, PROFILE_LABELS.get(sha[:8], sha[:12])) for sha, _ in cur.fetchall()]


def _alerts(cur, sha: str | None = None):
    clause = "WHERE a.profile_sha256=%s" if sha else ""
    params = (sha,) if sha else ()
    cur.execute(f"""SELECT a.profile_sha256,to_char(v.period_end,'YYYYMM'),a.level,b.name,a.rule_results
                    FROM alert a JOIN dataset_version v USING(version_id) JOIN bank b USING(bank_id)
                    {clause} ORDER BY v.period_end,b.name""", params)
    return cur.fetchall()


def _save(fig, out: Path, name: str, rows=None, caption: str = ""):
    out.mkdir(parents=True, exist_ok=True)
    metadata = {"Date": None}
    fig.savefig(out / f"{name}.png", dpi=300, bbox_inches="tight", metadata=metadata)
    fig.savefig(out / f"{name}.svg", bbox_inches="tight", metadata=metadata)
    with (out / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in rows or []:
            writer.writerow(row)
    (out / f"{name}.txt").write_text(caption + "\n", encoding="utf-8")
    import matplotlib.pyplot as plt
    plt.close(fig)


def _f1(cur, out, labels):
    plt = _matplotlib()
    grouped = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for sha, period, level, _name, _payload in _alerts(cur):
        version = PROFILE_LABELS.get(sha[:8])
        if not version or level == "not_evaluated":
            continue
        grouped[version][period][1] += 1
        if level == "red":
            grouped[version][period][0] += 1
    fig, ax = plt.subplots(figsize=(12, 5))
    csv_rows = [["profile", "period", "red_share_percent"]]
    for version in ("v0", "v0.9", "v1.0", "v1.1"):
        periods = sorted(grouped[version])
        shares = [100 * grouped[version][p][0] / grouped[version][p][1] for p in periods]
        ax.plot([_date(p) for p in periods], shares, label=version)
        csv_rows.extend([[version, p, f"{s:.8f}"] for p, s in zip(periods, shares)])
    ax.set(title="Share of banks in red alert by profile", xlabel=labels["period"], ylabel=labels["share"])
    ax.legend(); ax.tick_params(axis="x", rotation=60)
    _period_marker(ax, "201809", "quarterly data from here")
    _period_marker(ax, "202006", "NPL definition change")
    _save(fig, out, "F1", csv_rows, "Share of evaluated non-specialist banks in red alert by profile version.")


def _f2(cur, out, labels):
    plt = _matplotlib()
    rows = _alerts(cur, next((s for s, v in _profiles(cur) if v == "v1.1"), None))
    grouped = defaultdict(lambda: defaultdict(int))
    for _sha, period, level, _name, payload in rows:
        if isinstance(payload, dict) and payload.get("level_reason") == "specialist_excluded":
            continue
        grouped[period][level] += 1
    periods = sorted(grouped)
    fig, ax = plt.subplots(figsize=(12, 5))
    x = range(len(periods))
    totals = [sum(grouped[p][level] for level in ("green", "amber", "red", "not_evaluated")) for p in periods]
    shares = [[100 * grouped[p][level] / total if total else 0 for p, total in zip(periods, totals)]
              for level in ("green", "amber", "red", "not_evaluated")]
    ax.stackplot(x, *shares, colors=[COLORS[level] for level in ("green", "amber", "red", "not_evaluated")],
                 labels=[labels[level] for level in ("green", "amber", "red", "not_evaluated")])
    ax.set_xticks(list(x), periods)
    ax.set(title="Alert levels over time", xlabel=labels["period"], ylabel="Share (%)")
    ax.legend(); ax.tick_params(axis="x", rotation=60)
    _save(fig, out, "F2", [["period", "green", "amber", "red", "not_evaluated"]] +
          [[p] + [f"{shares[i][j]:.8f}" for i in range(4)] for j, p in enumerate(periods)],
          "Shares of evaluated non-specialist alert levels; specialists are excluded.")


def _f3(cur, out, labels, names):
    plt = _matplotlib()
    sha = next((s for s, v in _profiles(cur) if v == "v1.1"), None)
    rows = _alerts(cur, sha)
    selected = [r for r in rows if any(n.casefold() in (r[3] or "").casefold() for n in names)]
    periods = sorted({r[1] for r in selected})
    banks = [next((name for name in sorted({r[3] for r in selected}) if wanted.casefold() in name.casefold()), wanted)
             for wanted in names]
    banks = list(dict.fromkeys(bank for bank in banks if bank in {r[3] for r in selected}))
    levels = {"green": 0, "amber": 1, "red": 2, "not_evaluated": -1}
    matrix = []
    for bank in banks:
        values = []
        for period in periods:
            matches = [levels[r[2]] for r in selected if r[3] == bank and r[1] == period]
            values.append(matches[0] if matches else -2)
        matrix.append(values)
    fig, ax = plt.subplots(figsize=(14, max(4, len(banks) * .35)))
    colors = {-2: "white", -1: "#bdbdbd", 0: "#4daf4a", 1: "#ffbf00", 2: "#e41a1c"}
    hatches = {-2: "", -1: "xx", 0: "", 1: "//", 2: ".."}
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            ax.add_patch(plt.Rectangle((x, y), 1, 1, facecolor=colors[value],
                                       edgecolor="black", linewidth=.3, hatch=hatches[value]))
    ax.set(xlim=(0, len(periods)), ylim=(0, len(banks)), yticks=[i + .5 for i in range(len(banks))],
           yticklabels=banks, xticks=[i + .5 for i in range(len(periods))], xticklabels=periods,
           title="Bank-period alert levels", xlabel=labels["period"])
    ax.invert_yaxis(); ax.tick_params(axis="x", rotation=60)
    _save(fig, out, "F3", [["bank", *periods]] + [[bank, *row] for bank, row in zip(banks, matrix)],
          "Bank-period alert levels; white is not in sample and grey is not evaluated.")


def _f4(cur, out):
    plt = _matplotlib()
    cur.execute("""SELECT to_char(v.period_end,'YYYY'),p.cet1_ratio,p.npl_ratio,p.roe_annualised,p.leverage_ratio
                   FROM panel_row p JOIN dataset_version v USING(version_id) WHERE v.is_active""")
    values = defaultdict(lambda: defaultdict(list))
    for year, *features in cur.fetchall():
        for key, value in zip(("CET1 ratio", "NPL ratio", "RoCET1", "Leverage ratio"), features):
            if value is not None: values[key][year].append(value)
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    for index, (ax, key) in enumerate(zip(axes.flat, values)):
        years = sorted(values[key])
        x = [int(year) for year in years]
        med, lo, hi = [], [], []
        for year in years:
            data = sorted(values[key][year]); n = len(data)
            med.append(data[n // 2] * 100); lo.append(data[n // 4] * 100); hi.append(data[(3 * n) // 4] * 100)
        ax.plot(x, med); ax.fill_between(x, lo, hi, alpha=.2)
        ax.set_title(key); ax.set_ylabel("%"); ax.tick_params(axis="x", rotation=60)
        if key == "NPL ratio":
            ax.axvline(2020, color="#555555", linestyle="--", linewidth=0.8)
            ax.text(2020, .9, "NPL definition change", transform=ax.get_xaxis_transform(),
                    rotation=90, va="top", ha="right", fontsize=8)
    fig.suptitle("Annual indicator medians with IQR")
    _save(fig, out, "F4", [["indicator", "year", "median_percent", "q1_percent", "q3_percent"]],
          "Annual medians and interquartile ranges for the four panel indicators.")


def _f5(cur, out, labels):
    plt = _matplotlib()
    cur.execute("""SELECT to_char(v.period_end,'YYYYMM'),count(DISTINCT p.bank_id),
                          CASE WHEN v.period_end < DATE '2018-09-01' THEN 'semi-annual' ELSE 'quarterly' END,
                          max(i.edition_label)
                   FROM panel_row p JOIN dataset_version v USING(version_id)
                   JOIN import_batch i USING(import_id) GROUP BY v.period_end ORDER BY v.period_end""")
    rows = cur.fetchall(); periods = [r[0] for r in rows]
    fig, ax = plt.subplots(figsize=(12, 5))
    colors = {"semi-annual": "#377eb8", "quarterly": "#984ea3"}
    ax.bar([_date(p) for p in periods], [r[1] for r in rows],
           color=[colors[r[2]] for r in rows], edgecolor="black", linewidth=.3)
    ax.set(title="Data coverage", xlabel=labels["period"], ylabel=labels["banks"])
    ax.text(.01, 1.02, "Blue: semi-annual   Purple: quarterly", transform=ax.transAxes, fontsize=8)
    for x, row in enumerate(rows):
        ax.annotate(row[3] or "", (_date(row[0]), row[1]), fontsize=6, rotation=90, ha="center", va="bottom")
    _save(fig, out, "F5", [["period", "banks", "frequency", "edition"]] + [list(row) for row in rows],
          "Banks per period; bar colour indicates frequency and labels identify the EBA edition.")


def _f6(cur, out, labels, crisis, stable):
    plt = _matplotlib()
    sha = next((s for s, v in _profiles(cur) if v == "v1.1"), None)
    rows = [r for r in _alerts(cur, sha) if r[3] and (crisis.casefold() in r[3].casefold() or stable.casefold() in r[3].casefold())]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    score_colors = ["#f0f0f0", "#a6d854", "#ffd92f", "#e41a1c"]
    score_map = {"green": 0, "amber": 1, "red": 3, "not_evaluated": -1}
    csv_rows = [["bank", "period", "capital", "asset_quality", "profitability", "dynamics", "final"]]
    for ax, bank in zip(axes, (crisis, stable)):
        grouped = defaultdict(lambda: defaultdict(int))
        final = {}
        for _sha, period, level, name, payload in rows:
            if bank.casefold() not in name.casefold(): continue
            for family, data in (payload or {}).get("family_scores", {}).items():
                grouped[period][family] = data.get("score", 0)
            final[period] = score_map[level]
        periods = sorted(grouped)
        families = ("capital", "asset_quality", "profitability", "dynamics", "final")
        matrix = [[grouped[p].get(family, 0) if family != "final" else final.get(p, -1) for p in periods]
                  for family in families]
        ax.imshow(matrix, aspect="auto", interpolation="nearest", cmap=plt.matplotlib.colors.ListedColormap(score_colors),
                  vmin=-1, vmax=3)
        ax.set(yticks=range(5), yticklabels=families, xticks=range(len(periods)), xticklabels=periods,
               title=bank)
        ax.tick_params(axis="x", rotation=60)
        csv_rows.extend([[bank, p] + [grouped[p].get(f, 0) for f in ("capital", "asset_quality", "profitability", "dynamics")]
                         + [final.get(p, -1)] for p in periods])
    fig.suptitle("Family scores over time")
    _save(fig, out, "F6", csv_rows,
          "Family score strips and final alert level for the crisis and stable banks.")


def _f7(cur, out):
    plt = _matplotlib()
    from app.event_evaluation import evaluate_baselines, evaluate_events
    baselines = evaluate_baselines(cur.connection, "config/rules/eu_eba.yaml", "config/events.yaml")
    points = [(name, data) for name, data in baselines["baselines"].items()]
    points = [(name, data) for name, data in points
              if name != "B7 random baseline"]
    points += [("v1.1 red", baselines["baselines"]["v1.1 red"]),
               ("v1.1 amber+", baselines["baselines"]["v1.1 amber_or_red"])]
    fig, ax = plt.subplots(figsize=(8, 6))
    rows = [["method", "false_alarm_rate_percent", "hit_rate_percent"]]
    for name, data in points:
        x = data.get("false_alarm_rate_percent", 100 * data.get("false_alarm_rate", 0))
        y = data.get("hit_rate_percent", 100 * data.get("hit_rate", 0))
        ax.scatter([x], [y], label=name)
        rows.append([name, f"{x:.8f}", f"{y:.8f}"])
    ax.set(title="Hit rate versus false-alarm rate", xlabel="False-alarm rate (%)", ylabel="Hit rate (%)")
    ax.legend(fontsize=7)
    _save(fig, out, "F7", rows, "Event hit rate versus false-alarm rate for frozen v1.1 and fixed baselines.")


def _ml_result():
    path = Path("data/ml/results_T5_semiannual_robust.json")
    if not path.is_file():
        raise ValueError("train T5 on the semiannual grid before generating F8-F10")
    return json.loads(path.read_text())


def _f8(cur, out):
    plt = _matplotlib()
    result = _ml_result()
    fig, ax = plt.subplots(figsize=(8, 6))
    rows = [["model", "fold", "pr_auc"]]
    for metric in result.get("fold_metrics", []):
        if metric["model"] not in {"LR", "RF", "XGB"}:
            continue
        rows.append([metric["model"], str(metric["fold"]), f"{metric['pr_auc']:.8f}"])
    for name in ("LR", "RF", "XGB"):
        values = [m["pr_auc"] for m in result.get("fold_metrics", []) if m["model"] == name]
        if values:
            ax.plot(range(1, len(values) + 1), values, marker="o", label=name)
    ax.set(title="Out-of-fold precision-recall performance", xlabel="Fold", ylabel="PR-AUC")
    ax.legend()
    _save(fig, out, "F8", rows, "Pooled out-of-fold precision-recall comparison.")


def _f9(cur, out):
    plt = _matplotlib()
    result = _ml_result()
    importance = result.get("shap_importance", {})
    ordered = sorted(importance.items(), key=lambda item: item[1], reverse=True)[:15]
    fig, ax = plt.subplots(figsize=(8, 6))
    labels = [x[0] for x in reversed(ordered)]
    values = [x[1] for x in reversed(ordered)]
    ax.barh(labels, values, color="#377eb8")
    ax.set(title="Global feature importance (TreeSHAP)", xlabel="Mean absolute SHAP value")
    _save(fig, out, "F9", [["feature", "mean_abs_shap"]] +
          [[name, f"{value:.8f}"] for name, value in ordered],
          "Global TreeSHAP importance for the selected model.")


def _f10(cur, out):
    plt = _matplotlib()
    result = _ml_result()
    points = result.get("event_metrics", {})
    fig, ax = plt.subplots(figsize=(8, 6))
    rows = [["method", "false_alarm_rate_percent", "hit_rate_percent"]]
    for name, value in points.items():
        x, y = value["false_alarm_rate"] * 100, value["hit_rate"] * 100
        ax.scatter([x], [y], label=name)
        rows.append([name, f"{x:.8f}", f"{y:.8f}"])
    ax.set(title="Model and rule event performance", xlabel="False-alarm rate (%)", ylabel="Hit rate (%)")
    ax.legend(fontsize=8)
    _save(fig, out, "F10", rows, "Event hit rate versus false-alarm rate for models and rules.")


def _f11(cur, out):
    plt = _matplotlib()
    importance = _ml_result().get("shap_importance", {})
    groups = {"capital": ("cet1", "tier1", "total_capital", "leverage"),
              "asset quality": ("npl", "stage2"),
              "profitability": ("roe",),
              "concentration": ("nace_hhi", "sovereign_hhi"),
              "growth": ("loan_growth",),
              "liquidity": ()}
    values = {}
    for group, needles in groups.items():
        selected = [value for name, value in importance.items()
                    if any(needle in name for needle in needles)]
        values[group] = sum(selected) / len(selected) if selected else 0.0
    ordered = list(values)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(ordered, [values[group] for group in ordered], color="#377eb8")
    ax.set(title="Mean absolute SHAP by feature family", ylabel="Mean absolute SHAP")
    ax.tick_params(axis="x", rotation=35)
    _save(fig, out, "F11", [["family", "mean_abs_shap"]] +
          [[group, f"{values[group]:.8f}"] for group in ordered],
          "Headline robustness model mean absolute SHAP grouped by family.")


def _f12(cur, out):
    plt = _matplotlib()
    result = _ml_result()
    values = result.get("lead_time", {})
    if not values:
        values = {name: {"rules": 0, "ml": 0} for name in
                  ("Novo Banco", "Cyprus Cooperative Bank", "Carige", "NordLB")}
    names = list(values)
    rules = [values[name].get("rules", 0) for name in names]
    model = [values[name].get("ml", 0) for name in names]
    fig, ax = plt.subplots(figsize=(9, 5))
    width = .38
    positions = range(len(names))
    ax.bar([p - width / 2 for p in positions], rules, width, label="v1.1 red")
    ax.bar([p + width / 2 for p in positions], model, width, label="ML")
    ax.set(title="Lead time before events", ylabel="Quarters", xticks=list(positions),
           xticklabels=names)
    ax.legend()
    _save(fig, out, "F12", [["event", "rules_quarters", "ml_quarters"]] +
          [[name, str(values[name].get("rules", 0)), str(values[name].get("ml", 0))]
           for name in names], "Lead time comparison for rules and headline ML model.")


def generate(target: str, out_dir: str, lang: str = "en", only: list[str] | None = None) -> int:
    if lang not in LABELS:
        raise ValueError("lang must be en or ro")
    config = yaml.safe_load(Path("config/figures.yaml").read_text()) or {}
    selected = set(only or ("F1", "F2", "F3", "F4", "F5", "F6", "F7"))
    unknown = selected - {"F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"}
    if unknown:
        raise ValueError(f"unknown figures: {', '.join(sorted(unknown))}")
    conn = connect("public")
    try:
        with conn, conn.cursor() as cur:
            out = Path(out_dir)
            labels = LABELS[lang]
            if "F1" in selected: _f1(cur, out, labels)
            if "F2" in selected: _f2(cur, out, labels)
            if "F3" in selected: _f3(cur, out, labels, config.get("banks", []))
            if "F4" in selected: _f4(cur, out)
            if "F5" in selected: _f5(cur, out, labels)
            if "F6" in selected: _f6(cur, out, labels, config.get("crisis_bank", "Piraeus"), config.get("stable_bank", "BNP Paribas"))
            if "F7" in selected: _f7(cur, out)
            if "F8" in selected: _f8(cur, out)
            if "F9" in selected: _f9(cur, out)
            if "F10" in selected: _f10(cur, out)
            if "F11" in selected: _f11(cur, out)
            if "F12" in selected: _f12(cur, out)
    finally:
        conn.close()
    out = Path(out_dir)
    manifest = {}
    for path in sorted(out.glob("F[1-9].*")) + sorted(out.glob("F10.*")) + sorted(out.glob("F1[12].*")):
        manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(selected)
