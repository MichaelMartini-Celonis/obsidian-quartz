#!/usr/bin/env python3
"""Best-effort PDF harvester for Xin Luna Dong's classic database reading list.

Source (Wayback snapshot, since the live page moves):

    https://web.archive.org/web/20250419115646/https://lunadong.com/resources

The page is a big nested reading list: ``<h2>/<h3>/<h4>`` section headers, then
``<li>`` items shaped like

    E.F. Codd.  <i>A Relational Model of Data ...</i>.  CACM 13(6), 1970,
    pp. 377-387.  (<i>Must read.</i>)

i.e. **citations only, no download links**. So for each citation we parse
author / title / venue / year / start-page, skip anything already in the search
index, and then try to *resolve* a freely downloadable PDF in this order:

  1. CMU course-papers catalog - the ``~natassa/courses/15-721/papers/`` autoindex
     names ACM papers ``p<startpage>-<surname>.pdf``, so a (first-author surname,
     start-page) match yields a direct, legal CMU URL. (This is the "good way to
     access the CMU URLs" - see also scripts/cmu-course-papers.py.)
  2. DBLP title search  -> confirmed hit's electronic-edition (arXiv / open PDF).
  3. Unpaywall          -> open-access PDF for the DBLP DOI.
  4. arXiv title search  -> preprint, confirmed by title ratio + author surname.

Many entries are 1970s-2000s ACM/VLDB papers with no open copy; those are
reported as ``unresolved`` so you know what still needs a manual drop into
``Inbox/``. Downloads land in ``Inbox/lunadong/<section>/``.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - parse the reading list; flag titles already in the index.
  2. resolve  - find a downloadable PDF URL for each not-yet-indexed citation.
  3. download - fetch the resolved PDFs.

Usage:
  scripts/.venv/bin/python scripts/lunadong-reading-list.py all
  scripts/.venv/bin/python scripts/lunadong-reading-list.py gather
  scripts/.venv/bin/python scripts/lunadong-reading-list.py resolve --limit 40
  scripts/.venv/bin/python scripts/lunadong-reading-list.py download
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = "https://web.archive.org/web/20250419115646/https://lunadong.com/resources"
OUT_DIR = DOCS_ROOT / "Inbox" / "lunadong"
HTML_CACHE = OUT_DIR / "_page.html"
CKPT = OUT_DIR / "_lunadong.json"
REPORT = OUT_DIR / "_lunadong-report.csv"
CMU_COURSE_URL = "https://www.cs.cmu.edu/~natassa/courses/15-721/papers/"
RESOLVE_SLEEP = 0.3
DL_SLEEP = 0.6


# ---------------------------------------------------------------------------
# 1. gather - parse the reading list
# ---------------------------------------------------------------------------

class ReadingListParser(HTMLParser):
    """Collect (section, authors_text, title, trailer) per citation <li>.

    A citation <li> is one whose *first* <i> span is its title. Category <li>
    (bold labels wrapping a nested <ul>) carry no <i> and are ignored. Nested
    lists are handled with a per-<li> stack so the inner citation is captured,
    not the outer wrapper.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.section = "General"
        self._in_header = 0
        self._header_buf: list[str] = []
        self._li_stack: list[dict] = []
        self._in_italic = False
        self.records: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3", "h4"):
            self._in_header += 1
            self._header_buf = []
        elif tag == "li":
            self._li_stack.append({"before": [], "title": [], "after": [],
                                   "seen_italic": False})
        elif tag in ("i", "em"):
            self._in_italic = True

    def handle_endtag(self, tag):
        if tag in ("h2", "h3", "h4"):
            if self._in_header:
                self._in_header -= 1
            text = pf.clean("".join(self._header_buf))
            if text:
                self.section = text
        elif tag in ("i", "em"):
            self._in_italic = False
            if self._li_stack:
                self._li_stack[-1]["seen_italic"] = True
        elif tag == "li":
            if self._li_stack:
                li = self._li_stack.pop()
                title = pf.clean("".join(li["title"]))
                if len(title) >= 8:
                    self.records.append({
                        "section": self.section,
                        "authors_text": pf.clean("".join(li["before"])),
                        "title": title,
                        "trailer": pf.clean("".join(li["after"])),
                    })

    def handle_data(self, data):
        if self._in_header:
            self._header_buf.append(data)
            return
        if not self._li_stack:
            return
        li = self._li_stack[-1]
        if self._in_italic and not li["seen_italic"]:
            li["title"].append(data)
        elif li["seen_italic"]:
            li["after"].append(data)
        else:
            li["before"].append(data)


