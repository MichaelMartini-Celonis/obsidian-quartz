#!/usr/bin/env python3
"""Harvest ACM CAIS accepted papers, keep the ones that are Open Access on ACM,
and download the PDFs into ``Inbox/``.

Pipeline (resumable via a JSON checkpoint):

  1. gather   – parse the CAIS "Accepted Papers" listing for title / authors /
                pillar / per-paper URL, then read each per-paper page to pull
                the ACM Digital Library DOI.
  2. oa       – ask Unpaywall (DOI -> OA status) whether each paper is Open
                Access on ACM (gold / hybrid / bronze / any acm.org OA location)
                and collect downloadable OA PDF URLs.
  3. download – fetch the PDF for every OA paper into Inbox/cais-<year>/<pillar>/.
                ACM's own PDF endpoint is behind Cloudflare (HTTP 403 for
                scripts), so when the paper is OA we fall back to the OA copy
                Unpaywall surfaces (publisher mirror / arXiv / repository) and
                record which source was actually used.

Usage:
  scripts/.venv/bin/python scripts/cais-acm.py all
  scripts/.venv/bin/python scripts/cais-acm.py gather|oa|download
"""

from __future__ import annotations

import csv
import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

DOCS_ROOT = Path(__file__).resolve().parent.parent
YEAR = 2026
LIST_URL = f"https://www.caisconf.org/program/{YEAR}/papers/"
OUT_DIR = DOCS_ROOT / "Inbox" / f"cais-{YEAR}"
HTML_CACHE = OUT_DIR / "_html_cache"
CKPT = OUT_DIR / "_cais.json"
REPORT = OUT_DIR / "_cais-report.csv"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
UNPAYWALL = "https://api.unpaywall.org/v2/"
# Unpaywall requires a real contact email; reuse the repo's git identity.
try:
    EMAIL = subprocess.check_output(
        ["git", "-C", str(DOCS_ROOT), "config", "user.email"], text=True).strip()
except Exception:  # noqa: BLE001
    EMAIL = ""
EMAIL = EMAIL or "research@localhost"

# oa_status values that mean the article is Open Access *at the publisher* (ACM)
OA_ON_ACM_STATUS = {"gold", "hybrid", "bronze"}


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def cache_get(url: str, name: str) -> str:
    HTML_CACHE.mkdir(parents=True, exist_ok=True)
    f = HTML_CACHE / name
    if f.exists() and f.stat().st_size > 200:
        return f.read_text(encoding="utf-8")
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    f.write_text(r.text, encoding="utf-8")
    time.sleep(0.3)
    return r.text


# ---------------------------------------------------------------------------
# 1. gather
# ---------------------------------------------------------------------------

CARD_RE = re.compile(
    r'<div class="paper-card"[^>]*>\s*'
    r'<h3[^>]*>\s*<a href="(?P<slug>/program/\d+/papers/[^"]+)"[^>]*>(?P<title>.*?)</a>\s*</h3>\s*'
    r'(?:<p class="small text-muted mb-1">(?P<authors>.*?)</p>)?',
    re.S)

PILLAR_RE = re.compile(r'<h2[^>]*>(?P<pillar>.*?)</h2>', re.S)


def parse_authors(raw: str) -> list[str]:
    if not raw:
        return []
    txt = re.sub(r"<span[^>]*>\(.*?\)</span>", "", raw)   # drop affiliations
    txt = clean(txt)
    parts = [re.sub(r"\s*\(.*?\)\s*", "", p).strip() for p in txt.split(",")]
    return [p for p in parts if p]


def gather() -> list[dict]:
    listing = cache_get(LIST_URL, "_listing.html")

    # Map each card to the pillar (<h2>) that precedes it.
    markers = []
    for m in PILLAR_RE.finditer(listing):
        markers.append((m.start(), "pillar", clean(m.group("pillar"))))
    for m in CARD_RE.finditer(listing):
        markers.append((m.start(), "card", m))
    markers.sort(key=lambda x: x[0])

    records, cur_pillar = [], ""
    for _, kind, payload in markers:
        if kind == "pillar":
            cur_pillar = re.sub(r"\s*\d+\s*papers?$", "", payload).strip()
        else:
            m = payload
            slug = m.group("slug")
            records.append({
                "title": clean(m.group("title")),
                "slug": slug,
                "url": "https://www.caisconf.org" + slug,
                "pillar": cur_pillar,
                "authors": parse_authors(m.group("authors") or ""),
                "doi": None, "is_oa": None, "oa_status": None,
                "oa_on_acm": None, "pdf_url": None, "source": None,
                "status": "pending",
            })

    # de-dup by slug, then fetch each per-paper page for the ACM DOI
    seen, uniq = set(), []
    for r in records:
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        uniq.append(r)

    print(f"parsed {len(uniq)} entries; fetching per-paper pages for DOIs...")
    for i, r in enumerate(uniq, 1):
        name = "paper_" + re.sub(r"[^a-z0-9]+", "_", r["slug"]) + ".html"
        try:
            page = cache_get(r["url"], name)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}] page error {r['slug']}: {exc}")
            continue
        dm = re.search(r'dl\.acm\.org/doi/(10\.\d{4,9}/[^\s"\'<>]+)', page)
        r["doi"] = dm.group(1) if dm else None
        if not r["doi"]:
            r["status"] = "no_doi"
        if i % 10 == 0:
            print(f"  ...{i}/{len(uniq)}")
    return uniq


