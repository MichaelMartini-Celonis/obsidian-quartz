#!/usr/bin/env python3
"""Shared helpers for the paper-harvesting scripts.

The individual harvesters (``cmu-db-group.py``, ``cmu-course-papers.py``,
``lunadong-reading-list.py`, and the older conference scrapers) all need the
same handful of primitives:

  * a browser-ish ``requests`` session + a resilient PDF downloader that only
    keeps things that are *actually* PDFs;
  * text-normalisation / author-surname helpers for fuzzy title matching;
  * a **dedup check against the live search index** (``search/index.duckdb``)
    so we never re-fetch a paper the library already has;
  * best-effort *metadata -> PDF* resolvers (DBLP title search, Unpaywall DOI
    lookup, arXiv title search) for reading lists that give only citations.

Everything degrades gracefully: if the index is missing, dedup simply returns
"not present"; if a resolver host is down, it returns ``None`` and the caller
records the paper as unresolved.
"""

from __future__ import annotations

import difflib
import html
import re
import subprocess
import time
from pathlib import Path

import requests

DOCS_ROOT = Path(__file__).resolve().parent.parent
INDEX_DB = DOCS_ROOT / "search" / "index.duckdb"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ARXIV_API = "http://export.arxiv.org/api/query"
DBLP_API = "https://dblp.org/search/publ/api"
UNPAYWALL = "https://api.unpaywall.org/v2/"


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

