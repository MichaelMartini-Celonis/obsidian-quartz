#!/usr/bin/env python3
"""Harvest the "Author's Version" PDFs from the publications page of the TUM
Chair of Information Systems and Business Process Management (Rinderle-Ma).

The page (https://www.cs.cit.tum.de/bpm/publications/) lists publications
grouped under ``<h3 id="YYYY">`` year headers, each entry a ``<dd>`` block:

    <dt>[1]</dt>
    <dd>
      <authors>, "<title>," in <venue>, ..., YYYY, ..., doi: <doi>.
      Author's Version [<a href="https://i17vm1.in.tum.de/zotero/XXXX.pdf">PDF</a>]
    </dd>

Only entries that expose an "Author's Version [PDF]" carry a directly
downloadable copy on the chair's Zotero host; those are the ones we fetch.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - parse the publications HTML into per-entry records
                (year / authors / title / doi / pdf_url).
  2. download - fetch every entry that has a pdf_url into
                Inbox/tum-bpm/<year>/ as "<Author et al> - <Title>.pdf".

Usage:
  scripts/.venv/bin/python scripts/tum-bpm.py all
  scripts/.venv/bin/python scripts/tum-bpm.py gather|download
  scripts/.venv/bin/python scripts/tum-bpm.py all --since 2018
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

DOCS_ROOT = Path(__file__).resolve().parent.parent
LIST_URL = "https://www.cs.cit.tum.de/bpm/publications/"
OUT_DIR = DOCS_ROOT / "Inbox" / "tum-bpm"
HTML_CACHE = OUT_DIR / "_page.html"
CKPT = OUT_DIR / "_tum-bpm.json"
REPORT = OUT_DIR / "_tum-bpm-report.csv"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
DL_SLEEP = 0.5


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def fetch_page(force: bool = False) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if HTML_CACHE.exists() and HTML_CACHE.stat().st_size > 5000 and not force:
        return HTML_CACHE.read_text(encoding="utf-8")
    r = requests.get(LIST_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    HTML_CACHE.write_text(r.text, encoding="utf-8")
    return r.text


# ---------------------------------------------------------------------------
# 1. gather
# ---------------------------------------------------------------------------

# Year section headers: <h3 id="2026">2026 ...</h3>
SECTION_RE = re.compile(r'<h3\s+id="(?P<year>\d{4})"', re.I)
DD_RE = re.compile(r"<dd\b[^>]*>(?P<body>.*?)</dd>", re.S | re.I)
PDF_RE = re.compile(r'href="(?P<url>[^"]+\.pdf)"', re.I)
DOI_RE = re.compile(r"doi:\s*(?P<doi>10\.\d{4,9}/[^\s,<\"]+)", re.I)
# Title is wrapped in typographic double quotes (U+201C ... U+201D).
TITLE_RE = re.compile(r"\u201c(?P<title>.*?)[\.,]?\u201d", re.S)


def parse_authors(prefix: str) -> list[str]:
    prefix = clean(prefix).rstrip(", ")
    if not prefix:
        return []
    parts = [p.strip() for p in re.split(r",|\band\b", prefix)]
    out = []
    for p in parts:
        p = p.strip()
        # authors look like "Firstname ... Lastname"; drop stray fragments
        if p and 1 <= len(p.split()) <= 6 and not p.lower().startswith(("in ", "vol", "pp")):
            out.append(p)
    return out


def safe_name(rec: dict) -> str:
    authors = rec.get("authors") or []
    if authors:
        last = authors[0].split()[-1] if authors[0].split() else "Unknown"
    else:
        last = "Unknown"
    extra = " et al" if len(authors) > 1 else ""
    stem = f"{last}{extra} - {rec['title']}"
    stem = re.sub(r"[^\w.\-() ]+", "_", stem)[:180].strip()
    return f"{stem}.pdf"


def gather(since: int | None = None) -> list[dict]:
    page = fetch_page()

    # Split the document into (year -> html slice) using the <h3 id> markers.
    marks = [(m.start(), m.group("year")) for m in SECTION_RE.finditer(page)]
    records: list[dict] = []
    for idx, (start, year) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(page)
        section = page[start:end]
        y = int(year)
        if since is not None and y < since:
            continue
        for dm in DD_RE.finditer(section):
            body = dm.group("body")
            tm = TITLE_RE.search(body)
            if not tm:
                continue
            title = clean(tm.group("title"))
            if not title:
                continue
            authors = parse_authors(body[: tm.start()])
            pm = PDF_RE.search(body)
            doim = DOI_RE.search(clean(body))
            records.append({
                "year": y,
                "title": title,
                "authors": authors,
                "doi": doim.group("doi") if doim else None,
                "pdf_url": pm.group("url") if pm else None,
                "status": "pending" if pm else "no_pdf",
            })

    # de-dup by (year, lowercased title), keeping the first (prefers a pdf_url
    # because entries with PDFs are listed the same as those without).
    seen, uniq = set(), []
    for r in sorted(records, key=lambda r: (r["pdf_url"] is None)):
        key = (r["year"], r["title"].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    uniq.sort(key=lambda r: (-r["year"], r["title"].lower()))
    return uniq


# ---------------------------------------------------------------------------
# 2. download
# ---------------------------------------------------------------------------

def download(records: list[dict]) -> None:
    targets = [r for r in records if r.get("pdf_url")]
    print(f"downloading {len(targets)} author-version PDFs...")
    session = requests.Session()
    ok = fail = skip = 0
    for i, r in enumerate(targets, 1):
        dest_dir = OUT_DIR / str(r["year"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name(r)
        if dest.exists() and dest.stat().st_size > 2000:
            r["status"] = "downloaded"
            skip += 1
            continue
        try:
            resp = session.get(r["pdf_url"], headers=HEADERS, timeout=90, allow_redirects=True)
            data = resp.content
        except Exception as exc:  # noqa: BLE001
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(targets)}] -- {type(exc).__name__}: {str(exc)[:70]}")
            continue
        if resp.status_code == 200 and data[:5].startswith(b"%PDF") and len(data) > 2000:
            dest.write_bytes(data)
            r["status"] = "downloaded"
            ok += 1
            print(f"[{i}/{len(targets)}] OK  {dest.name}  ({len(data)//1024} KB)")
        else:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(targets)}] -- HTTP {resp.status_code}, {len(data)} bytes  {r['title'][:50]}")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, skipped(existing) {skip}, failed {fail} ===")


# ---------------------------------------------------------------------------
# checkpoint / report / summary
# ---------------------------------------------------------------------------

def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "status", "title", "authors", "doi", "pdf_url"])
        for r in records:
            w.writerow([r["year"], r.get("status", ""), r["title"],
                        "; ".join(r.get("authors", [])), r.get("doi") or "",
                        r.get("pdf_url") or ""])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    with_pdf = sum(1 for r in records if r.get("pdf_url"))
    dl = sum(1 for r in records if r.get("status") == "downloaded")
    print("\n=== TUM BPM summary ===")
    print(f"  entries: {len(records)} | with author-version PDF: {with_pdf} | downloaded: {dl}")
    print(f"  status: {dict(st)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", nargs="?", default="all", choices=["gather", "download", "all"])
    p.add_argument("--since", type=int, default=None,
                   help="only harvest publications from this year onward")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "gather":
        recs = gather(args.since); save_ckpt(recs); print_summary(recs); return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr); return 2
        download(recs); print_summary(recs); return 0
    # all
    recs = load_ckpt()
    if not recs:
        recs = gather(args.since); save_ckpt(recs)
    download(recs); print_summary(recs); return 0


if __name__ == "__main__":
    raise SystemExit(main())
