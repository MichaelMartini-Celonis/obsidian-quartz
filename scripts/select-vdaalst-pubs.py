#!/usr/bin/env python3
"""Parse van der Aalst's publications page and select papers worth importing.

Selection = union of:
  * recent papers (year >= --since, default 2022),
  * journal articles (any year),
  * award / best-paper highlighted entries (any year).

Excluded: theses, technical reports / working papers, and editorials / edited
proceedings / prefaces (i.e. "papers without content"). Very short PDFs are
dropped later, after download, by scripts/fetch-papers.py + a page-count filter.

Writes the selected PDF URLs to imports/vdaalst-selected.txt and prints stats.

    scripts/.venv/bin/python scripts/select-vdaalst-pubs.py --since 2022
"""

from __future__ import annotations

import argparse
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

PUBS_URL = "https://www.vdaalst.com/publications/publications.html"
OUT = Path("imports/vdaalst-selected.txt")
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")}

AWARD_RE = re.compile(r"best[ -]?paper|best student paper|distinguished paper|"
                      r"test[ -]of[ -]time|outstanding paper|award", re.I)

# Curated journal titles for this author. Matched only when the entry is NOT a
# "Proceedings" (conference) entry, so conference names that merely contain a
# word like "Information Systems" don't get miscounted as journals.
JOURNAL_RE = re.compile(
    r"IEEE Transactions|ACM Transactions|VLDB Journal|SIGMOD Record|"
    r"ACM Computing Surveys|Journal of |International Journal of |"
    r"\bInformation Systems\b|Data (?:and|&) Knowledge Engineering|"
    r"Distributed and Parallel Databases|Fundamenta Informaticae|"
    r"Computers in Industry|Decision Support Systems|"
    r"Software and Systems Modeling|Formal Aspects of Computing|"
    r"Business (?:and|&) Information Systems Engineering|"
    r"Knowledge and Information Systems|"
    r"Computer Supported Cooperative Work|Real-Time Systems|"
    r"Expert Systems with Applications|Applied Intelligence",
    re.I)

# Entries that carry no real paper content. NOTE: do *not* match a bare
# "editors," — conference citations read "In A and B, editors, Proceedings ...".
# Author-as-editor (an edited volume) is caught via the parenthetical "(Eds.)".
EXCLUDE_RE = re.compile(
    r"PhD thesis|Master'?s thesis|Master Thesis|Computing Science Notes|"
    r"Technical Report|BETA (?:Working Paper|report)|Working Paper|"
    r"\(\s*eds?\.?\s*\)|Preface|Editorial|book review|Habilitation|"
    r"Dagstuhl Reports|\bposter\b|Tool (?:Demonstration|Demo)|"
    r"Extended Abstract|Abstract of",
    re.I)


def strip_tags(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", s))


def parse_entries(html: str) -> list[dict]:
    # Split into per-entry chunks at each <dt>NUMBER</dt>.
    parts = re.split(r"<dt>\s*(\w+)\s*</dt>", html)
    entries = []
    # parts = [pre, id1, body1, id2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        eid, body = parts[i], parts[i + 1]
        m = re.search(r'href=["\']([^"\']+\.pdf)["\']', body, re.I)
        if not m:
            continue
        text = re.sub(r"\s+", " ", strip_tags(body)).strip()
        years = re.findall(r"\b(19|20)\d{2}\b", body)
        year = max(int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", body)) if years else None
        entries.append({
            "id": eid,
            "pdf": urljoin(PUBS_URL, m.group(1)),
            "text": text,
            "year": year,
            "award": bool(AWARD_RE.search(text)),
            "journal": bool(JOURNAL_RE.search(text)) and not re.search(r"proceedings", text, re.I),
            "exclude": bool(EXCLUDE_RE.search(text)),
        })
    return entries


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", type=int, default=2022, help="recent cutoff year (inclusive)")
    args = p.parse_args(argv)

    html = requests.get(PUBS_URL, headers=HEADERS, timeout=60).text
    entries = parse_entries(html)

    selected, reasons = [], {}
    for e in entries:
        if e["exclude"]:
            continue
        why = []
        if e["year"] and e["year"] >= args.since:
            why.append("recent")
        if e["journal"]:
            why.append("journal")
        if e["award"]:
            why.append("award")
        if why:
            selected.append(e)
            reasons[e["pdf"]] = "+".join(why)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(e["pdf"] for e in selected) + "\n", encoding="utf-8")

    from collections import Counter
    cat = Counter(reasons.values())
    print(f"parsed entries with PDFs: {len(entries)}")
    print(f"excluded (thesis/report/editorial): {sum(1 for e in entries if e['exclude'])}")
    print(f"selected: {len(selected)}  -> {OUT}")
    for k, v in sorted(cat.items(), key=lambda x: -x[1]):
        print(f"    {v:4d}  {k}")
    print(f"  journals total: {sum(1 for e in selected if e['journal'])}")
    print(f"  awards total:   {sum(1 for e in selected if e['award'])}")
    yrs = Counter(e['year'] for e in selected if e['year'])
    print("  by year:", dict(sorted(((y, n) for y, n in yrs.items()), reverse=True)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