# ---------------------------------------------------------------------------
# 2. OA check via Unpaywall
# ---------------------------------------------------------------------------

def oa_check(records: list[dict]) -> None:
    todo = [r for r in records if r.get("doi") and r.get("oa_status") is None]
    print(f"checking OA on ACM for {len(todo)} DOIs via Unpaywall ({EMAIL})...")
    for i, r in enumerate(todo, 1):
        try:
            resp = requests.get(f"{UNPAYWALL}{r['doi']}",
                                params={"email": EMAIL}, headers=HEADERS, timeout=60)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}] unpaywall error {r['doi']}: {exc}")
            time.sleep(1)
            continue
        if resp.status_code != 200:
            r["oa_status"] = "unknown"
            r["is_oa"] = None
            r["oa_on_acm"] = None
            print(f"  [{i}] {r['doi']}: unpaywall HTTP {resp.status_code}")
            time.sleep(0.5)
            continue
        d = resp.json()
        r["is_oa"] = bool(d.get("is_oa"))
        r["oa_status"] = d.get("oa_status") or "closed"
        locs = d.get("oa_locations") or []
        acm_loc = any("acm.org" in ((l.get("url") or "") + (l.get("url_for_pdf") or ""))
                      for l in locs)
        r["oa_on_acm"] = bool(r["is_oa"] and (r["oa_status"] in OA_ON_ACM_STATUS or acm_loc))
        # collect candidate PDF urls: prefer non-ACM direct PDFs (ACM blocks bots)
        pdfs = [l.get("url_for_pdf") for l in locs if l.get("url_for_pdf")]
        r["pdf_url"] = next((u for u in pdfs if "acm.org" not in u), pdfs[0] if pdfs else None)
        print(f"  [{i}/{len(todo)}] {r['oa_status']:7s} oa_acm={r['oa_on_acm']!s:5s} "
              f"pdf={'Y' if r['pdf_url'] else '-'}  {r['title'][:55]}")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(0.4)
    save_ckpt(records)


# ---------------------------------------------------------------------------
# 3. download
# ---------------------------------------------------------------------------

ARXIV_API = "http://export.arxiv.org/api/query"
ATOM_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)


