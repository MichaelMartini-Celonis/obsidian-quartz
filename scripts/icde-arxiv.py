#!/usr/bin/env python3
"""Find ICDE accepted papers with an open PDF (arXiv preprint or Unpaywall OA)
and download them.

ICDE proceedings are IEEE-paywalled. Pipeline (all resumable via a JSON
checkpoint):

  1. gather  – for years already in DBLP (2021–2025): parse
               ``conf/icde/icde<year>.xml``. For 2026 (not yet in DBLP): parse
               the conference accepted-papers HTML pages (research / industry /
               demo / TKDE / DEFT / PhD).
  2. match   – (a) arXiv API title match (fuzzy title-ratio + author-surname);
               (b) if still missing and a DOI is known, Unpaywall DOI → OA PDF.
  3. download – fetch the PDF for every confirmed match into
               Inbox/icde-arxiv/<year>/<track>/.

Usage:
  scripts/.venv/bin/python scripts/icde-arxiv.py all
  scripts/.venv/bin/python scripts/icde-arxiv.py gather
  scripts/.venv/bin/python scripts/icde-arxiv.py match
  scripts/.venv/bin/python scripts/icde-arxiv.py download
"""

from __future__ import annotations

import csv
import difflib
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "icde-arxiv"
CKPT = OUT_DIR / "_matches.json"
REPORT = OUT_DIR / "_icde-arxiv-report.csv"
HTML_CACHE = OUT_DIR / "_html_cache"
XML_CACHE = OUT_DIR / "_xml_cache"

# Recent years covered. 2021–2025 come from DBLP; 2026 from the conference site
# until DBLP indexes the proceedings.
YEARS = {2021, 2022, 2023, 2024, 2025, 2026}
DBLP_YEARS = {2021, 2022, 2023, 2024, 2025}
HTML_YEAR = 2026

# Track key -> (listing URL, track folder name) for the live conference site.
HTML_LISTINGS = {
    "research": (
        "https://icde2026.github.io/accepted-papers.html",
        "research",
    ),
    "industry": (
        "https://icde2026.github.io/ia-papers.html",
        "industry",
    ),
    "demo": (
        "https://icde2026.github.io/demo-papers.html",
        "demo",
    ),
    "tkde": (
        "https://icde2026.github.io/tkde-papers.html",
        "tkde",
    ),
    "deft": (
        "https://icde2026.github.io/deft-papers.html",
        "deft",
    ),
    "phd": (
        "https://icde2026.github.io/phd-papers.html",
        "phd",
    ),
}

HEADERS = {"User-Agent": "icde-arxiv-fetch/1.0 (personal research; mailto:none)"}
ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_SLEEP = 4.0   # arXiv asks for >=3s between API calls; be a little gentler
DL_SLEEP = 1.0

PAPER_RE = re.compile(
    r'<li class="paper-item">\s*'
    r'(?:<div class="number-column">(?P<num>.*?)</div>)?\s*'
    r'<div>\s*'
    r'<div class="title">(?P<title>.*?)</div>.*?'
    r'<div class="authors">(?P<authors>.*?)</div>',
    re.S)
AUTHOR_RE = re.compile(r'<span class="author-name">(?P<name>.*?)</span>')
REC_RE = re.compile(
    r"<(?P<tag>article|inproceedings)\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.S)
SKIP_TITLE_RE = re.compile(
    r"^(editorial|front matter|corrigendum|corrections?|preface|"
    r"table of contents|table des mati|message from|welcome|"
    r"organizing committee|program committee|keynote|"
    r"conference organization|sponsors?|author index)", re.I)

# Fields restored from a previous checkpoint when re-gathering.
_PRESERVE = ("arxiv_id", "arxiv_title", "pdf_url", "source", "status")
UNPAYWALL_SLEEP = 1.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)          # drop <i>, <sub>, <sup> ...
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def norm(s: str) -> str:
    s = clean_text(s).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def surname(author: str) -> str:
    a = re.sub(r"\*$", "", clean_text(author))         # drop corresponding-author *
    a = re.sub(r"\([^)]*\)", "", a)                      # drop "(affiliation)"
    a = re.sub(r"\s+\d+$", "", a)                        # drop DBLP homonym id
    a = re.sub(r"[^A-Za-z \-]", "", a).strip()
    parts = a.split()
    return parts[-1].lower() if parts else ""