def parse_authors(text: str) -> list[str]:
    text = pf.clean(text).rstrip(" .,:")
    # Drop a leading annotation label like "Sort-of-survey:" / "First paper:".
    text = re.sub(r"^[A-Za-z][\w '\-]{0,30}:\s*", "", text)
    text = re.sub(r",?\s+and\s+", ", ", text)
    out = []
    for p in re.split(r",|;", text):
        p = p.strip().rstrip(".")
        # authors look like "F. Lastname" / "Firstname Lastname"; drop fragments
        if p and 1 <= len(p.split()) <= 5 and re.search(r"[A-Za-z]", p):
            out.append(p)
    return out[:10]


def parse_year(trailer: str) -> int | None:
    yrs = [int(y) for y in re.findall(r"((?:19|20)\d{2})", trailer) if 1960 <= int(y) <= 2026]
    return yrs[-1] if yrs else None


def parse_startpage(trailer: str) -> int | None:
    m = re.search(r"pp?\.\s*(\d{1,4})", trailer)
    return int(m.group(1)) if m else None


def gather(dedup: bool) -> list[dict]:
    html = fetch_page()
    p = ReadingListParser()
    p.feed(html)
    seen, recs = set(), []
    for r in p.records:
        key = pf.norm(r["title"])
        if len(key) < 8 or key in seen:
            continue
        seen.add(key)
        authors = parse_authors(r["authors_text"])
        recs.append({
            "section": r["section"],
            "title": r["title"],
            "authors": authors,
            "year": parse_year(r["trailer"]),
            "startpage": parse_startpage(r["trailer"]),
            "trailer": r["trailer"][:200],
            "in_index": None,
            "pdf_url": None,
            "source": None,
            "status": "pending",
        })
    print(f"parsed {len(recs)} unique citations from the reading list")
    if dedup:
        idx = pf.IndexDedup()
        for r in recs:
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in recs if r['in_index'])} already in the search index")
    return recs


