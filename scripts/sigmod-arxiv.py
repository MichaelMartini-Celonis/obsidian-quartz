#!/usr/bin/env python3
"""Find SIGMOD papers with a freely available copy and download the PDFs.

Pipeline (all resumable via a JSON checkpoint):

  1. gather  – parse DBLP TOC XML for SIGMOD research + companion tracks
               (industry / demos / tutorials / ...) for the requested conference
               years, excluding PODS and non-papers. Two proceedings layouts:
               2015–2022 is one `conf/sigmod/sigmodYYYY` volume per year, while
               2023+ splits research into PACMMOD journal volumes and leaves the
               companion in `conf/sigmod/sigmodYYYYc`.
  2. match   – query the arXiv API by title (fuzzy title-ratio + author-surname
               confirmation), then fall back to Unpaywall on the DBLP DOI.
  3. download – fetch the PDF for every confirmed match into
               Inbox/sigmod-arxiv/<year>/<track>/.

`gather` merges into an existing checkpoint, so widening YEARS adds records
without discarding the match results already paid for.

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
from collections import Counter
from pathlib import Path

import requests

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "sigmod-arxiv"
CKPT = OUT_DIR / "_matches.json"
REPORT = OUT_DIR / "_sigmod-arxiv-report.csv"

YEARS = set(range(2015, 2027))

# DBLP TOC XML exports to parse.
#  - PACMMOD volumes hold the SIGMOD *research* papers from 2023 on (spread over
#    rounds/years); we key them by the "<h3>SIGMOD Conference YYYY</h3>" label.
#  - sigmodYYYYc are the matching conference *companion* proceedings
#    (industry/demo/tutorial/...); the year is fixed per file.
#  - Up to 2022 a single sigmodYYYY volume holds every track, sectioned by
#    "<h3>Research N: ...</h3>" / "Industry N" / "Demonstrations" / ...
DBLP_XML = {
    "research": [
        "journals/pacmmod/pacmmod1",
        "journals/pacmmod/pacmmod2",
        "journals/pacmmod/pacmmod3",
        "journals/pacmmod/pacmmod4",
    ],
    "companion": {
        2023: "conf/sigmod/sigmod2023c",
        2024: "conf/sigmod/sigmod2024c",
        2025: "conf/sigmod/sigmod2025c",
        2026: "conf/sigmod/sigmod2026c",
    },
    "combined": {y: f"conf/sigmod/sigmod{y}" for y in range(2015, 2023)},
}

HEADERS = {"User-Agent": "sigmod-arxiv-fetch/1.0 (personal research; mailto:none)"}
ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_SLEEP = 4.0   # arXiv asks for >=3s between API calls; be a little gentler
DBLP_SLEEP = 5.0    # DBLP starts refusing TOC requests fetched back-to-back
UNPAYWALL_SLEEP = 0.5
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


def fetch_xml(key: str) -> str | None:
    """Fetch (and cache) one DBLP TOC. Returns None if DBLP keeps refusing.

    DBLP throttles a burst of TOC requests by answering 429 and then simply
    closing the connection for a while, so back off generously and let the
    caller skip the volume: the cache makes a later re-run cheap.
    """
    XML_CACHE.mkdir(parents=True, exist_ok=True)
    cache = XML_CACHE / (key.replace("/", "_") + ".xml")
    if cache.exists() and cache.stat().st_size > 1000:
        return cache.read_text(encoding="utf-8")
    url = f"https://dblp.org/db/{key}.xml"
    last = None
    for attempt in range(5):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                cache.write_text(r.text, encoding="utf-8")
                time.sleep(DBLP_SLEEP)
                return r.text
            last = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {str(exc)[:70]}"
        wait = 60 * (attempt + 1)
        print(f"      dblp {key}: {last}; retry in {wait}s", flush=True)
        time.sleep(wait)
    print(f"      dblp {key}: giving up ({last}); re-run gather later", flush=True)
    return None


REC_RE = re.compile(
    r"<h2>(?P<h2>.*?)</h2>|<h3>(?P<h3>.*?)</h3>|"
    r"<(?P<tag>article|inproceedings)\b[^>]*>(?P<body>.*?)</(?P=tag)>",
    re.S)


def classify_track(section: str, default: str) -> str:
    """Map a DBLP section header onto a track name.

    Both proceedings layouts label their sections, but with different
    vocabularies: a combined volume names research sessions ("Research 7:
    Modern Hardware") while a companion volume names only the non-research
    tracks, so anything unlabelled there is companion material.
    """
    low = section.lower()
    if any(k in low for k in ("keynote", "plenary", "panel", "workshop",
                              "award", "student abstract", "phd symposium")):
        return "other"
    if "demo" in low:
        return "demo"
    if "industr" in low or "applied" in low:
        return "industry"
    if "tutorial" in low:
        return "tutorial"
    if low.startswith("research"):
        return "research"
    return default


def parse_toc(xml: str, want_year: int | None, track_from_file: str | None,
              default_track: str = "companion"):
    """Yield dicts for records. If want_year is set (PACMMOD research), filter by
    the 'SIGMOD Conference <year>' h3 label and drop PODS. Otherwise take
    everything in the file and tag it with the year the file belongs to."""
    cur_h3 = cur_sec = None
    for m in REC_RE.finditer(xml):
        if m.group("h2") is not None:
            # a combined volume nests research sessions (h3) under track groups
            # (h2), so only the most recent header of either level describes the
            # records that follow
            cur_sec = clean_text(m.group("h2"))
            continue
        if m.group("h3") is not None:
            cur_h3 = cur_sec = clean_text(m.group("h3"))
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
        else:                       # whole file, tracks read off the section header
            sec = cur_sec or default_track
            yield {"year": track_from_file, "track": classify_track(sec, default_track),
                   "section": sec, "title": title, "authors": authors, "doi": doi}


def gather() -> list[dict]:
    records: list[dict] = []
    # research papers across all PACMMOD volumes, filtered per year
    for key in DBLP_XML["research"]:
        print(f"  fetching {key} ...", flush=True)
        xml = fetch_xml(key)
        if xml is None:
            continue
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
        if xml is None:
            continue
        got = list(parse_toc(xml, want_year=None, track_from_file=y))
        print(f"      SIGMOD {y} companion: +{len(got)}")
        records.extend(got)
    # pre-PACMMOD years: one volume holds every track
    for y, key in sorted(DBLP_XML["combined"].items()):
        if y not in YEARS:
            continue
        print(f"  fetching {key} ...", flush=True)
        xml = fetch_xml(key)
        if xml is None:
            continue
        got = list(parse_toc(xml, want_year=None, track_from_file=y,
                             default_track="research"))
        by_track = Counter(r["track"] for r in got)
        print(f"      SIGMOD {y}: +{len(got)} ({dict(by_track)})")
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


def merge(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Add newly gathered records, keeping the match state already established.

    Widening YEARS must not throw away work: a record we have already resolved
    (or proven unresolvable) keeps its status, and only genuinely new titles
    enter as `pending`.
    """
    by_key = {(r["year"], norm(r["title"])): r for r in existing}
    for r in by_key.values():
        # records resolved before Unpaywall was a backend predate `source`
        if r.get("arxiv_id") and not r.get("source"):
            r["source"] = "arxiv"
    added = 0
    for r in fresh:
        k = (r["year"], norm(r["title"]))
        if k in by_key:
            # DBLP may have filled in a DOI since the last gather
            if r.get("doi") and not by_key[k].get("doi"):
                by_key[k]["doi"] = r["doi"]
            continue
        by_key[k] = r
        added += 1
    print(f"  merge: {len(existing)} known + {added} new = {len(by_key)}")
    return sorted(by_key.values(), key=lambda r: (r["year"], r["track"], r["title"]))


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


def _doi_tail(ee: str) -> str:
    """Reduce a DBLP `<ee>` DOI link to the bare DOI."""
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", ee.strip(), flags=re.I)


def _try_unpaywall(rec: dict, email: str) -> str | None:
    """Ask Unpaywall for OA copies of this record's DOI, at most once ever.

    Keeps *every* location rather than just the best one: SIGMOD's own OA
    channel (PACMMOD on dl.acm.org) is unreachable to any automated client, so
    the download stage needs the repository mirrors to fall back on.
    """
    rec["up_tried"] = True
    doi = _doi_tail(rec.get("doi") or "")
    if not doi:
        return None
    urls = pf.unpaywall_locations(doi, email)
    time.sleep(UNPAYWALL_SLEEP)
    if urls:
        rec["pdf_urls"] = urls
        rec["pdf_url"] = urls[0]
        rec["source"] = "unpaywall"
        rec["status"] = "found"
        return urls[0]
    return None


def match(records: list[dict]) -> None:
    email = pf.git_email()
    # Titles already proven absent from arXiv only need the (cheap, DOI-keyed)
    # Unpaywall question, so they don't pay the 4 s arXiv courtesy delay again.
    oa_only = [r for r in records
               if r.get("status") == "not_found" and not r.get("up_tried")
               and r.get("doi")]
    if oa_only:
        print(f"re-checking {len(oa_only)} arXiv misses against Unpaywall...")
        for i, r in enumerate(oa_only, 1):
            url = _try_unpaywall(r, email)
            if url:
                print(f"[{i}/{len(oa_only)}] OA     {url[:48]:48s}  {r['title'][:60]}")
            if i % 50 == 0:
                save_ckpt(records)
        save_ckpt(records)
        print(f"  recovered {sum(1 for r in oa_only if r['status'] == 'found')}")

    # arXiv insists on ~4 s between queries, so a full pass is hours long and any
    # interruption truncates it. Spend the early minutes where preprints actually
    # exist: full research papers, newest first. Demo and tutorial abstracts are
    # almost never posted, and 2015-era companion tracks essentially never.
    rank = {"research": 0, "industry": 1, "tutorial": 2, "demo": 3,
            "companion": 4, "other": 5}
    todo = sorted((r for r in records if r.get("status") in ("pending", "error")),
                  key=lambda r: (rank.get(r["track"], 9), -int(r["year"])))
    print(f"matching {len(todo)} papers (arXiv, then Unpaywall on DOI)...")
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
            r["pdf_url"] = f"https://arxiv.org/pdf/{c['id']}"
            r["source"] = "arxiv"
            r["status"] = "found"
            tag = f"r={ratio:.2f} a={overlap}"
            print(f"[{i}/{len(todo)}] ARXIV  {c['id']:16s} {tag}  {r['title'][:70]}")
        else:
            r["status"] = "not_found"
            url = _try_unpaywall(r, email)
            if url:
                print(f"[{i}/{len(todo)}] OA     {url[:48]:48s}  {r['title'][:60]}")
            else:
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


def download(records: list[dict], dedup: bool = True) -> None:
    found = [r for r in records if r.get("status") in ("found", "downloaded")]
    print(f"downloading {len(found)} matched PDFs...")
    session = pf.session()
    # DBLP gives us the title before we spend anything on the paper, so a copy the
    # corpus already holds can be dropped without a request. Sibling harvesters
    # download first and delete afterwards; here that would be 2.5 GB of transfer
    # to re-acquire papers whose only destination is the importer's duplicate bin.
    idx = pf.IndexDedup() if dedup else None
    ok = fail = skip = in_index = 0
    for i, r in enumerate(found, 1):
        if idx and idx.contains(r["title"]):
            r["status"] = "in_index"
            in_index += 1
            continue
        dest_dir = OUT_DIR / str(r["year"]) / r["track"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name(r)
        urls = r.get("pdf_urls") or []
        if r.get("arxiv_id"):
            urls = [f"https://arxiv.org/pdf/{r['arxiv_id']}"]
        elif r.get("pdf_url") and r["pdf_url"] not in urls:
            urls = [r["pdf_url"], *urls]
        if not urls:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(found)}] -- no pdf url for {r['title'][:60]}")
            continue
        info = "no candidates"
        good = False
        for url in urls:
            try:
                good, info = pf.download_pdf(session, url, dest)
            except Exception as exc:  # noqa: BLE001
                good, info = False, f"{type(exc).__name__}: {str(exc)[:60]}"
            if good:
                r["pdf_url"] = url
                break
            print(f"      x {url[:70]}: {info}")
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
            print(f"[{i}/{len(found)}] -- {r['title'][:60]}: {len(urls)} url(s) failed")
        if i % 20 == 0:
            save_ckpt(records)
        # Pace the remote hosts, not the local disk. A run interrupted near the
        # end re-walks every record it already has, and pausing for those turns a
        # resume into a 20-minute wait for a handful of remaining files.
        if info != "exists":
            time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, skipped(existing) {skip}, "
          f"already indexed {in_index}, failed {fail} ===")