def parse_authors_html(block: str) -> list[str]:
    out = []
    for m in AUTHOR_RE.finditer(block):
        name = clean_text(m.group("name"))
        name = re.sub(r"\*$", "", name).strip()
        if name:
            out.append(name)
    return out


def rec_key(r: dict) -> tuple:
    return (r["year"], r["track"], norm(r["title"]))


def blank_record(**kwargs) -> dict:
    base = {
        "year": None,
        "track": "",
        "number": "",
        "title": "",
        "authors": [],
        "doi": "",
        "section": "",
        "arxiv_id": None,
        "arxiv_title": "",
        "pdf_url": "",
        "source": "",
        "status": "pending",
    }
    base.update(kwargs)
    return base


def _doi_tail(doi_or_url: str) -> str:
    """Strip a ``https://doi.org/`` prefix if present."""
    s = (doi_or_url or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


# ---------------------------------------------------------------------------
# 1. gather — DBLP (past years) + HTML (current year)
# ---------------------------------------------------------------------------

def fetch_url(url: str, cache_path: Path) -> str:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        return cache_path.read_text(encoding="utf-8")
    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.text) > 1000:
                cache_path.write_text(r.text, encoding="utf-8")
                return r.text
            last = f"HTTP {r.status_code}, {len(r.text)} bytes"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        wait = 10 * (attempt + 1)
        print(f"      {url}: {last}; retry in {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def parse_dblp(xml: str, year: int) -> list[dict]:
    """Yield paper records from a DBLP TOC XML. Track is ``main`` (DBLP does
    not expose research/demo/industry section headers for ICDE)."""
    records = []
    for m in REC_RE.finditer(xml):
        body = m.group("body")
        title_m = re.search(r"<title>(.*?)</title>", body, re.S)
        if not title_m:
            continue
        title = clean_text(title_m.group(1)).rstrip(".")
        if not title or SKIP_TITLE_RE.match(title):
            continue
        authors = [clean_text(a) for a in re.findall(r"<author[^>]*>(.*?)</author>", body, re.S)]
        ee = re.findall(r"<ee>(.*?)</ee>", body)
        doi = next((clean_text(e) for e in ee if "doi.org" in e), "")
        records.append(blank_record(
            year=year, track="main", section="dblp",
            title=title, authors=authors, doi=doi,
        ))
    return records


def gather_dblp() -> list[dict]:
    records: list[dict] = []
    for y in sorted(DBLP_YEARS & YEARS):
        key = f"conf/icde/icde{y}"
        print(f"  fetching DBLP {key} ...", flush=True)
        xml = fetch_url(
            f"https://dblp.org/db/{key}.xml",
            XML_CACHE / f"icde{y}.xml",
        )
        got = parse_dblp(xml, y)
        print(f"      ICDE {y} (dblp): +{len(got)}")
        records.extend(got)
    return records


def parse_html_listing(html_text: str, year: int, track: str) -> list[dict]:
    records = []
    for m in PAPER_RE.finditer(html_text):
        title = clean_text(m.group("title"))
        if not title:
            continue
        authors = parse_authors_html(m.group("authors"))
        number = clean_text(m.group("num") or "")
        records.append(blank_record(
            year=year, track=track, number=number, section=track,
            title=title, authors=authors,
        ))
    return records


def gather_html() -> list[dict]:
    if HTML_YEAR not in YEARS:
        return []
    records: list[dict] = []
    for key, (url, track) in HTML_LISTINGS.items():
        print(f"  fetching HTML {HTML_YEAR}/{key} ...", flush=True)
        html_text = fetch_url(url, HTML_CACHE / f"{HTML_YEAR}-{key}.html")
        got = parse_html_listing(html_text, HTML_YEAR, track)
        print(f"      ICDE {HTML_YEAR} {track}: +{len(got)}")
        records.extend(got)
    return records


def merge_status(fresh: list[dict], previous: list[dict]) -> list[dict]:
    """Re-gathering must not wipe prior arXiv match / download state."""
    old = {rec_key(r): r for r in previous}
    for r in fresh:
        prev = old.get(rec_key(r))
        if not prev:
            continue
        for field in _PRESERVE:
            if field in prev:
                r[field] = prev[field]
    return fresh


def gather(previous: list[dict] | None = None) -> list[dict]:
    records = gather_dblp() + gather_html()
    seen, uniq = set(), []
    for r in records:
        k = rec_key(r)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    if previous:
        uniq = merge_status(uniq, previous)
    return uniq


# ---------------------------------------------------------------------------
# 2. match against arXiv
# ---------------------------------------------------------------------------

ATOM_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)


