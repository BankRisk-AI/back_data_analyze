"""Events in the panel and what the indicators look like before them (exploratory, read-only).

Approximation of the ML labels:
  E2 = CET1 12-month change in the lowest 5% (cut-off from training periods <= 2020-12)
  E3 = NPL 12-month change in the highest 5% (windows crossing the 2020-06 NPL break not labelled)
  event = E2 or E3
  E1 = a capital ratio below the thesis thresholds in the period itself
"""
from __future__ import annotations

from collections import Counter, defaultdict

import matplotlib.pyplot as plt
import numpy as np

from scripts.analyses.dataset import TRAIN_END
from scripts.analyses.draw_graph import DEFAULT_INDICATORS, NPL_BREAK, _month_end

E1_MINIMA = {"cet1_ratio": 0.07, "tier1_ratio": 0.085, "total_capital_ratio": 0.105}
TAIL = 0.05
HORIZON = 12
OFFSETS = (-24, -18, -12, -6, 0, 6, 12)


# ---------- labels ----------

def _forward_change(index: dict, row: dict, indicator: str, months: int = HORIZON):
    """x(t + months) - x(t) for the same bank, or None."""
    later = index.get((row["bank_id"], _month_end(row["period"], months)))
    if later is None or row[indicator] is None or later[indicator] is None:
        return None
    return later[indicator] - row[indicator]


def label_rows(rows: list[dict], semiannual: bool = False):
    """One item per row with e1, e2, e3 and event (None = unknown). Returns (items, cut-offs)."""
    index = {(r["bank_id"], r["period"]): r for r in rows}
    if semiannual:
        base = [r for r in rows if r["period"].month in (6, 12)]
    else:
        base = rows
    items = []
    for r in base:
        crosses_break = r["period"] < NPL_BREAK <= _month_end(r["period"], HORIZON)
        breach = any(r[k] is not None and r[k] < v for k, v in E1_MINIMA.items())
        items.append({
            "bank_id": r["bank_id"],
            "period": r["period"],
            "d_cet1": _forward_change(index, r, "cet1_ratio"),
            "d_npl": None if crosses_break else _forward_change(index, r, "npl_ratio"),
            "e1": breach,
        })
    train = [i for i in items if i["period"] <= TRAIN_END]
    cuts = {
        "cet1_fall": float(np.quantile([i["d_cet1"] for i in train if i["d_cet1"] is not None], TAIL)),
        "npl_rise": float(np.quantile([i["d_npl"] for i in train if i["d_npl"] is not None], 1 - TAIL)),
    }
    for i in items:
        i["e2"] = None if i["d_cet1"] is None else bool(i["d_cet1"] <= cuts["cet1_fall"])
        i["e3"] = None if i["d_npl"] is None else bool(i["d_npl"] >= cuts["npl_rise"])
        known = [x for x in (i["e2"], i["e3"]) if x is not None]
        i["event"] = any(known) if known else None
    return items, cuts


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

def print_events(items: list[dict], cuts: dict) -> None:
    """Events per year, episodes, banks, and the E1 breaches."""
    print(f"\ncut-offs from training periods: CET1 12-month change <= {cuts['cet1_fall']:+.4f}, "
          f"NPL 12-month change >= {cuts['npl_rise']:+.4f}")
    starts = episode_starts(items)
    starts_per_year = Counter(i["period"].year for i in starts)
    by_year = defaultdict(list)
    for i in items:
        by_year[i["period"].year].append(i)
    print("\nyear  labelled  E1 now  E2 rows  E3 rows  event rows   rate  episodes  banks")
    for year in sorted(by_year):
        group = by_year[year]
        known = [i for i in group if i["event"] is not None]
        events = [i for i in known if i["event"]]
        rate = len(events) / len(known) if known else float("nan")
        e1 = sum(i["e1"] for i in group)
        e2 = sum(bool(i["e2"]) for i in group)
        e3 = sum(bool(i["e3"]) for i in group)
        banks = len({i["bank_id"] for i in events})
        print(f"{year}  {len(known):8d} {e1:7d} {e2:8d} {e3:8d} {len(events):11d} {rate:6.1%} "
              f"{starts_per_year[year]:9d} {banks:6d}")
    known = [i for i in items if i["event"] is not None]
    events = [i for i in known if i["event"]]
    print(f"total: {len(known)} labelled rows, {len(events)} event rows, {len(starts)} episodes, "
          f"{len({i['bank_id'] for i in starts})} banks with at least one episode")
    e1_banks = sorted({i["bank_id"] for i in items if i["e1"]})
    print(f"E1 breaches: {sum(i['e1'] for i in items)} rows at {len(e1_banks)} banks: {e1_banks}")
    top = Counter(i["bank_id"] for i in starts).most_common(10)
    print("banks with most episodes: " + ", ".join(f"{b} ({n})" for b, n in top))


def events_figure(items: list[dict]):
    """Top: share of banks starting an event window per period. Bottom: E1 breaches. Returns (fig, periods)."""
    by_period = defaultdict(list)
    for i in items:
        by_period[i["period"]].append(i)
    periods = sorted(by_period)

    def rate(group, key):
        known = [i for i in group if i[key] is not None]
        return sum(bool(i[key]) for i in known) / len(known) if known else np.nan

    x = np.arange(len(periods))
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True)
    top.bar(x, [rate(by_period[p], "event") for p in periods], color="lightgrey", label="E2 or E3")
    top.plot(x, [rate(by_period[p], "e2") for p in periods], color="tab:blue", marker="o",
             markersize=3, label="E2: large CET1 fall")
    top.plot(x, [rate(by_period[p], "e3") for p in periods], color="tab:red", marker="o",
             markersize=3, label="E3: large NPL rise")
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


def event_profiles(rows: list[dict], items: list[dict], indicators: tuple[str, ...] = DEFAULT_INDICATORS):
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
            print(f"{indicator:22s} {k:+4d}m {np.median(events):+13.4f} {np.median(controls):+14.4f} "
                  f"{auc(events, controls):5.2f} {len(events):9d}")


def event_study_figure(profiles: dict, n_events: int):
    """Median and 25-75% band of events vs non-events around the event start. Returns (fig, panels)."""
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
                 f"values minus the period median; shaded = 12-month event window")
    fig.tight_layout()
    return fig, len(indicators)