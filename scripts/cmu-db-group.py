#!/usr/bin/env python3
"""Harvest the Carnegie Mellon Database Group publications and download the PDFs.

The listing (https://db.cs.cmu.edu/publications/) renders every paper as a

    <li class="... citation" id="<key>"> authors, &quot;Title,&quot; <em>venue</em>,
        ... YYYY.  <a href="....pdf" title="Download Document" class="bib-btn ...">
        <pre> @article{key, ... doi = {...}, url = {....pdf}, code = {...} }</pre>

so each entry carries a **direct, self-hosted PDF link** (the "PDF" download
button) plus a bibtex block. We parse those, skip papers already in the search
index, and download the rest into ``Inbox/cmu-db-group/<year>/``.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - parse the HTML into per-paper records (key/title/authors/year/
                venue/doi/pdf_url), flagging which titles the index already has.
  2. download - fetch every not-yet-indexed paper that exposes a PDF.

Usage:
  scripts/.venv/bin/python scripts/cmu-db-group.py all
  scripts/.venv/bin/python scripts/cmu-db-group.py gather|download
  scripts/.venv/bin/python scripts/cmu-db-group.py all --since 2015
  scripts/.venv/bin/python scripts/cmu-db-group.py all --no-dedup   # ignore the index
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
LIST_URL = "https://db.cs.cmu.edu/publications/"
OUT_DIR = DOCS_ROOT / "Inbox" / "cmu-db-group"
HTML_CACHE = OUT_DIR / "_page.html"
CKPT = OUT_DIR / "_cmu-db-group.json"
REPORT = OUT_DIR / "_cmu-db-group-report.csv"
DL_SLEEP = 0.6

# One <li ... class="...citation..." id="key"> ... </li> block per paper.
CITATION_RE = re.compile(
    r'<li[^>]*class="[^"]*\bcitation\b[^"]*"[^>]*id="(?P<key>[^"]+)"[^>]*>(?P<body>.*?)</li>',
    re.S | re.I)
PDF_HREF_RE = re.compile(r'href="(?P<url>[^"]+\.pdf)"[^>]*title="Download Document"', re.I)
TITLE_RE = re.compile(r'&quot;(?P<title>.*?),?&quot;', re.S)
BIB_DOI_RE = re.compile(r'doi\s*=\s*\{(?P<doi>10\.\d{4,9}/[^}]+)\}', re.I)
BIB_URL_RE = re.compile(r'url\s*=\s*\{(?P<url>https?://[^}]+)\}', re.I)
BIB_YEAR_RE = re.compile(r'year\s*=\s*\{?\s*((?:19|20)\d{2})', re.I)
MAX_YEAR = 2027


def fetch_page(force: bool = False) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if HTML_CACHE.exists() and HTML_CACHE.stat().st_size > 5000 and not force:
        return HTML_CACHE.read_text(encoding="utf-8")
    r = pf.requests.get(LIST_URL, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    HTML_CACHE.write_text(r.text, encoding="utf-8")
    return r.text


def parse_authors(prefix: str) -> list[str]:
    """Authors are the citation text before the first &quot; (the title)."""
    txt = pf.clean(prefix).rstrip(", ")
    txt = re.sub(r",?\s+and\s+", ", ", txt)
    out = []
    for p in txt.split(","):
        p = p.strip()
        if p and 1 <= len(p.split()) <= 5:
            out.append(p)
    return out


def parse(html: str) -> list[dict]:
    records: list[dict] = []
    for m in CITATION_RE.finditer(html):
        key, body = m.group("key"), m.group("body")
        tm = TITLE_RE.search(body)
        if not tm:
            continue
        title = pf.clean(tm.group("title")).rstrip(",")
        if not title:
            continue
        authors = parse_authors(body[: tm.start()])
        pdfm = PDF_HREF_RE.search(body)
        pdf_url = pf.html.unescape(pdfm.group("url")) if pdfm else None
        # Year: prefer the bibtex year, else the last year in the visible line.
        bib = body[body.find("<pre"):] if "<pre" in body else ""
        doim = BIB_DOI_RE.search(bib)
        if not pdf_url:
            um = BIB_URL_RE.search(bib)
            if um and um.group("url").lower().endswith(".pdf"):
                pdf_url = pf.html.unescape(um.group("url"))
        # Year: prefer the authoritative bibtex `year`, else the last *plausible*
        # 4-digit year in the visible citation line (avoids matching page numbers).
        year = None
        ym = BIB_YEAR_RE.search(bib)
        if ym:
            year = int(ym.group(1))
        else:
            visible = pf.clean(body[: body.find("<pre")] if "<pre" in body else body)
            plausible = [int(y) for y in re.findall(r"((?:19|20)\d{2})", visible)
                         if 1970 <= int(y) <= MAX_YEAR]
            year = plausible[-1] if plausible else None
        records.append({
            "key": key,
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doim.group("doi") if doim else None,
            "pdf_url": pdf_url,
            "status": "pending" if pdf_url else "no_pdf",
            "in_index": None,
        })
    # de-dup by citation key (page can repeat entries across sections).
    seen, uniq = set(), []
    for r in records:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        uniq.append(r)
    return uniq


def gather(since: int | None, dedup: bool) -> list[dict]:
    html = fetch_page()
    recs = parse(html)
    if since is not None:
        recs = [r for r in recs if (r["year"] or 0) >= since]
    print(f"parsed {len(recs)} CMU DB Group papers "
          f"({sum(1 for r in recs if r['pdf_url'])} with a PDF link)")
    if dedup:
        idx = pf.IndexDedup()
        for r in recs:
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in recs if r['in_index'])} already in the search index")
    recs.sort(key=lambda r: (-(r["year"] or 0), r["title"].lower()))
    return recs


def download(records: list[dict]) -> None:
    targets = [r for r in records
               if r.get("pdf_url") and not r.get("in_index")
               and r.get("status") not in ("downloaded",)]
    print(f"downloading {len(targets)} PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        year = r["year"] or "undated"
        dest = OUT_DIR / str(year) / (pf.safe_stem(r["authors"], r["title"]) + ".pdf")
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
    print("\n=== CMU DB Group summary ===")
    print(f"  papers: {len(records)} | with PDF: {sum(1 for r in records if r.get('pdf_url'))}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}"
          f" | downloaded: {sum(1 for r in records if r.get('status') == 'downloaded')}")
    print(f"  status: {dict(st)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all", choices=["gather", "download", "all"])
    p.add_argument("--since", type=int, default=None, help="only papers from this year onward")
    p.add_argument("--no-dedup", action="store_true", help="do not skip papers already indexed")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup
    if args.cmd == "gather":
        recs = gather(args.since, dedup); save_ckpt(recs); print_summary(recs); return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr); return 2
        download(recs); print_summary(recs); return 0
    recs = load_ckpt()
    if not recs:
        recs = gather(args.since, dedup); save_ckpt(recs)
    download(recs); print_summary(recs); return 0


if __name__ == "__main__":
    raise SystemExit(main())