class ArxivError(Exception):
    pass


def arxiv_query(title: str) -> list[dict]:
    """Return arXiv candidates for a title. Raises ArxivError on a transient
    failure (e.g. HTTP 429) so the caller can mark the record retryable rather
    than falsely 'not found'. An empty list means a genuine no-results reply."""
    words = re.findall(r"[A-Za-z0-9]+", clean_text(title))
    phrase = " ".join(words[:14])
    if not phrase:
        return []
    params = {"search_query": f'ti:"{phrase}"', "start": 0, "max_results": 8}
    text = None
    for attempt in range(6):
        try:
            r = requests.get(ARXIV_API, params=params, headers=HEADERS, timeout=60)
        except Exception as exc:  # noqa: BLE001
            wait = 15 * (attempt + 1)
            print(f"    ! arxiv {type(exc).__name__}: {str(exc)[:60]}; wait {wait}s")
            time.sleep(wait)
            continue
        if r.status_code == 200:
            text = r.text
            break
        if r.status_code in (429, 503):
            wait = int(r.headers.get("Retry-After", 0)) or 30 * (attempt + 1)
            print(f"    ! arxiv HTTP {r.status_code}; backoff {wait}s")
            time.sleep(wait)
            continue
        raise ArxivError(f"HTTP {r.status_code}")
    if text is None:
        raise ArxivError("exhausted retries")
    out = []
    for e in ATOM_ENTRY.findall(text):
        idm = re.search(r"<id>(.*?)</id>", e)
        tm = re.search(r"<title>(.*?)</title>", e, re.S)
        if not idm or not tm:
            continue
        aid = idm.group(1).rsplit("/abs/", 1)[-1]
        authors = re.findall(r"<name>(.*?)</name>", e)
        out.append({"id": aid, "title": clean_text(tm.group(1)),
                    "authors": authors})
    return out


def best_match(rec: dict, cands: list[dict]):
    tgt = norm(rec["title"])
    tgt_surn = {surname(a) for a in rec["authors"]} - {""}
    best = None
    best_ratio = 0.0
    for c in cands:
        ratio = difflib.SequenceMatcher(None, tgt, norm(c["title"])).ratio()
        c_surn = {surname(a) for a in c["authors"]} - {""}
        overlap = len(tgt_surn & c_surn)
        accept = ratio >= 0.92 or (ratio >= 0.80 and overlap >= 1)
        score = ratio + (0.05 * overlap)
        if accept and score > best_ratio:
            best_ratio = score
            best = (c, ratio, overlap)
    return best


def match(records: list[dict]) -> None:
    todo = [r for r in records if r.get("status") in ("pending", "error")]
    email = pf.git_email()
    print(f"matching {len(todo)} papers (arXiv, then Unpaywall on DOI)...")
    for i, r in enumerate(todo, 1):
        # --- (a) arXiv title match ---
        try:
            cands = arxiv_query(r["title"])
        except ArxivError as exc:
            r["status"] = "error"
            print(f"[{i}/{len(todo)}] ERR    ({exc}) {r['title'][:70]}")
            save_ckpt(records)
            time.sleep(ARXIV_SLEEP)
            continue
        bm = best_match(r, cands)
        if bm:
            c, ratio, overlap = bm
            r["arxiv_id"] = c["id"]
            r["arxiv_title"] = c["title"]
            r["pdf_url"] = f"https://arxiv.org/pdf/{c['id']}"
            r["source"] = "arxiv"
            r["status"] = "found"
            tag = f"r={ratio:.2f} a={overlap}"
            print(f"[{i}/{len(todo)}] ARXIV  {c['id']:16s} {tag}  {r['title'][:70]}")
            if i % 20 == 0:
                save_ckpt(records)
            time.sleep(ARXIV_SLEEP)
            continue

        # --- (b) Unpaywall DOI fallback (DBLP years carry DOIs) ---
        doi = _doi_tail(r.get("doi") or "")
        if doi:
            up = pf.unpaywall_pdf(doi, email)
            time.sleep(UNPAYWALL_SLEEP)
            if up:
                r["pdf_url"] = up
                r["source"] = "unpaywall"
                r["status"] = "found"
                print(f"[{i}/{len(todo)}] OA     {up[:48]:48s}  {r['title'][:60]}")
                if i % 20 == 0:
                    save_ckpt(records)
                time.sleep(ARXIV_SLEEP)
                continue

        r["status"] = "not_found"
        print(f"[{i}/{len(todo)}] --     {r['title'][:80]}")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(ARXIV_SLEEP)
    save_ckpt(records)