def fetch_page(force: bool = False) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if HTML_CACHE.exists() and HTML_CACHE.stat().st_size > 5000 and not force:
        return HTML_CACHE.read_text(encoding="utf-8")
    r = pf.requests.get(SNAPSHOT, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    HTML_CACHE.write_text(r.text, encoding="utf-8")
    return r.text


# ---------------------------------------------------------------------------
# 2. resolve - find a downloadable PDF URL
# ---------------------------------------------------------------------------

def build_cmu_catalog(sess) -> dict[tuple[str, int], str]:
    """Map (first-author surname, ACM start-page) -> CMU course PDF URL.

    Parses the autoindex for filenames like ``p297-o_neil.pdf`` (ACM naming:
    start-page + first-author surname). Directly answers "a good way to access
    the CMU URLs".
    """
    catalog: dict[tuple[str, int], str] = {}
    try:
        r = sess.get(CMU_COURSE_URL, timeout=45)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! CMU catalog fetch failed: {exc}")
        return catalog
    for href in re.findall(r'href="([^"]+\.pdf)"', r.text, re.I):
        name = Path(urlparse(urljoin(CMU_COURSE_URL, href)).path).name
        m = re.match(r"p(\d{1,4})-([a-z][a-z_'.\-]+)\.pdf$", name, re.I)
        if m:
            page = int(m.group(1))
            surn = re.split(r"[_'.\-]", m.group(2))[0].lower()
            catalog[(surn, page)] = urljoin(CMU_COURSE_URL, href)
    print(f"  CMU catalog: {len(catalog)} page-numbered PDFs")
    return catalog


def resolve_one(r: dict, catalog: dict, email: str) -> None:
    authors = r.get("authors") or []
    # 1) CMU course catalog by (surname, start-page)
    if authors and r.get("startpage"):
        key = (pf.surname(authors[0]), r["startpage"])
        if key in catalog:
            r["pdf_url"], r["source"], r["status"] = catalog[key], "cmu-course", "resolved"
            return
    # 2) DBLP -> ee (arXiv / open pdf), 3) Unpaywall via DOI
    hit = pf.dblp_best(r["title"], authors, r.get("year"))
    if hit:
        for ee in hit.get("ee", []):
            low = ee.lower()
            if "arxiv.org/abs" in low or low.endswith(".pdf"):
                r["pdf_url"], r["source"], r["status"] = ee, "dblp-ee", "resolved"
                return
        doi = hit.get("doi")
        if doi:
            up = pf.unpaywall_pdf(doi, email)
            if up:
                r["pdf_url"], r["source"], r["status"] = up, "unpaywall", "resolved"
                return
    # 4) arXiv title search
    ax = pf.arxiv_pdf(r["title"], authors)
    if ax:
        r["pdf_url"], r["source"], r["status"] = ax, "arxiv", "resolved"
        return
    r["status"] = "unresolved"


def resolve(records: list[dict], limit: int | None) -> None:
    todo = [r for r in records
            if not r.get("in_index") and r.get("status") in ("pending", "unresolved")]
    if limit:
        todo = todo[:limit]
    print(f"resolving PDF URLs for {len(todo)} citations (best-effort)...")
    sess = pf.session()
    catalog = build_cmu_catalog(sess)
    email = pf.git_email()
    for i, r in enumerate(todo, 1):
        try:
            resolve_one(r, catalog, email)
        except Exception as exc:  # noqa: BLE001
            r["status"] = "unresolved"
            print(f"[{i}/{len(todo)}] ERR {type(exc).__name__} {r['title'][:55]}")
            continue
        tag = r["source"] or "--"
        print(f"[{i}/{len(todo)}] {tag:11s} {r['title'][:66]}")
        if i % 15 == 0:
            save_ckpt(records)
        time.sleep(RESOLVE_SLEEP)
    save_ckpt(records)


# ---------------------------------------------------------------------------
# 3. download
# ---------------------------------------------------------------------------

def section_folder(section: str) -> str:
    return re.sub(r"[^\w.\-() ]+", "_", section)[:80].strip() or "misc"


def download(records: list[dict]) -> None:
    targets = [r for r in records if r.get("pdf_url") and not r.get("in_index")
               and r.get("status") in ("resolved", "dl_failed")]
    print(f"downloading {len(targets)} resolved PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        dest = OUT_DIR / section_folder(r["section"]) / (pf.safe_stem(r["authors"], r["title"]) + ".pdf")
        got, msg = pf.download_pdf(sess, r["pdf_url"], dest)
        if got:
            r["status"] = "downloaded"
            ok += 1
            print(f"[{i}/{len(targets)}] OK  ({r['source']}) {dest.name}  ({msg})")
        else:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:55]}  ({msg})")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


# ---------------------------------------------------------------------------
# checkpoint / report / summary
# ---------------------------------------------------------------------------

def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "status", "in_index", "source", "year", "title",
                    "authors", "pdf_url"])
        for r in records:
            w.writerow([r.get("section", ""), r.get("status", ""), r.get("in_index"),
                        r.get("source") or "", r.get("year") or "", r["title"],
                        "; ".join(r.get("authors", [])), r.get("pdf_url") or ""])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    src = Counter(r.get("source") for r in records if r.get("source"))
    print("\n=== Luna Dong reading list summary ===")
    print(f"  citations: {len(records)}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}"
          f" | resolved: {sum(1 for r in records if r.get('pdf_url'))}"
          f" | downloaded: {sum(1 for r in records if r.get('status') == 'downloaded')}")
    print(f"  status: {dict(st)}")
    if src:
        print(f"  resolved via: {dict(src)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "resolve", "download", "all"])
    p.add_argument("--limit", type=int, default=None, help="max citations to resolve this run")
    p.add_argument("--no-dedup", action="store_true", help="do not skip papers already indexed")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup
    if args.cmd == "gather":
        recs = gather(dedup); save_ckpt(recs); print_summary(recs); return 0
    if args.cmd == "resolve":
        recs = load_ckpt() or gather(dedup)
        resolve(recs, args.limit); print_summary(recs); return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather+resolve first", file=sys.stderr); return 2
        download(recs); print_summary(recs); return 0
    recs = load_ckpt()
    if not recs:
        recs = gather(dedup); save_ckpt(recs)
    resolve(recs, args.limit); download(recs); print_summary(recs); return 0


if __name__ == "__main__":
    raise SystemExit(main())
