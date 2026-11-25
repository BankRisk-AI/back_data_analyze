"""Write the hypotheses report: hypotheses.json (machine) and hypotheses.md (summary)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.eba_ml.application.io import write_json
from scripts.hypotheses.context import RunContext


def build_report(ctx: RunContext, sections: dict[str, Any]) -> dict[str, Any]:
    """Assemble the report dict: run metadata, H1a, H1b, H2, H3, H4 (pending), H5."""
    return {"run": str(ctx.run_dir), "selected_model": ctx.selected,
            "H1a": sections["H1a"], "H1b": sections["H1b"], "H2": sections["H2"],
            "H3": sections["H3"], "H4": {"status": ctx.settings.h4_status},
            "H5": sections["H5"]}


def _fmt_ci(ci: list[float]) -> str:
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def markdown_summary(report: dict[str, Any]) -> str:
    """One short block per hypothesis, with the headline numbers."""
    lines = [f"# Hypotheses - {report['run']}", "",
             f"Selected model: **{report['selected_model']}**", ""]
    lines.append("## H1a - ML vs LR (dPR-AUC)")
    for key in ("RF_vs_LR", "XGB_vs_LR"):
        d = report["H1a"].get(key, {}).get("dPR")
        if d:
            lines.append(f"- {key}: {d['estimate']:+.4f} CI95 {_fmt_ci(d['ci95'])} "
                         f"p_holm={d.get('p_holm', float('nan')):.4f}")
    h1b = report["H1b"]
    lines += ["", "## H1b - ML vs R1 recall at equal alert volume (final test)"]
    if "recall_diff" in h1b:
        lines.append(f"- ML {h1b['ml_recall']:.3f} vs R1 {h1b['r1_recall']:.3f}; "
                     f"diff {h1b['recall_diff']:+.3f} CI95 {_fmt_ci(h1b['ci95'])}; "
                     f"supported={h1b['supported']}")
    else:
        lines.append(f"- status: {h1b.get('status')}")
    h2 = report["H2"]
    lines += ["", "## H2 - lead time before R0 breach",
              f"- evaluated {h2['n_evaluated']} of {h2['n_breach_banks']} breach banks; "
              f"median L = {h2['median_L_quarters']} quarters; Wilcoxon {h2['wilcoxon']['status']}"]
    h3 = report["H3"]
    lines += ["", "## H3 - levels+trends vs levels only",
              f"- dPR {h3['dPR']['estimate']:+.4f} CI95 {_fmt_ci(h3['dPR']['ci95'])}"]
    h5 = report["H5"]
    lines += ["", "## H5 - SHAP families", f"- status: {h5['status']}"]
    if h5["status"] == "computed":
        ranked = sorted(h5["primary"].items(), key=lambda x: -x[1])
        lines.append("- ranking: " + ", ".join(f"{n} ({v:.3f})" for n, v in ranked))
        lines.append(f"- Capital and Earnings rank 1-2: {h5['capital_earnings_rank_1_2']}")
    lines += ["", f"## H4 - {report['H4']['status']}", ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], out_dir: Path, quick: bool) -> Path:
    """Write hypotheses[_quick].json and .md into out_dir; return the JSON path."""
    stem = "hypotheses_quick" if quick else "hypotheses"
    json_path = out_dir / f"{stem}.json"
    write_json(json_path, report)
    (out_dir / f"{stem}.md").write_text(markdown_summary(report))
    return json_path
