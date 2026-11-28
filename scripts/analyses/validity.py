"""Validity checks on the data and the label (read-only), ten points:

     1  banks leaving the sample (informative censoring)
     2  publication lag: what was known when
     3  known public distress cases: marked by the label, how early
     4  recurrence of events (a simple baseline)
     5  mergers and scope changes inside the event window
     6  learning curve: would more data help?
     7  country effects
     8  RWA density as a candidate feature
     9  implausible values
    10  label sensitivity and alternative definitions of E2
A summary with the key numbers is printed at the end.
Labels are the exploratory ones from scripts.analyses.events (E2 CET1, E3 NPL, E1 thresholds).
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import date

import matplotlib.pyplot as plt
import numpy as np

from scripts.analyses.dataset import TEST_END, TEST_START, TRAIN_END
from scripts.analyses.draw_graph import (
    DEFAULT_INDICATORS,
    NPL_BREAK,
    _month_end,
    winsorised_rows,
)
from scripts.analyses.events import E1_MINIMA, HORIZON, auc, episode_starts, period_medians
from scripts.analyses.feature_cards import (
    _auc,
    _bootstrap_ci,
    _key,
    _labelled,
    _pos_neg,
    _rho,
    _value,
    feature_cards,
    print_cards,
)
from scripts.analyses.features import build_features

# features kept by the rule on the original label; used to compare label variants (point 10)
KEPT = ("cet1_ratio:rz", "tier1_ratio:vol", "npl_ratio:chg", "roe_annualised:raw")
# features kept by the rule on the recommended label (weak_12m_e3weak_exits_noscope)
FINAL = ("total_capital_ratio:rz", "npl_ratio:rank", "npl_ratio:vol", "roe_annualised:raw",
         "roe_annualised:vol", "sovereign_hhi:raw", "loan_growth_yoy:raw")
CHECKED = ("cet1_ratio", "leverage_ratio", "npl_ratio", "roe_annualised")
FINDINGS: dict[str, str] = {}

# public distress events, matched on the bank name (dates approximate, to be checked)
KNOWN_CASES = (
    ("Monte dei Paschi", date(2017, 6, 30), "precautionary recapitalisation"),
    ("Banco Popular", date(2017, 6, 7), "resolution, sold to Santander"),
    ("Veneto Banca", date(2017, 6, 25), "liquidation"),
    ("Popolare di Vicenza", date(2017, 6, 25), "liquidation"),
    ("Carige", date(2019, 1, 2), "temporary administration"),
    ("Norddeutsche Landesbank", date(2019, 12, 31), "recapitalisation"),
    ("Caixa Geral", date(2017, 3, 31), "state recapitalisation"),
    ("Sberbank Europe", date(2022, 2, 28), "failing or likely to fail"),
    ("HSH", date(2018, 11, 28), "sale after state aid"),
    ("Banco Mare Nostrum", date(2017, 12, 29), "merger into state-owned Bankia"),
    ("Novo Banco", date(2017, 10, 18), "sale with contingent capital"),
    ("ABLV", date(2018, 2, 23), "failing or likely to fail"),
    ("Etruria", date(2015, 11, 22), "resolution"),
    ("Banca Marche", date(2015, 11, 22), "resolution"),
    ("Piraeus", date(2015, 12, 31), "recapitalisation"),
    ("National Bank of Greece", date(2015, 12, 31), "recapitalisation"),
    ("Alpha", date(2015, 12, 31), "recapitalisation"),
    ("Eurobank", date(2015, 12, 31), "recapitalisation"),
    ("Popolare di Bari", date(2019, 12, 31), "temporary administration"),
)

# alternative labels for point 10: (name, options for label_variant)
LABEL_VARIANTS = (
    ("baseline: abs 12m 5%", {}),
    ("horizon 6m", {"horizon": 6}),
    ("horizon 24m", {"horizon": 24}),
    ("tail 10%", {"tail": 0.10}),
    ("tail 2.5%", {"tail": 0.025}),
    ("relative CET1 fall", {"kind": "rel"}),
    ("fall into bottom quartile", {"kind": "weak"}),
    ("E2 only (no NPL rise)", {"e3": False}),
)


# ---------- helpers ----------

def bank_info() -> dict[int, dict]:
    """{bank_id: {name, country, finrep}} from the bank table (read-only)."""
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            url = os.environ.get("DATABASE_URL")
        except ImportError:
            pass
    if not url:
        raise RuntimeError("DATABASE_URL not set (run: set -a; . ./.env; set +a)")
    conn = psycopg2.connect(url)
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute("SELECT bank_id, name, country_code, finrep_reported FROM bank")
            return {b: {"name": (n or "").strip(), "country": (c or "").strip(), "finrep": f}
                    for b, n, c, f in cur.fetchall()}
    finally:
        conn.close()


def _bank_periods(rows: list[dict]) -> dict[int, list]:
    periods = defaultdict(list)
    for r in rows:
        periods[r["bank_id"]].append(r["period"])
    return {b: sorted(p) for b, p in periods.items()}


def _items_by_bank(items: list[dict]) -> dict[int, list]:
    by_bank = defaultdict(list)
    for i in items:
        by_bank[i["bank_id"]].append(i)
    return by_bank


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def _fmt(value) -> str:
    return "  -  " if value is None else f"{value:.3f}"


def _labelled_items(items: list[dict]) -> list[dict]:
    return [i for i in items if i["event"] is not None]


def _kept_aucs(features: dict, group: list[dict], names=KEPT) -> dict[str, float]:
    """Raw AUC per feature (> 0.5 = higher before events)."""
    return {n: _auc(*_pos_neg(features, group, _key(n))) for n in names}


def _group_ci(features, train, name, group_of, reps: int = 500, seed: int = 0):
    """95% CI of the AUC when whole groups (e.g. countries) are resampled."""
    groups = defaultdict(lambda: ([], []))
    for i in train:
        v = _value(features, i, name)
        if v is not None:
            groups[group_of(i)][0 if i["event"] else 1].append(v)
    arrays = [(np.array(p, dtype=float), np.array(n, dtype=float)) for p, n in groups.values()]
    rng = np.random.default_rng(seed)
    results = []
    for _ in range(reps):
        chosen = rng.integers(0, len(arrays), len(arrays))
        pos = np.concatenate([arrays[k][0] for k in chosen])
        neg = np.concatenate([arrays[k][1] for k in chosen])
        results.append(_auc(pos, neg))
    results = np.array(results)
    results = results[~np.isnan(results)]
    if len(results) == 0:
        return float("nan"), float("nan")
    low, high = np.percentile(results, [2.5, 97.5])
    return float(low), float(high)


# ---------- 1. banks leaving the sample ----------

def print_censoring(rows: list[dict], items: list[dict], info: dict):
    """Who leaves, how many labels are lost, and how leavers look at their last report."""
    last = max(r["period"] for r in rows)
    periods = _bank_periods(rows)
    exits = {b: p[-1] for b, p in periods.items() if p[-1] < last}
    row_at = {(r["bank_id"], r["period"]): r for r in rows}
    medians = period_medians(rows, CHECKED)
    by_bank = _items_by_bank(items)
    unknown = [i for i in items
               if i["event"] is None and _month_end(i["period"], HORIZON) <= last]
    censored = [i for i in unknown if i["bank_id"] in exits
                and _month_end(i["period"], HORIZON) > exits[i["bank_id"]]]
    print(f"banks: {len(periods)}; leaving before {last}: {len(exits)}")
    per_year = sorted(Counter(p.year for p in exits.values()).items())
    print("exits per year: " + ", ".join(f"{y}: {n}" for y, n in per_year))
    per_country = Counter(info.get(b, {}).get("country", "?") for b in exits).most_common(8)
    print("exits per country: " + ", ".join(f"{c}: {n}" for c, n in per_country))
    print(f"labels unknown although t+12m is inside the data: {len(unknown)}; "
          f"because the bank left the sample: {len(censored)}")
    recent = {b: any((i["event"] or i["e1"]) for i in by_bank.get(b, [])
                     if i["period"] >= _month_end(p, -24)) for b, p in exits.items()}
    n_recent = sum(recent.values())
    print(f"leavers with an event or E1 in the 24 months before leaving: {n_recent} of {len(exits)}")

    groups = {
        "left": [row_at[(b, p)] for b, p in exits.items()],
        "event start": [row_at[(i["bank_id"], i["period"])] for i in episode_starts(items)],
        "no event": [row_at[(i["bank_id"], i["period"])] for i in items if i["event"] is False],
    }

    def relative(group, ind):
        return [r[ind] - medians[(r["period"], ind)] for r in group
                if r[ind] is not None and (r["period"], ind) in medians]

    print("\nvalue minus the median bank of the same period (median per group); "
          "AUC = leavers vs no event")
    print("indicator              left   event start   no event    AUC")
    rel = {}
    for ind in CHECKED:
        rel[ind] = {name: relative(group, ind) for name, group in groups.items()}
        left, event, none = rel[ind]["left"], rel[ind]["event start"], rel[ind]["no event"]
        print(f"{ind:20s} {np.median(left):+7.4f} {np.median(event):+12.4f} "
              f"{np.median(none):+10.4f} {auc(left, none):6.2f}")

    def rel_cet1(b):
        r = row_at[(b, exits[b])]
        key = (r["period"], "cet1_ratio")
        return None if r["cet1_ratio"] is None or key not in medians else r["cet1_ratio"] - medians[key]

    ranked = sorted((b for b in exits if rel_cet1(b) is not None), key=rel_cet1)
    print("\nleavers with the weakest capital at their last report")
    for b in ranked[:10]:
        r = row_at[(b, exits[b])]
        d = info.get(b, {})
        print(f"  {b:5d} {d.get('country', ''):2s} last={exits[b]} CET1={_fmt(r['cet1_ratio'])} "
              f"NPL={_fmt(r['npl_ratio'])} ROE={_fmt(r['roe_annualised'])} "
              f"recent event={'yes' if recent[b] else 'no '} {d.get('name', '')[:45]}")
    FINDINGS["1 leaving the sample"] = (
        f"{len(exits)} of {len(periods)} banks leave; {len(censored)} of {len(unknown)} unknown "
        f"labels are lost by exit; {n_recent} leavers had an event or E1 in the 24m before")
    return _exits_figure(rel)


def _exits_figure(rel: dict):
    """Boxplots per indicator: leavers vs event starts vs no event (relative to period median)."""
    fig, axes = plt.subplots(1, len(rel), figsize=(4 * len(rel), 4.5))
    for ax, (ind, by_group) in zip(axes, rel.items()):
        names = [n for n in by_group if by_group[n]]
        ax.boxplot([by_group[n] for n in names], showfliers=False)
        ax.set_xticks(range(1, len(names) + 1))
        ax.set_xticklabels(names, rotation=20, fontsize=8)
        ax.axhline(0, color="grey", linewidth=0.8, linestyle=":")
        ax.set_title(ind, fontsize=9)
    fig.suptitle("Last report before leaving vs event starts vs no event "
                 "(value minus period median)")
    fig.tight_layout()
    return fig


# ---------- 2. publication lag ----------

def edition_year(period: date) -> int:
    """Year of the EBA transparency exercise that published this reference date."""
    if period <= date(2018, 6, 30):
        return period.year + 1 if period.month == 12 else period.year
    return period.year + 1 if period.month in (9, 12) else period.year


def published(period: date) -> date:
    """Approximate publication date (exercises appear late November / early December)."""
    return date(edition_year(period), 12, 1)


def print_publication_lag(rows: list[dict], items: list[dict], known: list[dict]) -> None:
    """Lag per edition, months of the event window left after publication, real lead of cases."""
    periods = sorted({r["period"] for r in rows})
    by_edition = defaultdict(list)
    for p in periods:
        by_edition[edition_year(p)].append(p)
    print("edition  published (approx.)  reference dates                      lag in months")
    for year, refs in sorted(by_edition.items()):
        lags = [_months_between(p, published(p)) for p in refs]
        dates = ", ".join(str(p)[:7] for p in refs)
        print(f"{year}     {published(refs[0])}           {dates:36s} {min(lags)}-{max(lags)}")
    starts = episode_starts(items)
    useful = [_months_between(published(i["period"]), _month_end(i["period"], HORIZON))
              for i in starts]
    none = sum(1 for u in useful if u <= 0)
    print(f"\nevent episodes: {len(starts)}; months of the 12-month event window still ahead "
          f"when the data were published: median {np.median(useful):.0f}, "
          f"none left for {none} ({none / max(len(starts), 1):.0%})")
    print("\nknown cases marked by the label: lead counted from the reference date vs from publication")
    leads = []
    for case in known:
        if case["verdict"] != "marked":
            continue
        from_reference = _months_between(case["first"], case["when"])
        from_publication = _months_between(published(case["first"]), case["when"])
        leads.append(from_publication)
        print(f"  {case['case']:24s} first signal {case['first']}  "
              f"lead {from_reference:3d} months, after publication {from_publication:3d}")
    FINDINGS["2 publication lag"] = (
        f"lag 5-17 months; median {np.median(useful):.0f} months of the event window left after "
        f"publication; {none / max(len(starts), 1):.0%} of episodes with none; real lead of marked "
        f"cases {min(leads) if leads else '-'}-{max(leads) if leads else '-'} months")


# ---------- 3. known distress cases ----------

def known_case_results(rows: list[dict], items: list[dict], info: dict) -> list[dict]:
    """Per known case and matching bank: in the panel? marked in the 24 months before? how early?"""
    periods = _bank_periods(rows)
    by_bank = _items_by_bank(items)
    results = []
    for pattern, when, what in KNOWN_CASES:
        banks = [b for b, d in info.items() if pattern.lower() in d["name"].lower()]
        in_panel = [b for b in banks if b in periods]
        if not in_panel:
            verdict = "name not found" if not banks else "not in panel"
            results.append({"case": pattern, "when": when, "what": what, "bank": None,
                            "span": None, "hits": 0, "e1": 0, "first": None, "verdict": verdict})
            continue
        for b in in_panel:
            span = periods[b]
            window = [i for i in by_bank.get(b, [])
                      if _month_end(when, -24) <= i["period"] <= when]
            hits = [i for i in window if i["event"]]
            e1 = [i for i in window if i["e1"]]
            first = min((i["period"] for i in hits + e1), default=None)
            if span[0] >= when:
                verdict = "no history before the event"
            elif hits or e1:
                verdict = "marked"
            elif span[-1] < when:
                verdict = "missed: left the sample"
            elif not window:
                verdict = "no reports in the 24 months before"
            else:
                verdict = "missed"
            results.append({"case": pattern, "when": when, "what": what, "bank": b,
                            "span": (span[0], span[-1]), "hits": len(hits), "e1": len(e1),
                            "first": first, "verdict": verdict})
    return results


def _case_counts(results: list[dict]) -> dict[str, int]:
    counts = Counter(r["verdict"] for r in results)
    with_history = counts["marked"] + counts["missed"] + counts["missed: left the sample"]
    return {"marked": counts["marked"], "with_history": with_history,
            "left": counts["missed: left the sample"], "missed": counts["missed"],
            "no_history": counts["no history before the event"]}


def print_known_cases(results: list[dict]) -> None:
    print("case                     date        bank  in panel                E2/E3  E1  "
          "lead(m)  verdict")
    for r in results:
        if r["bank"] is None:
            print(f"{r['case']:24s} {r['when']}     -  {r['verdict']}")
            continue
        lead = "-" if r["first"] is None else str(_months_between(r["first"], r["when"]))
        span = f"{r['span'][0]}..{r['span'][1]}"
        print(f"{r['case']:24s} {r['when']}  {r['bank']:4d}  {span}  {r['hits']:5d} {r['e1']:3d}  "
              f"{lead:>7s}  {r['verdict']} ({r['what']})")
    c = _case_counts(results)
    print(f"\ncases with history in the panel: {c['with_history']}; marked {c['marked']}, "
          f"missed because the bank left {c['left']}, missed otherwise {c['missed']}; "
          f"without history before the event {c['no_history']}")
    FINDINGS["3 known cases"] = (
        f"{c['marked']} of {c['with_history']} cases with history marked; {c['left']} lost by exit; "
        f"{c['missed']} missed otherwise; {c['no_history']} without history")


# ---------- 4. recurrence ----------

def recurrence_flags(items: list[dict]) -> dict[int, bool]:
    """Per item: did an event window of the same bank close in the 24 months before t?"""
    flags = {}
    for group in _items_by_bank(items).values():
        for i in group:
            start = _month_end(i["period"], -36)
            flags[id(i)] = any(
                j["event"] and start <= j["period"] and _month_end(j["period"], HORIZON) <= i["period"]
                for j in group)
    return flags


def print_recurrence(items: list[dict]) -> None:
    """Event rate with and without an earlier event, and the AUC of that simple rule."""
    flags = recurrence_flags(items)
    print("prior event = an event window of the same bank that closed in the 24 months before t")
    print("part    rows  with prior  P(event|prior)  P(event|none)  AUC of the rule")
    summary = {}
    for label, low, high in (("train", None, TRAIN_END), ("test", TEST_START, TEST_END)):
        group = [i for i in items if i["event"] is not None and i["period"] <= high
                 and (low is None or i["period"] >= low)]
        prior = [i for i in group if flags[id(i)]]
        none = [i for i in group if not flags[id(i)]]

        def rate(g):
            return sum(bool(i["event"]) for i in g) / len(g) if g else float("nan")

        pos = [1.0 if flags[id(i)] else 0.0 for i in group if i["event"]]
        neg = [1.0 if flags[id(i)] else 0.0 for i in group if not i["event"]]
        rule_auc = auc(pos, neg)
        summary[label] = (rate(prior), rate(none), rule_auc)
        print(f"{label:6s} {len(group):5d} {len(prior):11d} {rate(prior):15.1%} "
              f"{rate(none):14.1%} {rule_auc:16.2f}")
    starts = episode_starts(items)
    repeats = sum(1 for i in starts if flags[id(i)])
    print(f"episodes that follow an earlier one: {repeats} of {len(starts)}")
    p, n, a = summary["test"]
    FINDINGS["4 recurrence"] = (
        f"P(event | earlier event) {p:.0%} vs {n:.0%}; rule AUC on test {a:.2f}; "
        f"{repeats} of {len(starts)} episodes are repeats")


def print_event_banks(items: list[dict], info: dict, top: int = 15) -> None:
    """Banks with most episodes, with name, country and FINREP reporting."""
    counts = Counter(i["bank_id"] for i in episode_starts(items))
    print("\nbanks with most episodes")
    for bank, n in counts.most_common(top):
        d = info.get(bank, {})
        print(f"  {bank:5d}  {n:2d} episodes  {d.get('country', ''):2s}  "
              f"finrep={str(d.get('finrep')):5s}  {d.get('name', '')}")


# ---------- 5. mergers and scope changes ----------

def print_structural_changes(rows: list[dict], items: list[dict], info: dict,
                             features: dict, threshold: float = 0.3) -> None:
    """Event windows in which the loan book grows or shrinks by >= threshold (M&A, sales)."""
    row_at = {(r["bank_id"], r["period"]): r for r in rows}
    labelled = _labelled_items(items)
    flagged = {}
    for i in labelled:
        end = row_at.get((i["bank_id"], _month_end(i["period"], HORIZON)))
        growth = end["loan_growth_yoy"] if end else None
        flagged[id(i)] = growth is not None and abs(growth) >= threshold
    events = [i for i in labelled if i["event"]]
    others = [i for i in labelled if not i["event"]]
    share_events = sum(flagged[id(i)] for i in events) / max(len(events), 1)
    share_others = sum(flagged[id(i)] for i in others) / max(len(others), 1)
    flagged_rows = [i for i in labelled if flagged[id(i)]]
    rate_flagged = sum(bool(i["event"]) for i in flagged_rows) / max(len(flagged_rows), 1)
    print(f"event window = t..t+12m; structural change = loan book change of at least "
          f"{threshold:.0%} over the same window")
    print(f"event windows with a structural change: {share_events:.1%}; "
          f"other windows: {share_others:.1%}; event rate when flagged: {rate_flagged:.1%}")
    counts = Counter(i["bank_id"] for i in events if flagged[id(i)])
    print("banks with most event windows that include a structural change:")
    for bank, n in counts.most_common(10):
        d = info.get(bank, {})
        print(f"  {bank:5d} {n:2d}  {d.get('country', ''):2s}  {d.get('name', '')[:60]}")
    crosswalk = {r["bank_id"] for r in rows
                 if any("group_crosswalk" in v for v in (r.get("flags") or {}).values()
                        if isinstance(v, list))}
    print(f"banks already joined through the approved crosswalk: {len(crosswalk)}")
    train, _ = _labelled(items)
    clean = [i for i in train if not flagged.get(id(i), False)]
    before = _kept_aucs(features, train, FINAL)
    after = _kept_aucs(features, clean, FINAL)
    print("\ntraining AUC of the selected features (> 0.5 = higher before events): "
          "all windows vs without structural changes")
    for name in FINAL:
        print(f"  {name:24s} {before[name]:.2f} -> {after[name]:.2f}")
    FINDINGS["5 mergers, scope"] = (
        f"{share_events:.0%} of event windows vs {share_others:.0%} of others include a loan-book "
        f"change >= {threshold:.0%}")


# ---------- 6. learning curve ----------

def _matrix(features: dict, group: list[dict], names) -> np.ndarray:
    values = []
    for i in group:
        line = []
        for n in names:
            v = _value(features, i, _key(n))
            line.append(np.nan if v is None else v)
        values.append(line)
    return np.array(values, dtype=float)


def print_learning_curve(features: dict, items: list[dict], repeats: int = 20,
                         fractions=(0.25, 0.5, 0.75, 1.0)):
    """Logistic regression on a share of the training banks, scored on the test period."""
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import average_precision_score, roc_auc_score
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        print("scikit-learn not available; skipped")
        return None
    sets = {
        "selected 7": list(FINAL),
        "selected 6 (no sovereign)": list(FINAL[:5]) + [FINAL[6]],
        "raw levels 11": [f"{i}:raw" for i in DEFAULT_INDICATORS],
    }
    train, test = _labelled(items)
    y_test = np.array([bool(i["event"]) for i in test])
    banks = sorted({i["bank_id"] for i in train})
    curve = {name: {} for name in sets}
    print(f"test: {len(test)} rows, {int(y_test.sum())} events (base rate {y_test.mean():.1%}); "
          f"descriptive use of the test period")
    print("features                    share of banks  banks  events  ROC-AUC (sd)   PR-AUC (sd)")
    for name, cols in sets.items():
        x_test = _matrix(features, test, cols)
        for fraction in fractions:
            scores = []
            for seed in range(repeats if fraction < 1 else 1):
                rng = np.random.default_rng(seed)
                size = max(2, int(round(fraction * len(banks))))
                chosen = set(rng.choice(banks, size=size, replace=False).tolist())
                subset = [i for i in train if i["bank_id"] in chosen]
                y = np.array([bool(i["event"]) for i in subset])
                if y.sum() < 5:
                    continue
                model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                      LogisticRegression(class_weight="balanced", max_iter=2000))
                model.fit(_matrix(features, subset, cols), y)
                p = model.predict_proba(x_test)[:, 1]
                scores.append((roc_auc_score(y_test, p), average_precision_score(y_test, p),
                               int(y.sum())))
            curve[name][fraction] = scores
            roc = [s[0] for s in scores]
            pr = [s[1] for s in scores]
            events = np.mean([s[2] for s in scores]) if scores else float("nan")
            print(f"{name:27s} {fraction:14.0%} {int(round(fraction * len(banks))):6d} "
                  f"{events:7.0f}  {np.mean(roc):.3f} ({np.std(roc):.3f})  "
                  f"{np.mean(pr):.3f} ({np.std(pr):.3f})")
    text = []
    for name in sets:
        low = np.mean([s[0] for s in curve[name][fractions[0]]])
        high = np.mean([s[0] for s in curve[name][fractions[-1]]])
        text.append(f"{name} {low:.2f} -> {high:.2f}")
    FINDINGS["6 learning curve"] = "ROC-AUC on test, 25% -> 100% of training banks: " + "; ".join(text)
    return _learning_figure(curve, float(y_test.mean()))


def _learning_figure(curve: dict, base_rate: float):
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2))
    for name, by_fraction in curve.items():
        fractions = sorted(by_fraction)
        for ax, k in ((left, 0), (right, 1)):
            means = [np.mean([s[k] for s in by_fraction[f]]) for f in fractions]
            sds = [np.std([s[k] for s in by_fraction[f]]) for f in fractions]
            ax.errorbar([100 * f for f in fractions], means, yerr=sds, marker="o",
                        capsize=3, label=name)
    left.axhline(0.5, color="grey", linestyle=":", linewidth=1)
    right.axhline(base_rate, color="grey", linestyle=":", linewidth=1, label="base rate")
    left.set(xlabel="share of training banks (%)", ylabel="ROC-AUC on test",
             title="Learning curve: ROC-AUC")
    right.set(xlabel="share of training banks (%)", ylabel="PR-AUC on test",
              title="Learning curve: PR-AUC")
    for ax in (left, right):
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    return fig


# ---------- 7. country ----------

def print_country(rows: list[dict], items: list[dict], info: dict, features: dict,
                  kept=FINAL):
    """Variance with a country component, events per country, country-cluster CI of features."""
    def country(bank):
        return info.get(bank, {}).get("country") or "?"

    clipped = winsorised_rows(rows)
    print("variance shares (values clipped to p1-p99)")
    print("indicator              country  bank in country  common in time  bank-specific change")
    shares = {}
    for ind in DEFAULT_INDICATORS:
        present = [r for r in clipped if r[ind] is not None]
        if len(present) < 30:
            continue
        values = np.array([r[ind] for r in present])
        grand = values.mean()
        total = ((values - grand) ** 2).sum()
        by_country, by_bank = defaultdict(list), defaultdict(list)
        for r in present:
            by_country[country(r["bank_id"])].append(r[ind])
            by_bank[r["bank_id"]].append(r[ind])
        mean_c = {c: np.mean(v) for c, v in by_country.items()}
        mean_b = {b: np.mean(v) for b, v in by_bank.items()}
        between_country = sum(len(v) * (mean_c[c] - grand) ** 2 for c, v in by_country.items())
        bank_in_country = sum(len(v) * (mean_b[b] - mean_c[country(b)]) ** 2
                              for b, v in by_bank.items())
        by_period = defaultdict(list)
        for r in present:
            by_period[r["period"]].append(r[ind] - mean_b[r["bank_id"]])
        common = sum(len(d) * np.mean(d) ** 2 for d in by_period.values())
        rest = max(total - between_country - bank_in_country - common, 0.0)
        shares[ind] = between_country / total
        print(f"{ind:22s} {between_country / total:7.0%} {bank_in_country / total:16.0%} "
              f"{common / total:15.0%} {rest / total:21.0%}")

    starts = episode_starts(items)
    labelled = _labelled_items(items)
    rows_c = Counter(country(i["bank_id"]) for i in labelled)
    episodes_c = Counter(country(i["bank_id"]) for i in starts)
    banks_c = Counter(country(b) for b in {r["bank_id"] for r in rows})
    print("\ncountry  banks  labelled rows  episodes  per 100 rows")
    for c, n in episodes_c.most_common(12):
        print(f"{c:7s} {banks_c[c]:6d} {rows_c[c]:14d} {n:9d} {100 * n / max(rows_c[c], 1):13.1f}")
    top3 = sum(n for _, n in episodes_c.most_common(3))
    print(f"episodes in the 3 countries with most episodes: {top3} of {len(starts)}")

    train, _ = _labelled(items)
    print("\nselected features: training AUC with CI resampling banks vs resampling countries")
    print("feature                   AUC   CI banks        CI countries")
    lows = []
    for name in kept:
        key = _key(name)
        value = _auc(*_pos_neg(features, train, key))
        bank_low, bank_high = _bootstrap_ci(features, train, key)
        country_low, country_high = _group_ci(features, train, key,
                                              lambda i: country(i["bank_id"]))
        if value < 0.5:
            value = 1 - value
            bank_low, bank_high = 1 - bank_high, 1 - bank_low
            country_low, country_high = 1 - country_high, 1 - country_low
        lows.append(country_low)
        print(f"{name:24s} {value:5.2f}  [{bank_low:.2f}, {bank_high:.2f}]    "
              f"[{country_low:.2f}, {country_high:.2f}]")
    FINDINGS["7 country"] = (
        f"country share of variance: NPL {shares.get('npl_ratio', float('nan')):.0%}, "
        f"leverage {shares.get('leverage_ratio', float('nan')):.0%}, "
        f"CET1 {shares.get('cet1_ratio', float('nan')):.0%}; top 3 countries hold {top3} of "
        f"{len(starts)} episodes; lower CI bounds with country resampling {min(lows):.2f}-{max(lows):.2f}")
    return _countries_figure(episodes_c, rows_c)


def _countries_figure(episodes_c: Counter, rows_c: Counter):
    """Episodes per 100 labelled rows by country (countries with at least 20 labelled rows)."""
    countries = [c for c in rows_c if rows_c[c] >= 20]
    countries.sort(key=lambda c: -episodes_c[c] / rows_c[c])
    rates = [100 * episodes_c[c] / rows_c[c] for c in countries]
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.bar(range(len(countries)), rates, color="tab:blue")
    for x, c in enumerate(countries):
        ax.text(x, rates[x], str(episodes_c[c]), ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(countries)))
    ax.set_xticklabels(countries, fontsize=8)
    ax.set(ylabel="episodes per 100 labelled rows",
           title="Events by country (number above the bar = episodes)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    return fig


# ---------- 8. RWA density ----------

def print_rwa_density(rows: list[dict], items: list[dict]) -> None:
    """Feature card for rwa_density = leverage ratio / CET1 ratio, and its link to cet1_ratio:rz."""
    extended = []
    for r in rows:
        lev, cet1 = r["leverage_ratio"], r["cet1_ratio"]
        extended.append({**r, "rwa_density": lev / cet1 if lev is not None and cet1 else None})
    features = build_features(extended, ("rwa_density", "cet1_ratio"))
    cards = feature_cards(features, items, ("rwa_density",))
    print("rwa_density = leverage ratio / CET1 ratio ~ RWA / leverage exposure (Tier 1 ~ CET1)")
    print_cards(cards)
    train, _ = _labelled(items)
    reference = {"indicator": "cet1_ratio", "variant": "rz"}
    print("\ncorrelation with cet1_ratio:rz")
    for c in cards:
        print(f"  {c['feature']:24s} rho = {_rho(features, train, c, reference):+.2f}")
    kept = [c["feature"] for c in cards if c["decision"] == "keep"]
    FINDINGS["8 RWA density"] = f"kept by the rule: {', '.join(kept) or 'none'}"


# ---------- 9. implausible values ----------

def _both(r, a, b):
    return r[a] is not None and r[b] is not None


PLAUSIBILITY = (
    ("NPL exactly 0", lambda r: r["npl_ratio"] == 0),
    ("Stage 2 exactly 0", lambda r: r["stage2_share"] == 0),
    ("sector HHI = 1", lambda r: r["nace_hhi"] is not None and r["nace_hhi"] >= 0.999),
    ("sovereign HHI = 1", lambda r: r["sovereign_hhi"] is not None and r["sovereign_hhi"] >= 0.999),
    ("Tier 1 < CET1", lambda r: _both(r, "tier1_ratio", "cet1_ratio")
     and r["tier1_ratio"] < r["cet1_ratio"] - 1e-4),
    ("total capital < Tier 1", lambda r: _both(r, "total_capital_ratio", "tier1_ratio")
     and r["total_capital_ratio"] < r["tier1_ratio"] - 1e-4),
    ("leverage > Tier 1 ratio", lambda r: _both(r, "leverage_ratio", "tier1_ratio")
     and r["leverage_ratio"] > r["tier1_ratio"] + 1e-4),
    ("CET1 above 50%", lambda r: r["cet1_ratio"] is not None and r["cet1_ratio"] > 0.5),
    ("|ROE| above 100%", lambda r: r["roe_annualised"] is not None and abs(r["roe_annualised"]) > 1),
    ("NPL above 50%", lambda r: r["npl_ratio"] is not None and r["npl_ratio"] > 0.5),
)


def print_plausibility(rows: list[dict], items: list[dict], info: dict) -> None:
    """Rows breaking simple plausibility rules, stale values, and the panel's own flags."""
    event_keys = {(i["bank_id"], i["period"]) for i in items if i["event"]}
    print("rule                       rows  banks  of which event rows  examples")
    total = set()
    for name, rule in PLAUSIBILITY:
        hits = [r for r in rows if rule(r)]
        banks = Counter(r["bank_id"] for r in hits)
        events = sum(1 for r in hits if (r["bank_id"], r["period"]) in event_keys)
        examples = ", ".join(f"{b} {info.get(b, {}).get('name', '')[:22]}"
                             for b, _ in banks.most_common(3))
        total.update((r["bank_id"], r["period"]) for r in hits)
        print(f"{name:25s} {len(hits):5d} {len(banks):6d} {events:20d}  {examples}")
    stale = []
    for bank, periods in _bank_periods(rows).items():
        by_period = {r["period"]: r for r in rows if r["bank_id"] == bank}
        run = 1
        for prev, cur in zip(periods, periods[1:]):
            a, b = by_period[prev]["cet1_ratio"], by_period[cur]["cet1_ratio"]
            run = run + 1 if a is not None and a == b else 1
            if run == 4:
                stale.append((bank, cur))
    print(f"CET1 identical in 4 or more consecutive reports: {len(stale)} cases at "
          f"{len({b for b, _ in stale})} banks")
    counter = Counter()
    for r in rows:
        for feature, values in (r.get("flags") or {}).items():
            if isinstance(values, list):
                for v in values:
                    if v in ("outlier", "implausible_value", "extreme_growth"):
                        counter[(feature, v)] += 1
    print("panel flags (outlier = more than 3 MAD from the period median):")
    for (feature, flag), n in counter.most_common(12):
        print(f"  {feature:22s} {flag:18s} {n:5d}")
    FINDINGS["9 implausible values"] = (
        f"{len(total)} bank-periods break at least one rule; {len(stale)} stale CET1 runs")


