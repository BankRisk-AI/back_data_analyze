"""Events in the panel and what the indicators look like before them (exploratory, read-only).

Labels: one row = bank at period t; event window = t .. t + horizon.
  E2  large CET1 fall over the window; cut-off = 5% tail of training changes (<= 2020-12)
        kind "abs"  : change in percentage points (the original ML label)
        kind "rel"  : change in percent of the starting level
        kind "weak" : abs fall that also ends in the bottom quartile of CET1 in its period
  E3  large NPL rise over the window (5% tail); windows crossing the 2020-06 NPL break not labelled
  E4  optional: the bank leaves the sample inside the window, weak at its last report
        (E1 breach, negative ROE, or NPL in the top decile of its period)
  event = E2 or E3 (or E4); None = unknown
  E1  a capital ratio below the thesis thresholds in the period itself (descriptive)
Optional: windows with a loan-book change >= 30% (mergers, portfolio sales) are set to unknown.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

import matplotlib.pyplot as plt
import numpy as np

from scripts.analyses.dataset import TRAIN_END
from scripts.analyses.draw_graph import DEFAULT_INDICATORS, NPL_BREAK, _month_end

E1_MINIMA = {"cet1_ratio": 0.07, "tier1_ratio": 0.085, "total_capital_ratio": 0.105}
TAIL = 0.05
HORIZON = 12
SCOPE_CHANGE = 0.30          # loan-book change treated as merger / sale
WEAK_QUARTILE = 0.25         # E2 "weak": CET1 ends in the bottom quartile of its period
NPL_TOP_DECILE = 0.90        # E4: NPL in the top decile at the last report
OFFSETS = (-24, -18, -12, -6, 0, 6, 12)


@dataclass(frozen=True)
class LabelSpec:
    """How the event label is built."""
    kind: str = "abs"                 # E2: abs | rel | weak
    horizon: int = HORIZON
    tail: float = TAIL
    e3: bool = True
    e3_kind: str = "abs"              # E3: abs | weak (NPL also ends in the top quartile)
    exits: bool = False               # add E4
    drop_scope_changes: bool = False  # unknown label for windows with mergers / sales

    def name(self) -> str:
        parts = [self.kind, f"{self.horizon}m"]
        if self.tail != TAIL:
            parts.append(f"tail{self.tail:g}")
        if not self.e3:
            parts.append("noE3")
        elif self.e3_kind != "abs":
            parts.append(f"e3{self.e3_kind}")
        if self.exits:
            parts.append("exits")
        if self.drop_scope_changes:
            parts.append("noscope")
        return "_".join(parts)


ORIGINAL = LabelSpec()
RECOMMENDED = LabelSpec(kind="weak", e3_kind="weak", exits=True, drop_scope_changes=True)


# ---------- labels ----------

def _forward_change(index: dict, row: dict, indicator: str, months: int = HORIZON):
    """x(t + months) - x(t) for the same bank, or None."""
    later = index.get((row["bank_id"], _month_end(row["period"], months)))
    if later is None or row[indicator] is None or later[indicator] is None:
        return None
    return later[indicator] - row[indicator]


def _period_ranks(rows: list[dict], indicator: str) -> dict:
    """{(bank_id, period): rank in (0, 1] among the banks of that period}."""
    from scipy.stats import rankdata
    by_period = defaultdict(list)
    for r in rows:
        if r[indicator] is not None:
            by_period[r["period"]].append(r)
    ranks = {}
    for period, group in by_period.items():
        values = rankdata([r[indicator] for r in group]) / len(group)
        for r, v in zip(group, values):
            ranks[(r["bank_id"], period)] = float(v)
    return ranks


def _scope_change(index: dict, row: dict, horizon: int) -> bool:
    """A loan-book change >= SCOPE_CHANGE reported inside the window (merger, sale, split)."""
    for months in range(3, horizon + 1, 3):
        later = index.get((row["bank_id"], _month_end(row["period"], months)))
        if later is not None and later["loan_growth_yoy"] is not None \
                and abs(later["loan_growth_yoy"]) >= SCOPE_CHANGE:
            return True
    return False


def _weak_last_report(row: dict, npl_ranks: dict) -> bool:
    """E1 breach, negative ROE or NPL in the top decile at the bank's last report."""
    breach = any(row[k] is not None and row[k] < v for k, v in E1_MINIMA.items())
    loss = row["roe_annualised"] is not None and row["roe_annualised"] < 0
    bad_npl = npl_ranks.get((row["bank_id"], row["period"]), 0.0) >= NPL_TOP_DECILE
    return breach or loss or bad_npl


