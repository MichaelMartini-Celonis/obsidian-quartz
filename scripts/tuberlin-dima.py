#!/usr/bin/env python3
"""Harvest the TU Berlin DIMA (Database Systems and Information Management,
Volker Markl's group) publication list and download the author-version PDFs.

Source: https://www.tu.berlin/dima/forschung/publikationen

The page is rendered by the TYPO3 ``tx_publications`` plugin: 25 publications
per page across ~15 pages. Each publication is an

    <div class="item" data-publications-record="NNN">
      <div class="citation-content"> Surname, Given; ... <i>Title</i>
        venue, pages ... YEAR
        <dl>..<dt>DOI</dt>..<dt>Datei</dt>
           <span class="link-pdf-img"><img..><a href="...pdf"> ...

so most entries carry a **direct, self-hosted PDF link** (the "Datei" download)
plus a DOI. We crawl every page by following the ``<li class="next">`` link
(each page URL carries its own ``cHash``), parse the entries, skip papers already
in the search index, and download the rest into ``Inbox/tuberlin-dima/<year>/``.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - crawl all pages into per-paper records (id/title/authors/year/
                venue/doi/pdf_url), flagging which titles the index already has.
  2. download - fetch every not-yet-indexed paper that exposes a PDF.

Usage:
  scripts/.venv/bin/python scripts/tuberlin-dima.py all
  scripts/.venv/bin/python scripts/tuberlin-dima.py gather|download
  scripts/.venv/bin/python scripts/tuberlin-dima.py all --since 2018
  scripts/.venv/bin/python scripts/tuberlin-dima.py all --no-dedup
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.tu.berlin"
LIST_URL = "https://www.tu.berlin/dima/forschung/publikationen"
OUT_DIR = DOCS_ROOT / "Inbox" / "tuberlin-dima"
CKPT = OUT_DIR / "_tuberlin-dima.json"
REPORT = OUT_DIR / "_tuberlin-dima-report.csv"
PAGE_SLEEP = 0.8
DL_SLEEP = 0.6
MAX_YEAR = 2027

RECORD_RE = re.compile(r'data-publications-record="(?P<id>\d+)"')
NEXT_RE = re.compile(r'<li class="next"><a href="(?P<href>[^"]+)"')
TITLE_RE = re.compile(r"<i>(?P<title>.*?)</i>", re.S)
DOI_RE = re.compile(r'href="https?://(?:dx\.)?doi\.org/(?P<doi>10\.\d{4,9}/[^"]+)"', re.I)
PDF_RE = re.compile(r'href="(?P<url>https?://[^"]+\.pdf)"', re.I)
YEAR_RE = re.compile(r"<br\s*/?>\s*((?:19|20)\d{2})\b")


def fetch(url: str) -> str:
    r = pf.requests.get(url, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def item_chunks(html: str) -> list[str]:
    """Split a page's HTML into one chunk per publication ``item`` div."""
    starts = [m.start() for m in RECORD_RE.finditer(html)]
    if not starts:
        return []
    # stop the last chunk at the pagination nav so trailing markup isn't parsed.
    end = html.find('class="pagination"', starts[-1])
    if end < 0:
        end = len(html)
    bounds = starts + [end]
    return [html[bounds[i]:bounds[i + 1]] for i in range(len(starts))]


def parse_authors(prefix: str) -> list[str]:
    """Authors precede the title <i>; formatted 'Surname,\n Given;' -> 'Given Surname'."""
    txt = pf.clean(prefix)
    out = []
    for piece in txt.split(";"):
        piece = piece.strip().rstrip(",").strip()
        if not piece:
            continue
        if "," in piece:
            last, _, given = piece.partition(",")
            name = f"{given.strip()} {last.strip()}".strip()
        else:
            name = piece
        if name and 1 <= len(name.split()) <= 5 and re.search(r"[A-Za-z]", name):
            out.append(name)
    return out[:12]


def parse_chunk(chunk: str) -> dict | None:
    rid = RECORD_RE.search(chunk)
    tm = TITLE_RE.search(chunk)
    if not tm:
        return None
    title = pf.clean(tm.group("title")).rstrip(".")
    if len(pf.norm(title)) < 6:
        return None
    authors = parse_authors(chunk[: tm.start()])
    doim = DOI_RE.search(chunk)
    pdfm = PDF_RE.search(chunk)
    years = [int(y) for y in YEAR_RE.findall(chunk) if 1970 <= int(y) <= MAX_YEAR]
    return {
        "id": rid.group("id") if rid else None,
        "title": title,
        "authors": authors,
        "year": years[-1] if years else None,
        "doi": doim.group("doi") if doim else None,
        "pdf_url": pf.html.unescape(pdfm.group("url")) if pdfm else None,
        "status": "pending" if pdfm else "no_pdf",
        "in_index": None,
    }


