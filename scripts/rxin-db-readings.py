#!/usr/bin/env python3
"""Harvest Reynold Xin's classic database reading list (``rxin/db-readings``)
*and*, best-effort, the "External Reading Lists" it links to (a list of lists).

Main list: https://github.com/rxin/db-readings  (README.md)

The README is curated markdown. Two things get harvested:

  1. **In-repo papers** - entries shaped ``[Title](papers/xyz.pdf) (YEAR): ...``
     whose PDFs are hosted right in the repo, so they download directly from
     ``raw.githubusercontent.com/rxin/db-readings/master/papers/<file>``.

  2. **External Reading Lists** (the ``#external`` section) - a handful of other
     schools' graduate DB reading lists (Berkeley, Brown, Stanford, MIT, Wisconsin,
     CMU). These are heterogeneous web pages / sheets / PDFs, so for each we do a
     *best-effort* crawl: pull out direct ``.pdf`` / arXiv links (downloaded
     straight away) and descriptive hyperlink texts (treated as citations and
     resolved to an open PDF via DBLP / Unpaywall / arXiv, exactly like the Luna
     Dong harvester). Google-Sheet lists are read via their CSV export. Anything
     with no open copy is reported as ``unresolved`` / ``list_unreachable``.

Everything is deduped against the live search index and lands under
``Inbox/db-readings/<section>/``. Resumable via a JSON checkpoint.

Usage:
  scripts/.venv/bin/python scripts/rxin-db-readings.py all
  scripts/.venv/bin/python scripts/rxin-db-readings.py gather
  scripts/.venv/bin/python scripts/rxin-db-readings.py resolve --limit 40
  scripts/.venv/bin/python scripts/rxin-db-readings.py download
  scripts/.venv/bin/python scripts/rxin-db-readings.py all --no-external
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

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
RAW_README = "https://raw.githubusercontent.com/rxin/db-readings/master/README.md"
REPO_RAW_BASE = "https://raw.githubusercontent.com/rxin/db-readings/master/"
OUT_DIR = DOCS_ROOT / "Inbox" / "db-readings"
CKPT = OUT_DIR / "_db-readings.json"
REPORT = OUT_DIR / "_db-readings-report.csv"
RESOLVE_SLEEP = 0.3
DL_SLEEP = 0.6

MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]+)\]\((?P<href>[^)]+)\)")
YEAR_PAREN_RE = re.compile(r"\((?:19|20)(\d{2})\)")
HTML_LINK_RE = re.compile(r'<a\b[^>]*href="(?P<href>[^"#]+)"[^>]*>(?P<text>.*?)</a>', re.I | re.S)

# hyperlink texts that are navigation / boilerplate, not paper titles.
SKIP_TEXT = re.compile(
    r"^(home|about|syllabus|schedule|readings?|reading list|course|back|next|"
    r"prev|top|menu|login|edit|view|download|pdf|link|here|slides|lecture|"
    r"piazza|canvas|email|contact|calendar|policies|grading|projects?|"
    r"assignments?|resources?|papers?|more|google|github|twitter)\b", re.I)


def _year_from(text: str) -> int | None:
    m = YEAR_PAREN_RE.search(text)
    if m:
        y = int(("19" if int(m.group(1)) > 30 else "20") + m.group(1))
        return y
    ys = [int(y) for y in re.findall(r"((?:19|20)\d{2})", text) if 1960 <= int(y) <= 2027]
    return ys[0] if ys else None


# ---------------------------------------------------------------------------
# 1. gather
# ---------------------------------------------------------------------------

def parse_repo_readme(md: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """Return (in-repo paper records, [(external-list name, url), ...])."""
    section = "General"
    papers: list[dict] = []
    external: list[tuple[str, str]] = []
    in_external = False
    for line in md.splitlines():
        hm = re.match(r"^#{2,4}\s*(?:<a name='([^']+)'>\s*)?(.*)$", line)
        if hm:
            anchor, label = hm.group(1), pf.clean(hm.group(2))
            section = label or section
            in_external = (anchor == "external") or ("external reading list" in section.lower())
            continue
        for m in MD_LINK_RE.finditer(line):
            text, href = pf.clean(m.group("text")), m.group("href").strip()
            if in_external:
                if href.startswith("http"):
                    external.append((text, href))
                continue
            if href.startswith("papers/") and href.lower().endswith(".pdf"):
                papers.append({
                    "section": section,
                    "title": text,
                    "authors": [],
                    "year": _year_from(line),
                    "pdf_url": urljoin(REPO_RAW_BASE, href),
                    "doi": None,
                    "source": "db-readings-repo",
                    "list": "rxin/db-readings",
                    "status": "pending",
                    "in_index": None,
                })
    return papers, external


def google_sheet_csv(url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not m:
        return None
    gid = re.search(r"[?&#]gid=(\d+)", url)
    exp = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
    if gid:
        exp += f"&gid={gid.group(1)}"
    return exp


def crawl_external(name: str, url: str, sess) -> list[dict]:
    """Best-effort: pull direct-PDF/arXiv links and citation-like titles from a list."""
    recs: list[dict] = []
    csv_url = google_sheet_csv(url)
    try:
        r = sess.get(csv_url or url, timeout=60, allow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! {name}: unreachable ({type(exc).__name__})")
        return [{"section": f"External/{name}", "title": f"[list] {url}", "authors": [],
                 "year": None, "pdf_url": None, "doi": None, "source": f"ext:{name}",
                 "list": name, "status": "list_unreachable", "in_index": None}]
    ctype = r.headers.get("Content-Type", "").lower()

    def add(title, pdf=None, doi=None, status="pending"):
        title = pf.clean(title)
        if len(pf.norm(title)) < 10:
            return
        recs.append({"section": f"External/{name}", "title": title, "authors": [],
                     "year": _year_from(title), "pdf_url": pdf, "doi": doi,
                     "source": f"ext:{name}", "list": name, "status": status,
                     "in_index": None})

    if csv_url and ("csv" in ctype or not ctype):
        for row in csv.reader(r.text.splitlines()):
            for cell in row:
                cell = cell.strip()
                if len(cell.split()) >= 4 and re.search(r"[A-Za-z]", cell):
                    add(cell)
        return recs

    if "pdf" in ctype or url.lower().endswith(".pdf"):
        # the external "list" is itself a PDF document of citations; not a paper.
        return [{"section": f"External/{name}", "title": f"[pdf list] {name}", "authors": [],
                 "year": None, "pdf_url": None, "doi": None, "source": f"ext:{name}",
                 "list": name, "status": "manual_pdf_list", "in_index": None}]

    html = r.text
    for m in HTML_LINK_RE.finditer(html):
        href = pf.html.unescape(m.group("href").strip())
        text = pf.clean(m.group("text"))
        abs_href = urljoin(r.url, href)
        low = abs_href.lower()
        if low.endswith(".pdf"):
            add(text or Path(urlparse(low).path).stem, pdf=abs_href)
        elif "arxiv.org/abs/" in low or "arxiv.org/pdf/" in low:
            add(text or abs_href, pdf=abs_href)
        elif "doi.org/10." in low:
            doi = low.split("doi.org/", 1)[1]
            add(text or doi, doi=doi)
        elif (len(text) >= 20 and " " in text and not SKIP_TEXT.match(text)
              and not text.lower().startswith(("http", "www."))):
            add(text)
    # de-dup within the list by normalised title
    seen, uniq = set(), []
    for x in recs:
        k = pf.norm(x["title"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq


def gather(dedup: bool, do_external: bool) -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md = pf.requests.get(RAW_README, headers=pf.HEADERS, timeout=60).text
    papers, external = parse_repo_readme(md)
    print(f"repo papers: {len(papers)} | external lists: {len(external)}")
    records = list(papers)
    if do_external:
        sess = pf.session()
        for name, url in external:
            got = crawl_external(name, url, sess)
            print(f"  external '{name}': +{len(got)} candidates")
            records.extend(got)
            time.sleep(0.5)
    # global de-dup by normalised title
    seen, uniq = set(), []
    for r in records:
        k = pf.norm(r["title"])
        if len(k) < 6 or k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    records = uniq
    print(f"total unique candidates: {len(records)} "
          f"({sum(1 for r in records if r['pdf_url'])} with a direct PDF/arXiv link)")
    if dedup:
        idx = pf.IndexDedup()
        for r in records:
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in records if r['in_index'])} already in the search index")
    return records


# ---------------------------------------------------------------------------
# 2. resolve (title-only candidates)
# ---------------------------------------------------------------------------

def resolve_one(r: dict, email: str) -> None:
    hit = pf.dblp_best(r["title"], r.get("authors"), r.get("year"))
    if hit:
        if not r.get("authors") and hit.get("authors"):
            r["authors"] = hit["authors"]
        for ee in hit.get("ee", []):
            low = ee.lower()
            if "arxiv.org/abs" in low or low.endswith(".pdf"):
                r["pdf_url"], r["source"], r["status"] = ee, "dblp-ee", "resolved"
                return
        doi = hit.get("doi") or r.get("doi")
        if doi:
            up = pf.unpaywall_pdf(doi, email)
            if up:
                r["pdf_url"], r["source"], r["status"] = up, "unpaywall", "resolved"
                return
    if r.get("doi"):
        up = pf.unpaywall_pdf(r["doi"], email)
        if up:
            r["pdf_url"], r["source"], r["status"] = up, "unpaywall", "resolved"
            return
    ax = pf.arxiv_pdf(r["title"], r.get("authors"))
    if ax:
        r["pdf_url"], r["source"], r["status"] = ax, "arxiv", "resolved"
        return
    r["status"] = "unresolved"


def resolve(records: list[dict], limit: int | None) -> None:
    todo = [r for r in records if not r.get("in_index") and not r.get("pdf_url")
            and r.get("status") in ("pending", "unresolved")]
    if limit:
        todo = todo[:limit]
    print(f"resolving PDF URLs for {len(todo)} title-only candidates (best-effort)...")
    email = pf.git_email()
    for i, r in enumerate(todo, 1):
        try:
            resolve_one(r, email)
        except Exception as exc:  # noqa: BLE001
            r["status"] = "unresolved"
            print(f"[{i}/{len(todo)}] ERR {type(exc).__name__} {r['title'][:55]}")
            continue
        print(f"[{i}/{len(todo)}] {(r['source'] or '--'):11s} {r['title'][:64]}")
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
               and r.get("status") in ("pending", "resolved", "dl_failed")]
    print(f"downloading {len(targets)} PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        dest = (OUT_DIR / section_folder(r["section"])
                / (pf.safe_stem(r.get("authors") or [], r["title"]) + ".pdf"))
        got, msg = pf.download_pdf(sess, r["pdf_url"], dest)
        if got:
            r["status"], ok = "downloaded", ok + 1
            r["saved_as"] = str(dest.relative_to(OUT_DIR))
            print(f"[{i}/{len(targets)}] OK  ({r['source']}) {dest.name}  ({msg})")
        else:
            r["status"], fail = "dl_failed", fail + 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:52]}  ({msg})")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


# ---------------------------------------------------------------------------
# checkpoint / report / summary
# ---------------------------------------------------------------------------

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
        w.writerow(["list", "section", "status", "in_index", "source", "year",
                    "title", "authors", "pdf_url"])
        for r in records:
            w.writerow([r.get("list", ""), r.get("section", ""), r.get("status", ""),
                        r.get("in_index"), r.get("source") or "", r.get("year") or "",
                        r["title"], "; ".join(r.get("authors", [])), r.get("pdf_url") or ""])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    src = Counter(r.get("source") for r in records if r.get("source"))
    print("\n=== rxin/db-readings summary ===")
    print(f"  candidates: {len(records)}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}"
          f" | with PDF: {sum(1 for r in records if r.get('pdf_url'))}"
          f" | downloaded: {sum(1 for r in records if r.get('status') == 'downloaded')}")
    print(f"  status: {dict(st)}")
    if src:
        print(f"  resolved/linked via: {dict(src)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "resolve", "download", "prune-indexed", "all"])
    p.add_argument("--limit", type=int, default=None, help="max citations to resolve this run")
    p.add_argument("--no-external", action="store_true", help="skip the external reading lists")
    p.add_argument("--no-dedup", action="store_true", help="do not skip papers already indexed")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup
    do_ext = not args.no_external
    if args.cmd == "gather":
        recs = gather(dedup, do_ext); save_ckpt(recs); print_summary(recs); return 0
    if args.cmd == "resolve":
        recs = load_ckpt() or gather(dedup, do_ext)
        resolve(recs, args.limit); print_summary(recs); return 0
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
        recs = gather(dedup, do_ext); save_ckpt(recs)
    resolve(recs, args.limit); download(recs); print_summary(recs); return 0


if __name__ == "__main__":
    raise SystemExit(main())