def label_rows(rows: list[dict], semiannual: bool = False, spec: LabelSpec | None = None):
    """One item per row with e1..e4 and event (None = unknown). Returns (items, info)."""
    spec = spec or ORIGINAL
    index = {(r["bank_id"], r["period"]): r for r in rows}
    last_period = max(r["period"] for r in rows)
    last_report: dict[int, date] = {}
    for r in rows:
        if r["bank_id"] not in last_report or r["period"] > last_report[r["bank_id"]]:
            last_report[r["bank_id"]] = r["period"]
    cet1_ranks = _period_ranks(rows, "cet1_ratio")
    npl_ranks = _period_ranks(rows, "npl_ratio")
    base = [r for r in rows if r["period"].month in (6, 12)] if semiannual else rows

    items = []
    for r in base:
        end = _month_end(r["period"], spec.horizon)
        later = index.get((r["bank_id"], end))
        d_cet1 = None
        if later is not None and r["cet1_ratio"] is not None and later["cet1_ratio"] is not None:
            if spec.kind == "rel":
                if r["cet1_ratio"] > 0:
                    d_cet1 = later["cet1_ratio"] / r["cet1_ratio"] - 1
            else:
                d_cet1 = later["cet1_ratio"] - r["cet1_ratio"]
        d_npl = None
        if spec.e3 and not (r["period"] < NPL_BREAK <= end):
            d_npl = _forward_change(index, r, "npl_ratio", spec.horizon)
        ends_weak = later is not None and \
            cet1_ranks.get((later["bank_id"], later["period"]), 1.0) <= WEAK_QUARTILE
        npl_ends_bad = later is not None and \
            npl_ranks.get((later["bank_id"], later["period"]), 0.0) >= 1 - WEAK_QUARTILE
        last = last_report[r["bank_id"]]
        leaves = r["period"] <= last < end <= last_period
        e4 = None
        if spec.exits and leaves and _weak_last_report(index[(r["bank_id"], last)], npl_ranks):
            e4 = True
        items.append({
            "bank_id": r["bank_id"],
            "period": r["period"],
            "d_cet1": d_cet1,
            "d_npl": d_npl,
            "ends_weak": ends_weak,
            "npl_ends_bad": npl_ends_bad,
            "scope": spec.drop_scope_changes and _scope_change(index, r, spec.horizon),
            "e1": any(r[k] is not None and r[k] < v for k, v in E1_MINIMA.items()),
            "e4": e4,
        })

    train = [i for i in items if i["period"] <= TRAIN_END]
    cet1_train = [i["d_cet1"] for i in train if i["d_cet1"] is not None]
    npl_train = [i["d_npl"] for i in train if i["d_npl"] is not None]
    cuts = {
        "cet1_fall": float(np.quantile(cet1_train, spec.tail)),
        "npl_rise": float(np.quantile(npl_train, 1 - spec.tail)) if npl_train else None,
    }
    for i in items:
        if i["scope"] or i["d_cet1"] is None:
            i["e2"] = None
        else:
            fall = i["d_cet1"] <= cuts["cet1_fall"]
            i["e2"] = bool(fall and (spec.kind != "weak" or i["ends_weak"]))
        if i["scope"] or i["d_npl"] is None or cuts["npl_rise"] is None:
            i["e3"] = None
        else:
            rise = i["d_npl"] >= cuts["npl_rise"]
            i["e3"] = bool(rise and (spec.e3_kind != "weak" or i["npl_ends_bad"]))
        known = [x for x in (i["e2"], i["e3"], i["e4"]) if x is not None]
        i["event"] = any(known) if known else None
    info = {**cuts, "label": spec.name(),
            "scope_dropped": sum(1 for i in items if i["scope"]),
            "exit_events": sum(1 for i in items if i["e4"])}
    return items, info


def episode_starts(items: list[dict], key: str = "event") -> list[dict]:
    """First item of each run of consecutive event rows of a bank (one episode = one event)."""
    by_bank = defaultdict(list)
    for i in items:
        by_bank[i["bank_id"]].append(i)
    starts = []
    for bank_items in by_bank.values():
        bank_items.sort(key=lambda i: i["period"])
        previous = None
        for i in bank_items:
            continues = (previous is not None and previous[key]
                         and _month_end(previous["period"], 6) >= i["period"])
            if i[key] and not continues:
                starts.append(i)
            previous = i
    return starts