def gather(since: int | None, dedup: bool, max_pages: int) -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    url, page, records, seen = LIST_URL, 0, [], set()
    while url and page < max_pages:
        page += 1
        html = fetch(url)
        chunks = item_chunks(html)
        for ch in chunks:
            r = parse_chunk(ch)
            if not r:
                continue
            key = r["id"] or pf.norm(r["title"])
            if key in seen:
                continue
            seen.add(key)
            records.append(r)
        print(f"  page {page}: +{len(chunks)} items (total {len(records)})")
        nm = NEXT_RE.search(html)
        url = urljoin(BASE, pf.html.unescape(nm.group("href"))) if nm else None
        time.sleep(PAGE_SLEEP)
    if since is not None:
        records = [r for r in records if (r["year"] or 0) >= since]
    print(f"parsed {len(records)} DIMA publications "
          f"({sum(1 for r in records if r['pdf_url'])} with a PDF link)")
    if dedup:
        idx = pf.IndexDedup()
        for r in records:
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in records if r['in_index'])} already in the search index")
    records.sort(key=lambda r: (-(r["year"] or 0), r["title"].lower()))
    return records


def download(records: list[dict]) -> None:
    targets = [r for r in records if r.get("pdf_url") and not r.get("in_index")
               and r.get("status") not in ("downloaded",)]
    print(f"downloading {len(targets)} PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        year = r["year"] or "undated"
        dest = OUT_DIR / str(year) / (pf.safe_stem(r["authors"], r["title"]) + ".pdf")
        got, msg = pf.download_pdf(sess, r["pdf_url"], dest)
        if got:
            r["status"], ok = "downloaded", ok + 1
            r["saved_as"] = str(dest.relative_to(OUT_DIR))
            print(f"[{i}/{len(targets)}] OK  {dest.name}  ({msg})")
        else:
            r["status"], fail = "dl_failed", fail + 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:60]}  ({msg})")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


def prune_indexed(records: list[dict]) -> None:
    """Delete downloaded PDFs whose title is already in the search index.

    Lets ``download`` run while the index is busy (locked): dedup is deferred to
    here, once the DB is readable again. Idempotent.
    """
    idx = pf.IndexDedup()
    if not idx.available:
        print("  index unreadable; nothing pruned"); return
    removed = 0
    for r in records:
        if idx.contains(r["title"]):
            r["in_index"] = True
            sa = r.get("saved_as")
            if sa:
                f = OUT_DIR / sa
                if f.exists():
                    f.unlink(); removed += 1
                r["saved_as"] = None
            if r.get("status") == "downloaded":
                r["status"] = "in_index"
    save_ckpt(records)
    print(f"  pruned {removed} already-indexed PDFs from {OUT_DIR}")


def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "status", "in_index", "title", "authors", "doi", "pdf_url"])
        for r in records:
            w.writerow([r.get("year") or "", r.get("status", ""), r.get("in_index"),
                        r["title"], "; ".join(r.get("authors", [])),
                        r.get("doi") or "", r.get("pdf_url") or ""])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    print("\n=== TU Berlin DIMA summary ===")
    print(f"  papers: {len(records)} | with PDF: {sum(1 for r in records if r.get('pdf_url'))}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}"
          f" | downloaded: {sum(1 for r in records if r.get('status') == 'downloaded')}")
    print(f"  status: {dict(st)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "download", "prune-indexed", "all"])
    p.add_argument("--since", type=int, default=None, help="only papers from this year onward")
    p.add_argument("--max-pages", type=int, default=25, help="pagination safety cap")
    p.add_argument("--no-dedup", action="store_true", help="do not skip papers already indexed")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup
    if args.cmd == "gather":
        recs = gather(args.since, dedup, args.max_pages)
        save_ckpt(recs); print_summary(recs); return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr); return 2
        download(recs); print_summary(recs); return 0
    if args.cmd == "prune-indexed":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr); return 2
        prune_indexed(recs); print_summary(recs); return 0
    recs = load_ckpt()
    if not recs:
        recs = gather(args.since, dedup, args.max_pages); save_ckpt(recs)
    download(recs); print_summary(recs); return 0


if __name__ == "__main__":
    raise SystemExit(main())
