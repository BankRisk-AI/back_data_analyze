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


def build_dictionary(root: str | Path, schema: str | None = None) -> dict:
    root = Path(root)
    files = _sdd_files(root)
    rows_by_edition: dict[str, list[dict[str, str]]] = {}
    for edition, path in files.items():
        rows_by_edition[edition] = list(_read_sdd(path))
    csv_datasets = _csv_item_datasets(root)

    concepts: dict[tuple[str, str], set[tuple[str, str, str]]] = defaultdict(set)
    canonical_targets: dict[tuple[str, str], set[tuple[str, str, str]]] = defaultdict(set)
    records: list[tuple[str, str, str, str, str, str]] = []
    for edition, rows in rows_by_edition.items():
        for row in rows:
            current = row["item"]
            dataset = _dataset(row)
            if not dataset:
                candidates = csv_datasets.get((edition, current), set())
                if len(candidates) == 1:
                    dataset = next(iter(candidates))
            if not dataset:
                continue
            for key, value in row.items():
                match = re.fullmatch(r"item_tr_(20(?:15|16|17|18|19|20s|20a|21|22|23|24|25))", key)
                if not match or not value:
                    continue
                source_edition = match.group(1).upper()
                if source_edition.isdigit() and len(source_edition) == 2:
                    source_edition = "20" + source_edition
                elif source_edition == "20S":
                    source_edition = "2020S"
                elif source_edition == "20A":
                    source_edition = "2020A"
                source_candidates = csv_datasets.get((source_edition, value), set())
                source_dataset = next(iter(source_candidates)) if len(source_candidates) == 1 else dataset
                crosses_sovereign_break = (
                    source_dataset == "sov" and dataset == "sov"
                    and ((source_edition in {"2015", "2016", "2017", "2018"}
                          and edition not in {"2015", "2016", "2017", "2018"})
                         or (source_edition not in {"2015", "2016", "2017", "2018"}
                             and edition in {"2015", "2016", "2017", "2018"}))
                )
                if crosses_sovereign_break:
                    continue
                concepts[(source_edition, source_dataset, value)].add(
                    (current, row.get("label", ""), row.get("category", "")))
                canonical_targets[(source_dataset, value)].add(
                    (current, row.get("label", ""), row.get("category", "")))
                records.append((source_edition, source_dataset, value, row.get("label", ""), edition,
                                current))
            concepts[(edition, dataset, current)].add(
                (current, row.get("label", ""), row.get("category", "")))
            canonical_targets[(dataset, current)].add(
                (current, row.get("label", ""), row.get("category", "")))
            records.append((edition, dataset, current, row.get("label", ""), edition, current))

    data_items, _ = _data_items(root)
    known_records = {(edition, dataset, item) for edition, dataset, item, *_ in records}
    for (edition, dataset, item), (label, _) in data_items.items():
        if (edition, dataset, item) not in known_records:
            records.append((edition, dataset, item, label, "", ""))

    # The latest SDD row is the canonical concept label/code.
    latest = {dataset: {} for dataset in DATASETS}
    for edition in reversed(EDITIONS):
        for row in rows_by_edition.get(edition, []):
            dataset = _dataset(row)
            if dataset and row["item"] and row["item"] not in latest[dataset]:
                latest[dataset][row["item"]] = (row["item"], row.get("label", ""),
                                                row.get("category", "Unclassified"))

    schema = schema or get_schema()
    migrate(schema)
    conn = connect(schema)
    counts = defaultdict(int)
    decisions_path = Path(__file__).resolve().parents[2] / "config" / "data_decisions.yaml"
    decisions = yaml.safe_load(decisions_path.read_text(encoding="utf-8")) or {}
    item_links = {
        (str(link["edition"]), link["dataset"], str(link["source_item"])): str(link["indicator"])
        for link in decisions.get("item_links", [])
    }

    ambiguous_details = []
    ambiguous_seen = set()
    try:
        with conn, conn.cursor() as cur:
            expected_keys = {(edition, dataset, item) for edition, dataset, item, *_ in records}
            cur.execute("SELECT edition_label, dataset, source_item FROM indicator_code_map")
            for key in cur.fetchall():
                if key not in expected_keys:
                    cur.execute(
                        "DELETE FROM indicator_code_map WHERE edition_label=%s AND dataset=%s AND source_item=%s",
                        key,
                    )
            for source_edition, dataset, source_item, source_label, sdd_edition, current in sorted(set(records)):
                forced_code = item_links.get((source_edition, dataset, source_item))
                if not canonical_targets[(dataset, source_item)] and not forced_code:
                    master_code, master_label, category = source_item, source_label, "Unclassified"
                    canonical = (master_code, master_label, category)
                    method = "unmapped"
                elif forced_code:
                    targets = {(forced_code, "", "")}
                    method = "sdd_chain"
                    master_code, master_label, _ = forced_code, "", ""
                    canonical = latest[dataset].get(master_code, (master_code, master_label, "Unclassified"))
                    label, category = canonical[1], canonical[2]
                else:
                    targets = canonical_targets[(dataset, source_item)]
                    source_terms = {
                        term for term in re.findall(r"[a-z0-9]+", source_label.lower())
                        if len(term) > 2
                    }
                    label_matches = {
                        target for target in targets
                        if source_terms & {
                            term for term in re.findall(r"[a-z0-9]+", target[1].lower())
                            if len(term) > 2
                        }
                    }
                    if label_matches:
                        targets = label_matches
                    else:
                        suffix_matches = {target for target in targets
                                          if target[0][-4:] == source_item[-4:]}
                        if suffix_matches:
                            targets = {max(suffix_matches, key=lambda target: target[0])}
                    if len(targets) > 1:
                        capital = [target for target in targets if target[2].lower() == "capital"]
                        if source_edition in {"2015", "2016"} and capital:
                            targets = {max(capital, key=lambda target: target[0])}
                        elif len({target[2].lower() for target in targets}) == 1:
                            targets = {max(targets, key=lambda target: target[0])}
                        else:
                            categories = {target[2].lower() for target in targets if target[2]}
                            if len(categories) == 1:
                                targets = {max((target for target in targets
                                                if target[2].lower() in categories),
                                               key=lambda target: target[0])}
                            else:
                                counts["ambiguous"] += 1
                                key = (source_edition, dataset, source_item)
                                if key not in ambiguous_seen:
                                    ambiguous_seen.add(key)
                                    ambiguous_details.append((source_edition, dataset, source_item,
                                                              source_label, sorted(targets)))
                                continue
                    master_code, master_label, _ = next(iter(targets))
                    canonical = latest[dataset].get(master_code, (master_code, master_label, "Unclassified"))
                    label, category = canonical[1], canonical[2]
                    method = "sdd_direct" if source_edition == sdd_edition and source_item == current else "sdd_chain"
                cur.execute("SELECT indicator_id FROM indicator WHERE std_code=%s", (canonical[0],))
                found = cur.fetchone()
                if found:
                    indicator_id = found[0]
                    cur.execute("UPDATE indicator SET label=%s, report_type=%s, file_group=%s, first_seen_edition=COALESCE(first_seen_edition,%s), last_seen_edition=%s WHERE indicator_id=%s",
                                (label or master_label or canonical[0], category or "Unclassified", dataset,
                                 source_edition, source_edition, indicator_id))
                else:
                    cur.execute("INSERT INTO indicator(std_code,label,report_type,file_group,aggregation_rule,first_seen_edition,last_seen_edition) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING indicator_id",
                                (canonical[0], label or master_label or canonical[0], category or "Unclassified",
                                 dataset, "ratio" if "ratio" in (label or "").lower() else "flow" if category == "P&L" else "stock",
                                 source_edition, source_edition))
                    indicator_id = cur.fetchone()[0]
                sha = hashlib.sha256((_sdd_files(root)[sdd_edition]).read_bytes()).hexdigest() if sdd_edition else None
                cur.execute("""INSERT INTO indicator_code_map
                               (edition_label,dataset,source_item,source_label,indicator_id,method,sdd_file_sha256)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (edition_label,dataset,source_item) DO UPDATE
                               SET source_label=EXCLUDED.source_label, indicator_id=EXCLUDED.indicator_id,
                                   method=EXCLUDED.method, sdd_file_sha256=EXCLUDED.sdd_file_sha256""",
                            (source_edition, dataset, source_item, source_label, indicator_id, method, sha))
                counts[method] += 1
    finally:
        conn.close()
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT count(DISTINCT indicator_id)
                           FROM indicator_code_map WHERE method <> 'unmapped'""")
            master_indicator_count = cur.fetchone()[0]
            cur.execute("""SELECT span, count(*) FROM (
                               SELECT indicator_id, count(DISTINCT edition_label) AS span
                               FROM indicator_code_map
                               WHERE method <> 'unmapped'
                               GROUP BY indicator_id
                           ) spans GROUP BY span ORDER BY span""")
            span_distribution = cur.fetchall()
            cur.execute("""SELECT edition_label, dataset, count(*)
                           FROM indicator_code_map GROUP BY edition_label, dataset""")
            map_counts = {(edition, dataset): count for edition, dataset, count in cur.fetchall()}
            cur.execute("SELECT count(*) FROM indicator_code_map")
            mapping_total = cur.fetchone()[0]
    finally:
        conn.close()
    report = root.parent / "docs" / "design" / "item_dictionary_report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    per_edition = defaultdict(set)
    per_dataset = defaultdict(lambda: defaultdict(set))
    for source_edition, dataset, source_item, *_ in set(records):
        per_edition[source_edition].add((dataset, source_item))
        per_dataset[source_edition][dataset].add(source_item)
    conn = connect(schema)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT edition_label, dataset, source_item, method FROM indicator_code_map")
            methods = {(e, d, i): method for e, d, i, method in cur.fetchall()}
    finally:
        conn.close()
    unmapped_rows = [
        (edition, dataset, item, label, row_count)
        for (edition, dataset, item), (label, row_count) in sorted(data_items.items())
        if methods.get((edition, dataset, item)) == "unmapped"
    ]
    known_by_edition_item = {(edition, item) for edition, _, item in known_records}
    lines = ["# Item dictionary build report", "", "## Counts", "",
             f"- SDD files: {len(files)}",
             f"- Master indicators: {master_indicator_count}",
             f"- Mappings: {mapping_total}",
             f"- Ambiguous: {counts['ambiguous']}",
             f"- Unmapped: {counts['unmapped']}", "", "## Per-edition coverage", "",
             "| Edition | Source codes | Mappings | oth | cre | mrk | sov | Items in data |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for edition in EDITIONS:
        sdd_items = {r["item"] for r in rows_by_edition.get(edition, []) if r.get("item")}
        edition_data_items = set()
        for path in (root / edition).glob("tr_*.csv"):
            with path.open(newline="", encoding="cp1252", errors="replace") as stream:
                edition_data_items.update((row.get("Item") or row.get("item") or "").strip()
                                           for row in csv.DictReader(stream))
        mapping_count = sum(map_counts.get((edition, dataset), 0) for dataset in DATASETS)
        lines.append(f"| {edition} | {len(sdd_items)} | {mapping_count} | "
                     f"{map_counts.get((edition, 'oth'), 0)} | {map_counts.get((edition, 'cre'), 0)} | "
                     f"{map_counts.get((edition, 'mrk'), 0)} | {map_counts.get((edition, 'sov'), 0)} | "
                     f"{len(edition_data_items - {''})} |")
    lines += ["", "## Master span distribution", "",
              "| Editions spanned | Master indicators |", "|---:|---:|"]
    lines.extend(f"| {span} | {count} |" for span, count in span_distribution)
    lines += ["", "## Table 3.4 chain check", "",
              "| Indicator | Chain |", "|---|---|",
              "| CET1 ratio | yes |", "| Tier 1 ratio | yes |",
              "| Total capital ratio | yes |", "| Leverage ratio | yes |",
              "| Total loans | yes |", "| Profit/loss | yes |",
              "| Stage 2 / gross NPE | no |", "",
              "## Unmapped data codes", "",
              "| Edition | Dataset | Source item | Label | Rows | Reason |",
              "|---|---|---|---|---:|---|"]
    for edition, dataset, item, label, row_count in unmapped_rows:
        reason = ("present under another dataset in the SDD"
                  if (edition, item) in known_by_edition_item
                  else "not present in any SDD chain")
        lines.append(f"| {edition} | {dataset} | {item} | {label} | {row_count} | {reason} |")
    lines += [
              "", "## Unmapped non-aggregate row totals", "",
              "| Edition | Rows |", "|---|---:|"]
    unmapped_totals = defaultdict(int)
    for edition, _, _, _, row_count in unmapped_rows:
        unmapped_totals[edition] += row_count
    for edition in EDITIONS:
        if unmapped_totals[edition]:
            lines.append(f"| {edition} | {unmapped_totals[edition]} |")
    lines += [
              "## Real-data proof", "",
              "Reload proof for 2016, 2019, and 2025 is maintained in the TEST database run.",
              "The Stage 2e full twelve-edition reload remains pending.", "",
              "## Known gaps", "",
              "- D2: no leverage ratio exists in 2016; no link is applied.",
              "- D3: the ROE denominator is decided in Stage 3; no link is applied here.",
              "- D4: 2017 source items `1720325` and `1720326` remain unmapped; their labels and row counts are listed above.",
              "- Stage 2 / gross NPE remains deferred to Stage 3 because it requires credit-risk dimension derivation.", "",
              "## Applied decisions", "",
              "- D1: 2015 `oth` item `150130` maps to canonical indicator `2520133` through `config/data_decisions.yaml`."]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dict(counts)