def auc(positive: list[float], negative: list[float]) -> float:
    """Probability that a random event value is higher than a random non-event value (0.5 = no signal)."""
    from scipy.stats import mannwhitneyu
    if len(positive) < 5 or len(negative) < 5:
        return float("nan")
    u = mannwhitneyu(positive, negative, alternative="two-sided").statistic
    return float(u / (len(positive) * len(negative)))


# ---------- 9. how many events, when, where ----------

def print_events(items: list[dict], info: dict) -> None:
    """Events per year, episodes, banks, and the E1 breaches."""
    npl = "-" if info["npl_rise"] is None else f"{info['npl_rise']:+.4f}"
    print(f"\nlabel: {info['label']}")
    print(f"cut-offs from training periods: CET1 change <= {info['cet1_fall']:+.4f}, "
          f"NPL change >= {npl}")
    print(f"windows set to unknown because of a merger / sale: {info['scope_dropped']}; "
          f"exit events (E4): {info['exit_events']}")
    starts = episode_starts(items)
    starts_per_year = Counter(i["period"].year for i in starts)
    by_year = defaultdict(list)
    for i in items:
        by_year[i["period"].year].append(i)
    print("\nyear  labelled  E1 now  E2 rows  E3 rows  E4 rows  event rows   rate  episodes  banks")
    for year in sorted(by_year):
        group = by_year[year]
        known = [i for i in group if i["event"] is not None]
        events = [i for i in known if i["event"]]
        rate = len(events) / len(known) if known else float("nan")
        e1 = sum(i["e1"] for i in group)
        e2 = sum(bool(i["e2"]) for i in group)
        e3 = sum(bool(i["e3"]) for i in group)
        e4 = sum(bool(i["e4"]) for i in group)
        banks = len({i["bank_id"] for i in events})
        print(f"{year}  {len(known):8d} {e1:7d} {e2:8d} {e3:8d} {e4:8d} {len(events):11d} "
              f"{rate:6.1%} {starts_per_year[year]:9d} {banks:6d}")
    known = [i for i in items if i["event"] is not None]
    events = [i for i in known if i["event"]]
    print(f"total: {len(known)} labelled rows, {len(events)} event rows, {len(starts)} episodes, "
          f"{len({i['bank_id'] for i in starts})} banks with at least one episode")
    e1_banks = sorted({i["bank_id"] for i in items if i["e1"]})
    print(f"E1 breaches: {sum(i['e1'] for i in items)} rows at {len(e1_banks)} banks: {e1_banks}")
    top = Counter(i["bank_id"] for i in starts).most_common(10)
    print("banks with most episodes: " + ", ".join(f"{b} ({n})" for b, n in top))


def events_figure(items: list[dict]):
    """Top: share of banks starting an event window per period. Bottom: E1 breaches."""
    by_period = defaultdict(list)
    for i in items:
        by_period[i["period"]].append(i)
    periods = sorted(by_period)

    def rate(group, key):
        known = [i for i in group if i[key] is not None]
        return sum(bool(i[key]) for i in known) / len(known) if known else np.nan

    def share(group, key):
        known = [i for i in group if i["event"] is not None]
        return sum(bool(i[key]) for i in known) / len(known) if known else np.nan

    x = np.arange(len(periods))
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True)
    top.bar(x, [rate(by_period[p], "event") for p in periods], color="lightgrey", label="any event")
    top.plot(x, [rate(by_period[p], "e2") for p in periods], color="tab:blue", marker="o",
             markersize=3, label="E2: large CET1 fall")
    top.plot(x, [rate(by_period[p], "e3") for p in periods], color="tab:red", marker="o",
             markersize=3, label="E3: large NPL rise")
    if any(i["e4"] for i in items):
        top.plot(x, [share(by_period[p], "e4") for p in periods], color="black", marker="x",
                 markersize=4, linestyle="none", label="E4: leaves in a weak state")
    top.axhline(TAIL, color="black", linestyle=":", linewidth=1, label="5% (cut-off level)")
    train_edge = sum(1 for p in periods if p <= TRAIN_END) - 0.5
    for ax in (top, bottom):
        ax.axvline(train_edge, color="grey", linestyle="--", linewidth=1)
        ax.grid(alpha=0.3)
    top.set(ylabel="share of labelled banks",
            title="Event windows starting in each period (dashed line = end of training periods)")
    top.legend(fontsize=8, frameon=False)
    bottom.bar(x, [sum(i["e1"] for i in by_period[p]) for p in periods], color="tab:red")
    bottom.set(ylabel="banks", title="E1: banks below a capital threshold in the period")
    bottom.set_xticks(x)
    bottom.set_xticklabels([str(p)[:7] for p in periods], rotation=90, fontsize=7)
    fig.tight_layout()
    return fig, len(periods)