# ---------------------------------------------------------------------------
# 3. download
# ---------------------------------------------------------------------------

def safe_name(rec: dict) -> str:
    first = surname(rec["authors"][0]).title() if rec["authors"] else "Unknown"
    extra = " et al" if len(rec["authors"]) > 1 else ""
    title = clean_text(rec["title"])
    stem = f"{first}{extra} - {title}"
    stem = re.sub(r"[^\w.\-() ]+", "_", stem)[:180].strip()
    tag = rec.get("arxiv_id") or rec.get("source") or "oa"
    return f"{stem} [{tag}].pdf"


def download(records: list[dict]) -> None:
    found = [r for r in records if r.get("status") in ("found", "downloaded")]
    print(f"downloading {len(found)} matched PDFs...")
    session = pf.session()
    ok = fail = skip = 0
    for i, r in enumerate(found, 1):
        dest_dir = OUT_DIR / str(r["year"]) / r["track"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name(r)
        url = r.get("pdf_url") or (
            f"https://arxiv.org/pdf/{r['arxiv_id']}" if r.get("arxiv_id") else ""
        )
        if not url:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(found)}] -- no pdf_url for {r['title'][:60]}")
            continue
        good, info = pf.download_pdf(session, url, dest)
        if good:
            r["status"] = "downloaded"
            if info == "exists":
                skip += 1
            else:
                ok += 1
                print(f"[{i}/{len(found)}] OK  {dest.name}  ({info})")
        else:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(found)}] -- {url[:60]}: {info}")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, skipped(existing) {skip}, failed {fail} ===")


# ---------------------------------------------------------------------------
# checkpoint / report
# ---------------------------------------------------------------------------

def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "track", "number", "status", "source", "arxiv_id",
                    "title", "arxiv_title", "authors", "doi", "pdf_url", "section"])
        for r in records:
            w.writerow([r["year"], r["track"], r.get("number", ""),
                        r["status"], r.get("source", ""),
                        r.get("arxiv_id") or "",
                        r["title"], r.get("arxiv_title", ""),
                        "; ".join(r["authors"]), r.get("doi", ""),
                        r.get("pdf_url", ""), r.get("section", "")])


def load_ckpt() -> list[dict]:
    if CKPT.exists():
        return json.loads(CKPT.read_text(encoding="utf-8"))
    return []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    by_year = Counter((r["year"], r["status"]) for r in records)
    print("\n=== summary (year / status) ===")
    for (y, s), n in sorted(by_year.items()):
        print(f"  {y}  {s:12s} {n}")
    by_track = Counter((r["year"], r["track"]) for r in records)
    print("\n=== papers per year / track ===")
    for (y, t), n in sorted(by_track.items()):
        print(f"  {y}  {t:10s} {n}")
    from collections import Counter as _C
    tot = len(records)
    found = sum(1 for r in records if r["status"] in ("found", "downloaded"))
    dl = sum(1 for r in records if r["status"] == "downloaded")
    by_src = _C(r.get("source") or "-" for r in records
                if r["status"] in ("found", "downloaded"))
    print(f"  total papers: {tot} | OA matches: {found} {dict(by_src)} | downloaded: {dl}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:2] or ["all"])[0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if cmd == "gather":
        prev = load_ckpt()
        recs = gather(previous=prev)
        save_ckpt(recs)
        print_summary(recs)
        return 0
    if cmd == "match":
        recs = load_ckpt() or gather()
        match(recs)
        print_summary(recs)
        return 0
    if cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather+match first", file=sys.stderr)
            return 2
        download(recs)
        print_summary(recs)
        return 0
    if cmd == "all":
        # Always re-gather so newly added years appear, but keep prior match state.
        recs = gather(previous=load_ckpt())
        save_ckpt(recs)
        match(recs)
        download(recs)
        print_summary(recs)
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