def clean(s: str) -> str:
    """Strip tags/entities and collapse whitespace."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm(s: str) -> str:
    """Aggressive normalisation for fuzzy title comparison."""
    s = clean(s).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def surname(author: str) -> str:
    a = re.sub(r"\s+\d+$", "", clean(author))          # drop DBLP homonym id
    a = re.sub(r"\([^)]*\)", "", a)                      # drop "(affiliation)"
    a = re.sub(r"[^A-Za-z .\-]", "", a).strip()
    parts = [p for p in a.split() if p and p != "."]
    if not parts:
        return ""
    particles = {"van", "der", "de", "den", "von", "la", "le", "du", "di"}
    if len(parts) >= 2 and parts[-2].lower() in particles:
        return " ".join(parts[-2:]).lower()
    return parts[-1].lower()


def safe_stem(authors: list[str], title: str, extra: str = "") -> str:
    """``Author et al - Title[ extra]`` sanitised for a filename (no suffix)."""
    if authors:
        first = surname(authors[0]).title() or "Unknown"
    else:
        first = "Unknown"
    tail = " et al" if len(authors) > 1 else ""
    stem = f"{first}{tail} - {clean(title)}"
    if extra:
        stem = f"{stem} {extra}"
    stem = re.sub(r"[^\w.\-() ]+", "_", stem)[:180].strip()
    return stem or "paper"


# ---------------------------------------------------------------------------
# HTTP / download
# ---------------------------------------------------------------------------

def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def normalize_pdf_url(url: str) -> str:
    """Turn landing-page URLs into direct-PDF URLs where we can (arXiv)."""
    url = url.strip()
    m = re.match(r"https?://arxiv\.org/abs/([^?#]+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    return url


def download_pdf(sess: requests.Session, url: str, dest: Path,
                 timeout: int = 90) -> tuple[bool, str]:
    """Fetch ``url`` to ``dest`` iff the body is a real PDF. Idempotent."""
    if dest.exists() and dest.stat().st_size > 2000:
        return True, "exists"
    url = normalize_pdf_url(url)
    try:
        r = sess.get(url, timeout=timeout, allow_redirects=True)
        data = r.content
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:80]}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    ctype = r.headers.get("Content-Type", "").lower()
    if not ("pdf" in ctype or data[:5].startswith(b"%PDF")):
        return False, f"not a PDF ({ctype or 'unknown'})"
    if len(data) < 2000:
        return False, f"too small ({len(data)} bytes)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True, f"{len(data) // 1024} KB"


# ---------------------------------------------------------------------------
# dedup against the live search index
# ---------------------------------------------------------------------------

class IndexDedup:
    """Check whether a title is already present in ``search/index.duckdb``.

    Loads every document title once (read-only). ``contains(title)`` matches on
    exact normalised equality first, then a high-cutoff fuzzy ratio so minor
    punctuation / subtitle differences still count as "already have it".
    """

    def __init__(self, cutoff: float = 0.93):
        self.cutoff = cutoff
        self.norm_titles: set[str] = set()
        self._norm_list: list[str] = []
        self.available = False
        self._load()

    def _load(self) -> None:
        if not INDEX_DB.exists():
            print(f"  [dedup] index not found at {INDEX_DB}; dedup disabled")
            return
        try:
            import duckdb
        except ImportError:
            print("  [dedup] duckdb not installed; dedup disabled")
            return
        try:
            con = duckdb.connect(str(INDEX_DB), read_only=True)
            rows = con.execute("SELECT title FROM documents").fetchall()
            con.close()
        except Exception as exc:  # noqa: BLE001
            print(f"  [dedup] could not read index ({exc}); dedup disabled")
            return
        for (title,) in rows:
            n = norm(title or "")
            if len(n) >= 8:                    # ignore junk/empty titles
                self.norm_titles.add(n)
        self._norm_list = list(self.norm_titles)
        self.available = True
        print(f"  [dedup] loaded {len(self.norm_titles)} indexed titles")

    def contains(self, title: str) -> bool:
        if not self.available:
            return False
        n = norm(title)
        if len(n) < 8:
            return False
        if n in self.norm_titles:
            return True
        hit = difflib.get_close_matches(n, self._norm_list, n=1, cutoff=self.cutoff)
        return bool(hit)


# ---------------------------------------------------------------------------
# metadata -> PDF resolvers
# ---------------------------------------------------------------------------

def _title_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def dblp_search(title: str, rows: int = 8, sleep: float = 1.2) -> list[dict]:
    """DBLP title search -> candidate records (title/year/venue/doi/ee/authors)."""
    words = re.findall(r"[A-Za-z0-9]+", clean(title))
    q = " ".join(words[:16])
    if not q:
        return []
    for attempt in range(4):
        try:
            r = requests.get(DBLP_API, params={"q": q, "format": "json", "h": rows},
                             headers=HEADERS, timeout=45)
        except Exception:  # noqa: BLE001
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            break
        if r.status_code in (429, 503):
            time.sleep(10 * (attempt + 1))
            continue
        return []
    else:
        return []
    time.sleep(sleep)
    try:
        hits = r.json().get("result", {}).get("hits", {}).get("hit", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for h in hits:
        info = h.get("info", {})
        ee = info.get("ee")
        ees = ee if isinstance(ee, list) else ([ee] if ee else [])
        au = info.get("authors", {}).get("author", [])
        if isinstance(au, dict):
            au = [au]
        authors = [a.get("text", "") if isinstance(a, dict) else str(a) for a in au]
        out.append({
            "title": clean(info.get("title", "")),
            "year": info.get("year"),
            "venue": info.get("venue", ""),
            "doi": info.get("doi"),
            "ee": ees,
            "authors": authors,
        })
    return out


def dblp_best(title: str, authors: list[str] | None = None,
              year: str | int | None = None) -> dict | None:
    """Confirm a DBLP hit via fuzzy title (+ author surname / year signals)."""
    cands = dblp_search(title)
    tgt_surn = {surname(a) for a in (authors or [])} - {""}
    best, best_score = None, 0.0
    for c in cands:
        ratio = _title_ratio(title, c["title"])
        c_surn = {surname(a) for a in c["authors"]} - {""}
        overlap = len(tgt_surn & c_surn)
        year_ok = bool(year and c.get("year") and str(year) == str(c["year"]))
        accept = ratio >= 0.90 or (ratio >= 0.78 and (overlap or year_ok))
        score = ratio + 0.05 * overlap + (0.03 if year_ok else 0)
        if accept and score > best_score:
            best, best_score = c, score
    return best


def unpaywall_pdf(doi: str, email: str) -> str | None:
    """Return a downloadable OA PDF URL for a DOI, if Unpaywall knows one."""
    if not doi:
        return None
    try:
        r = requests.get(f"{UNPAYWALL}{doi}", params={"email": email},
                         headers=HEADERS, timeout=45)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code != 200:
        return None
    d = r.json()
    locs = d.get("oa_locations") or []
    best = d.get("best_oa_location") or {}
    for cand in [best, *locs]:
        u = (cand or {}).get("url_for_pdf")
        if u:
            return u
    return None


def arxiv_pdf(title: str, authors: list[str] | None = None,
              sleep: float = 3.0) -> str | None:
    """Find an arXiv preprint for a title (confirmed by title ratio + author)."""
    words = re.findall(r"[A-Za-z0-9]+", clean(title))
    phrase = " ".join(words[:14])
    if not phrase:
        return None
    for attempt in range(4):
        try:
            r = requests.get(ARXIV_API, params={"search_query": f'ti:"{phrase}"',
                             "max_results": 8}, headers=HEADERS, timeout=45)
        except Exception:  # noqa: BLE001
            time.sleep(8 * (attempt + 1))
            continue
        if r.status_code == 200:
            break
        if r.status_code in (429, 503):
            time.sleep(20 * (attempt + 1))
            continue
        return None
    else:
        return None
    time.sleep(sleep)
    tgt_surn = {surname(a) for a in (authors or [])} - {""}
    best, best_score = None, 0.0
    for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
        idm = re.search(r"<id>(.*?)</id>", e)
        tm = re.search(r"<title>(.*?)</title>", e, re.S)
        if not idm or not tm:
            continue
        ratio = _title_ratio(title, tm.group(1))
        names = re.findall(r"<name>(.*?)</name>", e)
        overlap = len({surname(n) for n in names} & tgt_surn)
        if (ratio >= 0.92 or (ratio >= 0.80 and overlap)) and ratio + 0.05 * overlap > best_score:
            best = idm.group(1).rsplit("/abs/", 1)[-1]
            best_score = ratio + 0.05 * overlap
    return f"https://arxiv.org/pdf/{best}" if best else None


def git_email(default: str = "research@localhost") -> str:
    """Contact email for Unpaywall - reuse the repo's git identity."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(DOCS_ROOT), "config", "user.email"], text=True).strip()
        return out or default
    except Exception:  # noqa: BLE001
        return default