# ---------- 10. label sensitivity and alternatives ----------

def _period_ranks(rows: list[dict], ind: str) -> dict:
    from scipy.stats import rankdata
    by_period = defaultdict(list)
    for r in rows:
        if r[ind] is not None:
            by_period[r["period"]].append(r)
    ranks = {}
    for period, group in by_period.items():
        values = rankdata([r[ind] for r in group]) / len(group)
        for r, v in zip(group, values):
            ranks[(r["bank_id"], period)] = float(v)
    return ranks


def label_variant(rows: list[dict], semiannual: bool, horizon: int = 12, tail: float = 0.05,
                  kind: str = "abs", e3: bool = True) -> list[dict]:
    """Labels like scripts.analyses.events.label_rows, with other horizon, tail or E2 definition.

    kind: abs = CET1 change in points; rel = CET1 change in percent of the level;
          weak = abs fall that also ends in the bottom quartile of CET1 in its period.
    """
    index = {(r["bank_id"], r["period"]): r for r in rows}
    ranks = _period_ranks(rows, "cet1_ratio")
    base = [r for r in rows if r["period"].month in (6, 12)] if semiannual else rows
    items = []
    for r in base:
        later = index.get((r["bank_id"], _month_end(r["period"], horizon)))
        d_cet1 = None
        if later and r["cet1_ratio"] is not None and later["cet1_ratio"] is not None:
            if kind == "rel":
                d_cet1 = later["cet1_ratio"] / r["cet1_ratio"] - 1 if r["cet1_ratio"] > 0 else None
            else:
                d_cet1 = later["cet1_ratio"] - r["cet1_ratio"]
        crosses = r["period"] < NPL_BREAK <= _month_end(r["period"], horizon)
        d_npl = None
        if e3 and later and not crosses and r["npl_ratio"] is not None \
                and later["npl_ratio"] is not None:
            d_npl = later["npl_ratio"] - r["npl_ratio"]
        weak = later is not None and ranks.get((later["bank_id"], later["period"]), 1.0) <= 0.25
        breach = any(r[k] is not None and r[k] < v for k, v in E1_MINIMA.items())
        items.append({"bank_id": r["bank_id"], "period": r["period"], "d_cet1": d_cet1,
                      "d_npl": d_npl, "weak": weak, "e1": breach})
    train = [i for i in items if i["period"] <= TRAIN_END]
    cut_cet1 = np.quantile([i["d_cet1"] for i in train if i["d_cet1"] is not None], tail)
    npl_values = [i["d_npl"] for i in train if i["d_npl"] is not None]
    cut_npl = np.quantile(npl_values, 1 - tail) if npl_values else None
    for i in items:
        if i["d_cet1"] is None:
            i["e2"] = None
        else:
            i["e2"] = bool(i["d_cet1"] <= cut_cet1 and (kind != "weak" or i["weak"]))
        i["e3"] = None if i["d_npl"] is None or cut_npl is None else bool(i["d_npl"] >= cut_npl)
        known = [x for x in (i["e2"], i["e3"]) if x is not None]
        i["event"] = any(known) if known else None
    return items