# ---------- 10. what happens before an event ----------

def period_medians(rows: list[dict], indicators: tuple[str, ...]) -> dict:
    """{(period, indicator): median over banks}."""
    values = defaultdict(list)
    for r in rows:
        for indicator in indicators:
            if r[indicator] is not None:
                values[(r["period"], indicator)].append(r[indicator])
    return {key: float(np.median(v)) for key, v in values.items()}


def event_profiles(rows: list[dict], items: list[dict],
                   indicators: tuple[str, ...] = DEFAULT_INDICATORS):
    """{indicator: {offset: (event values, control values)}} relative to the period median."""
    index = {(r["bank_id"], r["period"]): r for r in rows}
    medians = period_medians(rows, indicators)
    events = episode_starts(items)
    controls = [i for i in items if i["event"] is False]
    profiles = {ind: {k: ([], []) for k in OFFSETS} for ind in indicators}
    for position, group in enumerate((events, controls)):
        for i in group:
            for k in OFFSETS:
                period = _month_end(i["period"], k)
                r = index.get((i["bank_id"], period))
                if r is None:
                    continue
                for ind in indicators:
                    if r[ind] is not None:
                        profiles[ind][k][position].append(r[ind] - medians[(period, ind)])
    return profiles, len(events), len(controls)


def print_event_study(profiles: dict, n_events: int, n_controls: int) -> None:
    """Medians and AUC 12 and 6 months before the event window and at its start."""
    print(f"\n{n_events} event episodes vs {n_controls} non-event rows; "
          f"values = indicator minus the median of all banks in that period")
    print("AUC: 0.5 = no difference, > 0.5 = higher before events, < 0.5 = lower before events")
    print("indicator              offset  median event  median control   AUC  n events")
    for indicator, by_offset in profiles.items():
        for k in (-12, -6, 0):
            events, controls = by_offset[k]
            if not events or not controls:
                continue
            print(f"{indicator:22s} {k:+4d}m {np.median(events):+13.4f} "
                  f"{np.median(controls):+14.4f} {auc(events, controls):5.2f} {len(events):9d}")


def event_study_figure(profiles: dict, n_events: int):
    """Median and 25-75% band of events vs non-events around the event start."""
    indicators = list(profiles)
    columns = 2
    lines = (len(indicators) + 1) // columns
    fig, axes = plt.subplots(lines, columns, figsize=(11, 2.8 * lines))
    for ax, indicator in zip(axes.flat, indicators):
        for position, (label, colour) in enumerate((("event", "tab:red"), ("no event", "grey"))):
            xs, mid, low, high = [], [], [], []
            for k in OFFSETS:
                values = profiles[indicator][k][position]
                if len(values) >= 5:
                    xs.append(k)
                    low_k, mid_k, high_k = np.percentile(values, [25, 50, 75])
                    low.append(low_k)
                    mid.append(mid_k)
                    high.append(high_k)
            ax.fill_between(xs, low, high, color=colour, alpha=0.2)
            ax.plot(xs, mid, color=colour, marker="o", markersize=3, label=label)
        ax.axvspan(0, HORIZON, color="tab:red", alpha=0.05)
        ax.axvline(0, color="black", linewidth=0.8)
        ax.axhline(0, color="grey", linewidth=0.6, linestyle=":")
        events0, controls0 = profiles[indicator][0]
        ax.set_title(f"{indicator}  (AUC at t0 = {auc(events0, controls0):.2f})", fontsize=9)
        ax.set_xticks(OFFSETS)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7, frameon=False)
    for ax in list(axes.flat)[len(indicators):]:
        ax.set_visible(False)
    fig.suptitle(f"Before and after an event ({n_events} episodes); months from t0, "
                 f"values minus the period median; shaded = event window")
    fig.tight_layout()
    return fig, len(indicators)