def _norm(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", html.unescape(s)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def arxiv_by_title(title: str, authors: list[str]) -> str | None:
    """Last-resort OA source: find an arXiv preprint for an OA-on-ACM paper
    whose ACM PDF is Cloudflare-blocked. Confirms via title ratio + author."""
    import difflib
    words = re.findall(r"[A-Za-z0-9]+", title)
    phrase = " ".join(words[:14])
    if not phrase:
        return None
    for attempt in range(4):
        try:
            r = requests.get(ARXIV_API, params={"search_query": f'ti:"{phrase}"',
                             "max_results": 8}, headers=HEADERS, timeout=60)
        except Exception:  # noqa: BLE001
            time.sleep(10); continue
        if r.status_code == 200:
            break
        if r.status_code in (429, 503):
            time.sleep(30 * (attempt + 1)); continue
        return None
    else:
        return None
    tgt = _norm(title)
    surn = {a.split()[-1].lower() for a in authors if a.split()} - {""}
    best, best_score = None, 0.0
    for e in ATOM_ENTRY.findall(r.text):
        idm = re.search(r"<id>(.*?)</id>", e)
        tm = re.search(r"<title>(.*?)</title>", e, re.S)
        if not idm or not tm:
            continue
        ratio = difflib.SequenceMatcher(None, tgt, _norm(tm.group(1))).ratio()
        names = re.findall(r"<name>(.*?)</name>", e)
        overlap = len({n.split()[-1].lower() for n in names if n.split()} & surn)
        if (ratio >= 0.92 or (ratio >= 0.80 and overlap)) and ratio + 0.05 * overlap > best_score:
            best_score = ratio + 0.05 * overlap
            best = idm.group(1).rsplit("/abs/", 1)[-1]
    time.sleep(3)
    return f"https://arxiv.org/pdf/{best}" if best else None


def safe_name(r: dict) -> str:
    first = (r["authors"][0].split()[-1] if r["authors"] else "Unknown")
    extra = " et al" if len(r["authors"]) > 1 else ""
    stem = f"{first}{extra} - {r['title']}"
    stem = re.sub(r"[^\w.\-() ]+", "_", stem)[:180].strip()
    return f"{stem}.pdf"


def candidate_urls(r: dict) -> list[str]:
    urls = []
    if r.get("doi"):
        urls.append(f"https://dl.acm.org/doi/pdf/{r['doi']}")   # ACM OA (often 403)
    if r.get("pdf_url"):
        urls.append(r["pdf_url"])
    # normalize arxiv abs -> pdf
    out = []
    for u in urls:
        m = re.match(r"https?://arxiv\.org/abs/([^?#]+)", u)
        out.append(f"https://arxiv.org/pdf/{m.group(1)}" if m else u)
    return out


def download(records: list[dict]) -> None:
    # Only papers that are Open Access on ACM (per the user's requirement).
    targets = [r for r in records if r.get("oa_on_acm")]
    print(f"downloading {len(targets)} OA-on-ACM papers...")
    session = requests.Session()
    ok = fail = skip = 0
    for i, r in enumerate(targets, 1):
        pillar = re.sub(r"[^\w.\-() ]+", "_", r["pillar"] or "misc").strip() or "misc"
        dest_dir = OUT_DIR / pillar
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name(r)
        if dest.exists() and dest.stat().st_size > 2000:
            r["status"] = "downloaded"
            skip += 1
            continue
        cands = candidate_urls(r)
        got = False
        for pass_no in range(2):
            for url in cands:
                try:
                    resp = session.get(url, headers=HEADERS, timeout=90, allow_redirects=True)
                    data = resp.content
                except Exception as exc:  # noqa: BLE001
                    print(f"    ! {url[:50]}: {type(exc).__name__}")
                    continue
                if resp.status_code == 200 and data[:5].startswith(b"%PDF") and len(data) > 2000:
                    dest.write_bytes(data)
                    r["status"] = "downloaded"
                    if "acm.org" in url:
                        r["source"] = "acm"
                    elif "arxiv.org" in url:
                        r["source"] = url.rsplit("/", 1)[-1] + " (arxiv)"
                    else:
                        r["source"] = url
                    ok += 1
                    src = "ACM" if "acm.org" in url else ("arXiv" if "arxiv" in url else "mirror")
                    print(f"[{i}/{len(targets)}] OK  ({src}) {dest.name}  ({len(data)//1024} KB)")
                    got = True
                    break
                time.sleep(0.5)
            if got:
                break
            # ACM blocked / no repository PDF: try arXiv title search once, then retry.
            ax = arxiv_by_title(r["title"], r.get("authors", []))
            if ax and ax not in cands:
                r["pdf_url"] = r.get("pdf_url") or ax
                cands = [ax]
            else:
                break
        if not got:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(targets)}] -- no downloadable PDF  {r['title'][:60]}")
        if i % 10 == 0:
            save_ckpt(records)
        time.sleep(0.8)
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
        w.writerow(["pillar", "status", "oa_status", "oa_on_acm", "source",
                    "title", "authors", "doi", "pdf_url", "url"])
        for r in records:
            w.writerow([r.get("pillar", ""), r.get("status", ""), r.get("oa_status", ""),
                        r.get("oa_on_acm", ""), r.get("source", "") or "",
                        r["title"], "; ".join(r.get("authors", [])),
                        r.get("doi") or "", r.get("pdf_url") or "", r.get("url", "")])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    oa = Counter(r.get("oa_status") for r in records)
    st = Counter(r.get("status") for r in records)
    n_acm = sum(1 for r in records if r.get("oa_on_acm"))
    dl = sum(1 for r in records if r.get("status") == "downloaded")
    print("\n=== CAIS summary ===")
    print(f"  papers: {len(records)} | with DOI: {sum(1 for r in records if r.get('doi'))}")
    print(f"  oa_status: {dict(oa)}")
    print(f"  OA on ACM: {n_acm} | downloaded: {dl}")
    print(f"  status: {dict(st)}")


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:2] or ["all"])[0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if cmd == "gather":
        recs = gather(); save_ckpt(recs); print_summary(recs); return 0
    if cmd == "oa":
        recs = load_ckpt() or gather(); oa_check(recs); print_summary(recs); return 0
    if cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather+oa first", file=sys.stderr); return 2
        download(recs); print_summary(recs); return 0
    if cmd == "all":
        recs = load_ckpt()
        if not recs:
            recs = gather(); save_ckpt(recs)
        oa_check(recs); download(recs); print_summary(recs); return 0
    print(f"unknown command: {cmd}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
