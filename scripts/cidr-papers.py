#!/usr/bin/env python3
"""Harvest CIDR proceedings PDFs from the open cidrdb site.

CIDR is fully open. The modern proceedings site (``vldb.org/cidrdb/<year>/``,
the same tree as ``cidrdb.org``) lists every paper as a ``paper-card`` with
title, authors and a direct ``../papers/<year>/….pdf`` link. There is no
paywall and no OA resolver: a paper is public iff the listing links a PDF,
which they all do.

The seed page for this harvester is CIDR 2025's trampoline-style SQL paper
(https://vldb.org/cidrdb/2025/trampoline-style-queries-for-sql.html). The same
markup covers every year the new site still publishes (2019–2026). Older CIDR
volumes live under the ``www.cidrdb.org/cidrYYYY/`` layout and are out of
scope until someone wants them.

Pipeline (resumable via a JSON checkpoint — this is the paper backlog):

  1. gather   - parse each year's index into per-paper records, flag titles
                already in the search index.
  2. download - fetch every not-yet-indexed PDF into ``Inbox/cidr-papers/<year>/``.

    scripts/.venv/bin/python scripts/cidr-papers.py gather
    scripts/.venv/bin/python scripts/cidr-papers.py download
    scripts/.venv/bin/python scripts/cidr-papers.py all
    scripts/.venv/bin/python scripts/cidr-papers.py gather --years 2025
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "cidr-papers"
HTML_CACHE = OUT_DIR / "_html_cache"
CKPT = OUT_DIR / "_cidr-papers.json"
REPORT = OUT_DIR / "_cidr-papers-report.csv"
DL_SLEEP = 0.6

BASE = "https://vldb.org/cidrdb/"
# Years the Skeleton/paper-card site still serves. 2019 is the earliest index
# on vldb.org/cidrdb; 2026 is the current volume.
YEARS = list(range(2019, 2027))

CARD_RE = re.compile(
    r'<div class="paper-card">(.*?)</div>\s*(?:</div>|<div class="paper-card">)',
    re.S | re.I)
TITLE_RE = re.compile(r'<p class="title">(.*?)</p>', re.S | re.I)
AUTHORS_RE = re.compile(r'<p class="authors">(.*?)</p>', re.S | re.I)
PDF_RE = re.compile(r'href="([^"]+\.pdf)"', re.I)
PAGE_RE = re.compile(r'href="([^"]+\.html)"', re.I)


def parse_years(spec: str | None) -> list[int]:
    if not spec:
        return list(YEARS)
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    unknown = [y for y in out if y not in YEARS]
    if unknown:
        raise SystemExit(f"years not on cidrdb: {unknown} (have {YEARS[0]}–{YEARS[-1]})")
    return out


def fetch_index(year: int, force: bool = False) -> str:
    HTML_CACHE.mkdir(parents=True, exist_ok=True)
    cache = HTML_CACHE / f"{year}.html"
    if cache.exists() and cache.stat().st_size > 2000 and not force:
        return cache.read_text(encoding="utf-8")
    url = f"{BASE}{year}/"
    r = pf.requests.get(url, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    cache.write_text(r.text, encoding="utf-8")
    return r.text


def split_authors(raw: str) -> list[str]:
    txt = pf.clean(raw)
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r",?\s+and\s+", ", ", txt, flags=re.I)
    return [p.strip() for p in txt.split(",") if p.strip()]


def parse_year(year: int, html: str) -> list[dict]:
    page_url = f"{BASE}{year}/"
    # The regex above consumes up to the next card, so stitch a sentinel on.
    blob = html + '<div class="paper-card">'
    records: list[dict] = []
    seen = set()
    for m in CARD_RE.finditer(blob):
        body = m.group(1)
        tm = TITLE_RE.search(body)
        am = AUTHORS_RE.search(body)
        pm = PDF_RE.search(body)
        if not tm or not pm:
            continue
        title = pf.clean(tm.group(1))
        pdf_url = urljoin(page_url, pf.html.unescape(pm.group(1)))
        if pdf_url in seen:
            continue
        seen.add(pdf_url)
        page_m = PAGE_RE.search(body)
        records.append({
            "key": f"{year}:{Path(pdf_url).name}",
            "year": year,
            "title": title,
            "authors": split_authors(am.group(1) if am else ""),
            "pdf_url": pdf_url,
            "page_url": urljoin(page_url, page_m.group(1)) if page_m else page_url,
            "status": "pending",
            "in_index": None,
        })
    return records


def gather(years: list[int], dedup: bool) -> list[dict]:
    recs: list[dict] = []
    for year in years:
        html = fetch_index(year)
        year_recs = parse_year(year, html)
        print(f"  {year}: {len(year_recs)} papers "
              f"({sum(1 for r in year_recs if r['pdf_url'])} with a PDF)")
        recs.extend(year_recs)
    print(f"parsed {len(recs)} CIDR papers")
    if dedup:
        idx = pf.IndexDedup()
        for r in recs:
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in recs if r['in_index'])} already in the search index")
    recs.sort(key=lambda r: (-(r["year"] or 0), r["title"].lower()))
    return recs


def merge_ckpt(fresh: list[dict], existing: list[dict]) -> list[dict]:
    """Keep download status for keys we have already fetched."""
    old = {r["key"]: r for r in existing}
    out = []
    for r in fresh:
        prev = old.get(r["key"])
        if prev and prev.get("status") in ("downloaded", "dl_failed"):
            r["status"] = prev["status"]
        out.append(r)
    return out


def download(records: list[dict]) -> None:
    targets = [r for r in records
               if r.get("pdf_url") and not r.get("in_index")
               and r.get("status") not in ("downloaded",)]
    print(f"downloading {len(targets)} PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        dest = OUT_DIR / str(r["year"]) / (pf.safe_stem(r["authors"], r["title"]) + ".pdf")
        got, msg = pf.download_pdf(sess, r["pdf_url"], dest)
        if got:
            r["status"] = "downloaded"
            ok += 1
            print(f"[{i}/{len(targets)}] OK  {dest.name}  ({msg})")
        else:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:60]}  ({msg})")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "status", "in_index", "title", "authors", "pdf_url", "page_url"])
        for r in records:
            w.writerow([r.get("year") or "", r.get("status", ""), r.get("in_index"),
                        r["title"], "; ".join(r.get("authors", [])),
                        r.get("pdf_url") or "", r.get("page_url") or ""])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    st = Counter(r.get("status") for r in records)
    print("\n=== CIDR summary ===")
    print(f"  papers: {len(records)} | with PDF: {sum(1 for r in records if r.get('pdf_url'))}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}"
          f" | pending: {sum(1 for r in records if r.get('status') == 'pending')}"
          f" | downloaded: {sum(1 for r in records if r.get('status') == 'downloaded')}")
    print(f"  status: {dict(st)}")
    print(f"  backlog: {CKPT.relative_to(DOCS_ROOT)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="gather",
                   choices=["gather", "download", "all"])
    p.add_argument("--years", default=None,
                   help="comma/range list, e.g. 2025 or 2021-2026 (default: 2019-2026)")
    p.add_argument("--no-dedup", action="store_true",
                   help="do not skip papers already indexed")
    p.add_argument("--refresh-html", action="store_true",
                   help="re-fetch year index pages instead of using the cache")
    args = p.parse_args(argv)

    years = parse_years(args.years)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup
    if args.refresh_html:
        for y in years:
            cache = HTML_CACHE / f"{y}.html"
            if cache.exists():
                cache.unlink()

    if args.cmd == "gather":
        recs = gather(years, dedup)
        recs = merge_ckpt(recs, load_ckpt())
        save_ckpt(recs)
        print_summary(recs)
        return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr)
            return 2
        download(recs)
        print_summary(recs)
        return 0
    recs = load_ckpt()
    if not recs:
        recs = gather(years, dedup)
        save_ckpt(recs)
    download(recs)
    print_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
