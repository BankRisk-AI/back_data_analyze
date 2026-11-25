#!/usr/bin/env python3
"""Download the EBA EU-wide transparency exercise databases, one folder per edition.

For every edition it reads the edition page on eba.europa.eu, collects the "Full database"
links (tr_oth, tr_cre, tr_mrk, tr_sov, SDD, TR_Metadata) and downloads them.
Only the Python standard library is used.

Examples:
    python -m scripts.data.download_eba                      # all editions into ./eba_data
    python -m scripts.data.download_eba --years 2023 2024    # only these editions
    python -m scripts.data.download_eba --dry-run            # list what would be downloaded
    python -m scripts.data.download_eba --with-guides        # also the CSV guide PDFs
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

BASE = "https://www.eba.europa.eu/risk-and-data-analysis/risk-analysis"
TE = f"{BASE}/eu-wide-transparency-exercise"

# Edition pages as listed on eba.europa.eu. 2025 lives on the exercise's main page.
EDITIONS: dict[int, list[str]] = {
    2025: [TE, "https://www.eba.europa.eu/node/18852"],
    2024: [f"{TE}/2024-eu-wide-transparency-exercise"],
    2023: [f"{TE}/2023-eu-wide-transparency-exercise"],
    2022: [f"{TE}/2022-eu-wide-transparency-exercise"],
    2021: [f"{TE}/2021-eu-wide-transparency"],
    2020: [f"{TE}/2020-eu-wide-transparency"],
    2019: [f"{TE}/2019-eu-wide-transparency"],
    2018: [f"{BASE}/2018-eu-wide-transparency-exercise"],
    2017: [f"{BASE}/2017-eu-wide-transparency-exercise"],
    2016: [f"{BASE}/2016-eu-wide-transparency-exercise"],
    2015: [f"{BASE}/2015-eu-wide-transparency-exercise"],
    2013: [f"{BASE}/2013-eu-wide-transparency-exercise"],
}

# File kinds the application needs, recognised by file name.
KINDS = {
    "tr_oth": re.compile(r"^tr_oth.*\.(csv|zip)$", re.I),
    "tr_cre": re.compile(r"^tr_cre.*\.(csv|zip)$", re.I),
    "tr_mrk": re.compile(r"^tr_mrk.*\.(csv|zip)$", re.I),
    "tr_sov": re.compile(r"^tr_sov.*\.(csv|zip)$", re.I),
    "SDD": re.compile(r"^sdd.*\.xlsx?$", re.I),
    "TR_Metadata": re.compile(r"^tr_metadata.*\.xlsx?$", re.I),
}
GUIDE = re.compile(r"^csv.*guide.*\.pdf$", re.I)
# Older editions may publish the whole database as one archive.
FULL_DB_ARCHIVE = re.compile(r"full[ _%20-]*database.*\.zip$", re.I)

USER_AGENT = "Mozilla/5.0 (research data download; EBA transparency exercise)"
TIMEOUT = 120
RETRIES = 3
CHUNK = 1 << 20


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def request(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def fetch_html(url: str) -> str | None:
    for attempt in range(1, RETRIES + 1):
        try:
            with request(url) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == RETRIES:
                print(f"    page not reachable: {url} ({e})", file=sys.stderr)
                return None
            time.sleep(2 * attempt)
    return None


def file_name(url: str) -> str:
    return unquote(os.path.basename(urlparse(url).path))


def classify(name: str, with_guides: bool) -> str | None:
    for kind, pattern in KINDS.items():
        if pattern.match(name):
            return kind
    if FULL_DB_ARCHIVE.search(name):
        return "full_database_zip"
    if with_guides and GUIDE.match(name):
        return "guide"
    return None


def find_files(page_urls: list[str], with_guides: bool) -> list[dict]:
    """Links of the edition, de-duplicated by file name (first page that has them wins)."""
    found: dict[str, dict] = {}
    for page in page_urls:
        html = fetch_html(page)
        if not html:
            continue
        parser = LinkParser()
        parser.feed(html)
        for href in parser.links:
            url = urljoin(page, href.strip())
            name = file_name(url)
            kind = classify(name, with_guides)
            if kind and name not in found:
                found[name] = {"kind": kind, "name": name, "url": url, "page": page}
        if any(f["kind"] in KINDS for f in found.values()):
            break
    return sorted(found.values(), key=lambda f: (f["kind"], f["name"]))


def remote_size(url: str) -> int | None:
    try:
        with request(url, "HEAD") as r:
            value = r.headers.get("Content-Length")
            return int(value) if value else None
    except Exception:
        return None


def download(url: str, dest: Path, force: bool) -> tuple[str, int]:
    """Returns (status, bytes). Status: downloaded, skipped, failed: <reason>."""
    if dest.exists() and not force:
        size = remote_size(url)
        if size is None or size == dest.stat().st_size:
            return "skipped", dest.stat().st_size
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, RETRIES + 1):
        try:
            written = 0
            with request(url) as r, open(part, "wb") as out:
                total = int(r.headers.get("Content-Length") or 0)
                for chunk in iter(lambda: r.read(CHUNK), b""):
                    out.write(chunk)
                    written += len(chunk)
                    if total:
                        print(f"\r      {written / 1e6:7.1f} / {total / 1e6:.1f} MB", end="", flush=True)
            print("\r" + " " * 40 + "\r", end="")
            if total and written != total:
                raise IOError(f"incomplete: {written} of {total} bytes")
            os.replace(part, dest)
            return "downloaded", written
        except Exception as e:
            part.unlink(missing_ok=True)
            if attempt == RETRIES:
                return f"failed: {e}", 0
            time.sleep(3 * attempt)
    return "failed", 0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_zip(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        z.extractall(path.parent)
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download EBA transparency exercise databases")
    ap.add_argument("--out", default="eba_data", help="target folder (default: ./eba_data)")
    ap.add_argument("--years", type=int, nargs="+", help="editions to download (default: all)")
    ap.add_argument("--with-guides", action="store_true", help="also download the CSV guide PDFs")
    ap.add_argument("--extract", action="store_true", help="unzip downloaded .zip archives")
    ap.add_argument("--force", action="store_true", help="download again even if the file exists")
    ap.add_argument("--dry-run", action="store_true", help="only list the files that would be downloaded")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between downloads (default: 1)")
    a = ap.parse_args(argv)

    years = sorted(a.years or EDITIONS, reverse=True)
    unknown = [y for y in years if y not in EDITIONS]
    if unknown:
        print(f"unknown editions: {unknown}; known: {sorted(EDITIONS)}", file=sys.stderr)
        return 2

    out = Path(a.out)
    manifest: list[dict] = []
    summary: list[tuple[int, list[str], list[str]]] = []

    for year in years:
        print(f"[{year}] reading edition page")
        files = find_files(EDITIONS[year], a.with_guides)
        kinds = {f["kind"] for f in files}
        missing = [k for k in KINDS if k not in kinds]
        if "full_database_zip" in kinds:
            missing = []                      # the archive should contain them; check after extraction
        summary.append((year, sorted(kinds), missing))
        if not files:
            print("    no database files found on the page: download this edition manually")
            continue
        folder = out / str(year)
        for f in files:
            print(f"    {f['name']}")
            if a.dry_run:
                manifest.append({"year": year, **f, "status": "dry-run"})
                continue
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / f["name"]
            status, size = download(f["url"], dest, a.force)
            row = {"year": year, **f, "status": status, "bytes": size, "path": str(dest)}
            if status in ("downloaded", "skipped") and dest.exists():
                row["sha256"] = sha256(dest)
                if a.extract and dest.suffix.lower() == ".zip":
                    row["extracted"] = extract_zip(dest)
            if status.startswith("failed"):
                print(f"      {status}", file=sys.stderr)
            manifest.append(row)
            time.sleep(a.delay)

    if not a.dry_run:
        out.mkdir(parents=True, exist_ok=True)
        previous_path = out / "manifest.json"
        merged: dict[tuple, dict] = {}
        if previous_path.exists():                     # keep the rows of editions not downloaded in this run
            try:
                for row in json.loads(previous_path.read_text(encoding="utf-8")):
                    merged[(row["year"], row["name"])] = row
            except (ValueError, KeyError):
                pass
        for row in manifest:
            merged[(row["year"], row["name"])] = row
        rows = sorted(merged.values(), key=lambda r: (-r["year"], r["kind"], r["name"]))
        previous_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as fh:
            cols = ["year", "kind", "name", "status", "bytes", "sha256", "url", "path"]
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    print("\nSummary (needed per edition: " + ", ".join(KINDS) + ")")
    for year, kinds, missing in summary:
        state = "complete" if not missing and kinds else ("NOTHING FOUND" if not kinds else "missing: " + ", ".join(missing))
        print(f"  {year}: {state}")
    failed = [m for m in manifest if str(m.get("status", "")).startswith("failed")]
    if failed:
        print(f"\n{len(failed)} download(s) failed; run the script again to retry them.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())