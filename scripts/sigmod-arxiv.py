#!/usr/bin/env python3
"""Find SIGMOD accepted papers that have an arXiv preprint and download the PDFs.

Pipeline (all resumable via a JSON checkpoint):

  1. gather  – parse DBLP TOC XML for SIGMOD research (PACMMOD volumes) +
               companion tracks (industry / demos / tutorials / ...), for the
               requested conference years, excluding PODS and non-papers.
  2. match   – query the arXiv API by title and confirm the hit with a
               fuzzy title-ratio + author-surname check.
  3. download – fetch the PDF for every confirmed match into
               Inbox/sigmod-arxiv/<year>/.

Usage:
  scripts/.venv/bin/python scripts/sigmod-arxiv.py all
  scripts/.venv/bin/python scripts/sigmod-arxiv.py gather
  scripts/.venv/bin/python scripts/sigmod-arxiv.py match
  scripts/.venv/bin/python scripts/sigmod-arxiv.py download
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

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "sigmod-arxiv"
CKPT = OUT_DIR / "_matches.json"
REPORT = OUT_DIR / "_sigmod-arxiv-report.csv"

YEARS = {2024, 2025, 2026}

# DBLP TOC XML exports to parse.
#  - PACMMOD volumes hold the SIGMOD *research* papers (spread over rounds/years);
#    we key them by the "<h3>SIGMOD Conference YYYY</h3>" section label.
#  - sigmodYYYYc are the conference *companion* proceedings (industry/demo/etc.);
#    the year is fixed per file.
DBLP_XML = {
    "research": [
        "journals/pacmmod/pacmmod1",
        "journals/pacmmod/pacmmod2",
        "journals/pacmmod/pacmmod3",
        "journals/pacmmod/pacmmod4",
    ],
    "companion": {
        2024: "conf/sigmod/sigmod2024c",
        2025: "conf/sigmod/sigmod2025c",
        2026: "conf/sigmod/sigmod2026c",
    },
}

HEADERS = {"User-Agent": "sigmod-arxiv-fetch/1.0 (personal research; mailto:none)"}
ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_SLEEP = 4.0   # arXiv asks for >=3s between API calls; be a little gentler
DL_SLEEP = 1.0

SKIP_TITLE_RE = re.compile(
    r"^(editorial|front matter|corrigendum|corrections?|preface|"
    r"table of contents|table des mati)", re.I)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def clean_text(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)          # drop <i>, <sub>, <sup> ...
    s = html.unescape(s)
    return s.strip()


def norm(s: str) -> str:
    s = clean_text(s).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def surname(author: str) -> str:
    a = re.sub(r"\s+\d+$", "", clean_text(author))   # strip DBLP homonym id
    a = re.sub(r"[^A-Za-z \-]", "", a)
    parts = a.split()
    return parts[-1].lower() if parts else ""


# ---------------------------------------------------------------------------
# 1. gather
# ---------------------------------------------------------------------------

XML_CACHE = OUT_DIR / "_xml_cache"


def fetch_xml(key: str) -> str:
    XML_CACHE.mkdir(parents=True, exist_ok=True)
    cache = XML_CACHE / (key.replace("/", "_") + ".xml")
    if cache.exists() and cache.stat().st_size > 1000:
        return cache.read_text(encoding="utf-8")
    url = f"https://dblp.org/db/{key}.xml"
    last = None
    for attempt in range(6):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                cache.write_text(r.text, encoding="utf-8")
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
        wait = 10 * (attempt + 1)
        print(f"      dblp {key}: {last}; retry in {wait}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"failed to fetch {url}: {last}")


REC_RE = re.compile(
    r"<h2>(?P<h2>.*?)</h2>|<h3>(?P<h3>.*?)</h3>|"
    r"<(?P<tag>article|inproceedings)\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.S)


def parse_toc(xml: str, want_year: int | None, track_from_file: str | None):
    """Yield dicts for records. If want_year is set (research), filter by the
    'SIGMOD Conference <year>' h3 label and drop PODS. Otherwise (companion)
    take everything and tag with track_from_file's section headers."""
    cur_h2 = cur_h3 = None
    for m in REC_RE.finditer(xml):
        if m.group("h2") is not None:
            cur_h2 = clean_text(m.group("h2"))
            continue
        if m.group("h3") is not None:
            cur_h3 = clean_text(m.group("h3"))
            continue
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

        if want_year is not None:   # research: PACMMOD, gated by section label
            sec = cur_h3 or ""
            if "PODS" in sec.upper():
                continue
            mm = re.search(r"SIGMOD Conference\s+(\d{4})", sec)
            if not mm or int(mm.group(1)) != want_year:
                continue
            yield {"year": want_year, "track": "research", "section": sec,
                   "title": title, "authors": authors, "doi": doi}
        else:                       # companion: everything, section = current header
            sec = cur_h2 or cur_h3 or "companion"
            # skip pure abstracts we can't match (keynotes / panels / workshops)
            low = sec.lower()
            if any(k in low for k in ("keynote", "plenary", "panel", "workshop")):
                track = "other"
            elif "demo" in low:
                track = "demo"
            elif "industr" in low:
                track = "industry"
            elif "tutorial" in low:
                track = "tutorial"
            else:
                track = "companion"
            yield {"year": track_from_file, "track": track, "section": sec,
                   "title": title, "authors": authors, "doi": doi}