def print_label_variants(rows: list[dict], info: dict, features: dict, semiannual: bool):
    """Events, overlap with the baseline, known cases marked and feature AUCs per label variant."""
    results = []
    baseline_events = baseline_known = None
    for name, options in LABEL_VARIANTS:
        items = label_variant(rows, semiannual, **options)
        labelled = _labelled_items(items)
        events = {(i["bank_id"], i["period"]) for i in labelled if i["event"]}
        known_keys = {(i["bank_id"], i["period"]) for i in labelled}
        starts = episode_starts(items)
        if baseline_events is None:
            baseline_events, baseline_known = events, known_keys
        common = known_keys & baseline_known
        a, b = events & common, baseline_events & common
        jaccard = len(a & b) / max(len(a | b), 1)
        cases = _case_counts(known_case_results(rows, items, info))
        rz = [features.get((i["bank_id"], i["period"]), {}).get(("cet1_ratio", "rz"))
              for i in starts]
        rz = [v for v in rz if v is not None]
        train, _ = _labelled(items)
        aucs = _kept_aucs(features, train, KEPT)
        banks = len({i["bank_id"] for i in starts})
        results.append({"name": name, "rows": len(labelled), "events": len(events),
                        "episodes": len(starts), "banks": banks, "jaccard": jaccard,
                        "marked": cases["marked"], "with_history": cases["with_history"],
                        "rz": float(np.median(rz)) if rz else float("nan"), **aucs})
    print("training AUC is raw: > 0.5 = higher before events, < 0.5 = lower before events")
    print("variant                      rows  events  episodes  banks  Jaccard  known marked  "
          "CET1 rz at start  AUC cet1:rz  tier1:vol  npl:chg  roe")
    for r in results:
        print(f"{r['name']:26s} {r['rows']:6d} {r['events']:7d} {r['episodes']:9d} {r['banks']:6d} "
              f"{r['jaccard']:8.2f} {r['marked']:7d} of {r['with_history']:<3d} {r['rz']:+16.2f} "
              f"{r['cet1_ratio:rz']:12.2f} {r['tier1_ratio:vol']:10.2f} "
              f"{r['npl_ratio:chg']:8.2f} {r['roe_annualised:raw']:5.2f}")
    FINDINGS["10 label variants"] = "; ".join(
        f"{r['name']}: {r['episodes']} episodes, {r['marked']}/{r['with_history']} cases, "
        f"CET1 rz {r['rz']:+.2f}" for r in results)