# ---------------------------------------------------------------------------
# checkpoint / report
# ---------------------------------------------------------------------------

def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "track", "status", "source", "arxiv_id", "pdf_url",
                    "title", "arxiv_title", "authors", "doi", "section"])
        for r in records:
            w.writerow([r["year"], r["track"], r["status"], r.get("source", ""),
                        r.get("arxiv_id") or "", r.get("pdf_url", ""),
                        r["title"], r.get("arxiv_title", ""),
                        "; ".join(r["authors"]), r.get("doi", ""), r.get("section", "")])


def load_ckpt() -> list[dict]:
    if CKPT.exists():
        return json.loads(CKPT.read_text(encoding="utf-8"))
    return []


def print_summary(records: list[dict]) -> None:
    by_year = Counter((r["year"], r["status"]) for r in records)
    print("\n=== summary (year / status) ===")
    for (y, s), n in sorted(by_year.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        print(f"  {y}  {s:12s} {n}")
    tot = len(records)
    OPEN = ("found", "downloaded", "in_index")
    found = sum(1 for r in records if r["status"] in OPEN)
    dl = sum(1 for r in records if r["status"] == "downloaded")
    held = sum(1 for r in records if r["status"] == "in_index")
    by_src = Counter(r.get("source", "") for r in records if r["status"] in OPEN)
    print(f"  total papers: {tot} | open copies: {found} {dict(by_src)} "
          f"| downloaded: {dl} | already held: {held}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:2] or ["all"])[0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if cmd == "gather":
        recs = merge(load_ckpt(), gather())
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
        recs = merge(load_ckpt(), gather())
        save_ckpt(recs)
        match(recs)
        download(recs)
        print_summary(recs)
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
