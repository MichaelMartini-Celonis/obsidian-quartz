#!/usr/bin/env python3
"""Harvest the PDF paper collections that CMU course pages expose as open
Apache directory listings, e.g.

    https://www.cs.cmu.edu/~natassa/courses/15-721/papers/

Those ``~user/courses/.../papers/`` folders are classic **advanced-databases
reading lists** (Ailamaki's 15-721, etc.). They are served as plain Apache
"Index of ..." autoindex pages, so every ``*.pdf`` / ``*.PDF`` is directly and
legally fetchable. The catch is the filenames are cryptic (``p297-o_neil.pdf``,
``GrayLocks.pdf``, ``ARC.pdf``) - the ``p<page>-<author>.pdf`` ones follow the
old ACM Digital Library naming (article start-page + first-author surname).

Because the filenames carry no reliable title, we download first, then read the
PDF's own first page to get a title and **drop anything the search index already
has** (unless ``--no-dedup``). Whatever remains lands in
``Inbox/cmu-course-papers/<label>/`` where ``import-downloads.py`` renames it to
``Author - Title.pdf`` from the extracted bibliography and content-hash
de-duplicates against the library as a backstop.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - crawl the autoindex page(s) for all PDF URLs.
  2. download - fetch each PDF (skip already-fetched), then index-dedup.

Usage:
  scripts/.venv/bin/python scripts/cmu-course-papers.py all
  scripts/.venv/bin/python scripts/cmu-course-papers.py gather|download
  scripts/.venv/bin/python scripts/cmu-course-papers.py all \
      --url https://www.cs.cmu.edu/~natassa/courses/15-721/papers/
  scripts/.venv/bin/python scripts/cmu-course-papers.py all --no-dedup
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "cmu-course-papers"
CKPT = OUT_DIR / "_cmu-course-papers.json"
REPORT = OUT_DIR / "_cmu-course-papers-report.csv"
DL_SLEEP = 0.5

# Default sources: CMU course "papers/" autoindex directories.
DEFAULT_URLS = [
    "https://www.cs.cmu.edu/~natassa/courses/15-721/papers/",
]

HREF_RE = re.compile(r'<a\s+href="([^"?][^"]*)"', re.I)


def label_for(url: str) -> str:
    """A short folder label derived from the directory URL."""
    path = urlparse(url).path
    m = re.search(r"~([^/]+)/courses/([^/]+)", path)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    parts = [p for p in path.split("/") if p and p != "papers"]
    return re.sub(r"[^\w.\-]+", "-", "-".join(parts[-2:]) or "course")


def crawl(url: str, sess: requests.Session, seen_dirs: set[str],
          depth: int = 0) -> list[str]:
    """Return all PDF URLs found under an Apache autoindex directory."""
    if depth > 2 or url in seen_dirs:
        return []
    seen_dirs.add(url)
    try:
        r = sess.get(url, timeout=45)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {url}: {type(exc).__name__}")
        return []
    pdfs: list[str] = []
    for href in HREF_RE.findall(r.text):
        if href.startswith(("/", "?", "#")) or "://" in href and not href.startswith(url):
            # skip sort links, parent dir, and off-directory links
            if not href.lower().endswith((".pdf", "/")):
                continue
        low = href.lower()
        full = urljoin(url, href)
        if low.endswith(".pdf"):
            pdfs.append(full)
        elif href.endswith("/") and full.startswith(url) and full != url:
            pdfs.extend(crawl(full, sess, seen_dirs, depth + 1))
    return pdfs


def gather(urls: list[str]) -> list[dict]:
    sess = pf.session()
    records: list[dict] = []
    seen_url: set[str] = set()
    for url in urls:
        label = label_for(url)
        found = crawl(url, sess, set())
        n = 0
        for pdf_url in found:
            if pdf_url in seen_url:
                continue
            seen_url.add(pdf_url)
            records.append({
                "label": label,
                "pdf_url": pdf_url,
                "filename": Path(urlparse(pdf_url).path).name,
                "title": None,
                "in_index": None,
                "status": "pending",
            })
            n += 1
        print(f"  {label}: {n} PDFs at {url}")
    print(f"parsed {len(records)} PDF links across {len(urls)} directory(ies)")
    return records


def _extract_title(path: Path) -> str | None:
    """Best-effort title from PDF metadata / first non-boilerplate line."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        meta = reader.metadata
        if meta and meta.title:
            t = pf.clean(str(meta.title))
            if len(t) >= 8 and "untitled" not in t.lower():
                return t
        text = reader.pages[0].extract_text() or "" if reader.pages else ""
        for line in (pf.clean(l) for l in text.splitlines()):
            if len(line.split()) >= 3 and not re.search(r"@|\.edu|proceedings|copyright", line, re.I):
                return line
    except Exception:  # noqa: BLE001
        return None
    return None