def gather() -> list[dict]:
    records: list[dict] = []
    # research papers across all PACMMOD volumes, filtered per year
    for key in DBLP_XML["research"]:
        print(f"  fetching {key} ...", flush=True)
        xml = fetch_xml(key)
        for y in sorted(YEARS):
            got = list(parse_toc(xml, want_year=y, track_from_file=None))
            if got:
                print(f"      SIGMOD {y}: +{len(got)} research")
                records.extend(got)
    # companion tracks per year
    for y, key in DBLP_XML["companion"].items():
        if y not in YEARS:
            continue
        print(f"  fetching {key} ...", flush=True)
        xml = fetch_xml(key)
        got = list(parse_toc(xml, want_year=None, track_from_file=y))
        print(f"      SIGMOD {y} companion: +{len(got)}")
        records.extend(got)

    # de-dup by (year, normalized title)
    seen, uniq = set(), []
    for r in records:
        k = (r["year"], norm(r["title"]))
        if k in seen:
            continue
        seen.add(k)
        r["arxiv_id"] = None
        r["arxiv_title"] = ""
        r["status"] = "pending"
        uniq.append(r)
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
    print(f"matching {len(todo)} papers against arXiv (sleep {ARXIV_SLEEP}s)...")
    for i, r in enumerate(todo, 1):
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
            r["status"] = "found"
            tag = f"r={ratio:.2f} a={overlap}"
            print(f"[{i}/{len(todo)}] FOUND  {c['id']:16s} {tag}  {r['title'][:70]}")
        else:
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
    return f"{stem} [{rec['arxiv_id']}].pdf"


def download(records: list[dict]) -> None:
    found = [r for r in records if r.get("status") in ("found", "downloaded")]
    print(f"downloading {len(found)} matched PDFs...")
    session = requests.Session()
    ok = fail = skip = 0
    for i, r in enumerate(found, 1):
        dest_dir = OUT_DIR / str(r["year"]) / r["track"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name(r)
        if dest.exists() and dest.stat().st_size > 2000:
            r["status"] = "downloaded"
            skip += 1
            continue
        aid = r["arxiv_id"]
        url = f"https://arxiv.org/pdf/{aid}"
        try:
            resp = session.get(url, headers=HEADERS, timeout=90, allow_redirects=True)
            data = resp.content
            if resp.status_code == 200 and (data[:5].startswith(b"%PDF")) and len(data) > 2000:
                dest.write_bytes(data)
                r["status"] = "downloaded"
                ok += 1
                print(f"[{i}/{len(found)}] OK  {dest.name}  ({len(data)//1024} KB)")
            else:
                r["status"] = "dl_failed"
                fail += 1
                print(f"[{i}/{len(found)}] -- {aid}: HTTP {resp.status_code}, {len(data)} bytes")
        except Exception as exc:  # noqa: BLE001
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(found)}] -- {aid}: {type(exc).__name__}: {str(exc)[:80]}")
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
        w.writerow(["year", "track", "status", "arxiv_id", "title",
                    "arxiv_title", "authors", "doi", "section"])
        for r in records:
            w.writerow([r["year"], r["track"], r["status"], r.get("arxiv_id") or "",
                        r["title"], r.get("arxiv_title", ""),
                        "; ".join(r["authors"]), r.get("doi", ""), r.get("section", "")])


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
    tot = len(records)
    found = sum(1 for r in records if r["status"] in ("found", "downloaded"))
    dl = sum(1 for r in records if r["status"] == "downloaded")
    print(f"  total papers: {tot} | arXiv matches: {found} | downloaded: {dl}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:2] or ["all"])[0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if cmd == "gather":
        recs = gather()
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
        recs = load_ckpt()
        if not recs:
            recs = gather()
            save_ckpt(recs)
        match(recs)
        download(recs)
        print_summary(recs)
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