# ---------- summary and entry ----------

def print_findings() -> None:
    print("\n=== summary of findings ===")
    for key, text in FINDINGS.items():
        print(f"{key:22s} {text}")


def validity_analyses(rows: list[dict], items: list[dict], semiannual: bool = False) -> dict:
    """Run the ten checks; return the figures."""
    FINDINGS.clear()
    info = bank_info()
    features = build_features(rows)
    figures = {}
    print("\n=== 1. banks leaving the sample (informative censoring) ===")
    figures["exits"] = print_censoring(rows, items, info)
    known = known_case_results(rows, items, info)
    print("\n=== 2. publication lag ===")
    print_publication_lag(rows, items, known)
    print("\n=== 3. known public distress cases ===")
    print_known_cases(known)
    print("\n=== 4. recurrence of events ===")
    print_recurrence(items)
    print_event_banks(items, info)
    print("\n=== 5. mergers and scope changes ===")
    print_structural_changes(rows, items, info, features)
    print("\n=== 6. learning curve ===")
    curve = print_learning_curve(features, items)
    if curve is not None:
        figures["learning_curve"] = curve
    print("\n=== 7. country ===")
    figures["countries"] = print_country(rows, items, info, features)
    print("\n=== 8. RWA density ===")
    print_rwa_density(rows, items)
    print("\n=== 9. implausible values ===")
    print_plausibility(rows, items, info)
    print("\n=== 10. label sensitivity and alternative definitions ===")
    print_label_variants(rows, info, features, semiannual)
    print_findings()
    return figures