def unique_dest(directory: Path, filename: str) -> Path:
    """A destination path unique *case-insensitively* (macOS/APFS is case-
    insensitive, so ``P047.PDF`` and ``p047.pdf`` would otherwise clobber each
    other and silently lose a distinct paper)."""
    directory.mkdir(parents=True, exist_ok=True)
    existing = {p.name.lower() for p in directory.iterdir()}
    stem, suffix = Path(filename).stem, Path(filename).suffix
    cand, n = filename, 2
    while cand.lower() in existing:
        cand = f"{stem}_{n}{suffix}"
        n += 1
    return directory / cand


def download(records: list[dict], dedup: bool) -> None:
    todo = [r for r in records if r.get("status") not in ("downloaded", "in_index")]
    print(f"downloading {len(todo)} PDFs -> {OUT_DIR}")
    idx = pf.IndexDedup() if dedup else None
    sess = pf.session()
    ok = fail = deduped = 0
    for i, r in enumerate(todo, 1):
        dest = unique_dest(OUT_DIR / r["label"], r["filename"])
        got, msg = pf.download_pdf(sess, r["pdf_url"], dest)
        if not got:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(todo)}] --  {r['filename']}  ({msg})")
            time.sleep(DL_SLEEP)
            continue
        r["saved_as"] = dest.name
        title = _extract_title(dest)
        r["title"] = title
        if idx and title and idx.contains(title):
            dest.unlink(missing_ok=True)
            r["in_index"] = True
            r["status"] = "in_index"
            deduped += 1
            print(f"[{i}/{len(todo)}] SKIP (in index) {r['filename']}  -> {title[:50]}")
        else:
            r["in_index"] = False
            r["status"] = "downloaded"
            ok += 1
            print(f"[{i}/{len(todo)}] OK  {r['filename']}  ({msg})"
                  + (f"  [{title[:45]}]" if title else ""))
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, in-index skipped {deduped}, failed {fail} ===")


def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["label", "status", "in_index", "filename", "title", "pdf_url"])
        for r in records:
            w.writerow([r.get("label", ""), r.get("status", ""), r.get("in_index"),
                        r.get("filename", ""), r.get("title") or "", r.get("pdf_url", "")])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    print("\n=== CMU course papers summary ===")
    print(f"  PDFs: {len(records)} | downloaded: {sum(1 for r in records if r.get('status') == 'downloaded')}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}")
    print(f"  status: {dict(st)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all", choices=["gather", "download", "all"])
    p.add_argument("--url", action="append", help="autoindex directory URL (repeatable)")
    p.add_argument("--no-dedup", action="store_true", help="keep PDFs even if already indexed")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    urls = args.url or DEFAULT_URLS
    dedup = not args.no_dedup
    if args.cmd == "gather":
        recs = gather(urls); save_ckpt(recs); print_summary(recs); return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr); return 2
        download(recs, dedup); print_summary(recs); return 0
    recs = load_ckpt()
    if not recs:
        recs = gather(urls); save_ckpt(recs)
    download(recs, dedup); print_summary(recs); return 0


if __name__ == "__main__":
    raise SystemExit(main())
