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
  * best-effort *metadata -> PDF* resolvers — the common OA backends
    **arXiv** (https://arxiv.org/), **Unpaywall** (https://unpaywall.org/) and
    **OpenAlex** (https://openalex.org/), plus DBLP title search — for listings
    that give only citations.

``arxiv``/``dblp`` only really cover computer science. **OpenAlex** is the
cross-domain fallback: it indexes philosophy, engineering standards and
grey literature (institutional repositories, PhilArchive, Zenodo, …) that the
CS-centric backends miss, and exposes an OA PDF location per work.

Ad-hoc lookup (no harvester run):

  scripts/.venv/bin/python scripts/paperfetch.py lookup --title "…"
  scripts/.venv/bin/python scripts/paperfetch.py lookup --doi 10.…

Everything degrades gracefully: if the index is missing, dedup simply returns
"not present"; if a resolver host is down, it returns ``None`` and the caller
records the paper as unresolved.
"""

from __future__ import annotations

import difflib
import html
import os
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
OPENALEX_API = "https://api.openalex.org/works"
SEMANTICSCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"


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
    """Turn landing-page URLs into direct-PDF URLs where we can.

    * arXiv ``/abs/`` -> ``/pdf/``.
    * Wayback snapshots get the ``id_`` timestamp modifier, which returns the
      *original* archived bytes instead of the rewritten HTML wrapper the plain
      snapshot URL serves (without it an archived PDF arrives as a web page).
    """
    url = url.strip()
    m = re.match(r"https?://arxiv\.org/abs/([^?#]+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    # The old AAAI Press host 403s on its own proceedings; the CDN serves the
    # same files under an identical path. OpenAlex still hands out the old URLs.
    url = re.sub(r"^https?://(?:www\.)?aaaipress\.org/", "https://cdn.aaai.org/", url)
    m = re.match(r"(https?://web\.archive\.org/web/)(\d+)(/)(https?://.*)", url)
    if m and not m.group(2).endswith("id_"):
        return f"{m.group(1)}{m.group(2)}id_/{m.group(4)}"
    return url


_CITATION_PDF_RE = re.compile(
    r"""<meta[^>]+(?:name|property)\s*=\s*["'](?:citation_pdf_url|eprints\.document_url)["']"""
    r"""[^>]*?content\s*=\s*["']([^"']+)["']""", re.I)
_CITATION_PDF_REV_RE = re.compile(
    r"""<meta[^>]+content\s*=\s*["']([^"']+)["'][^>]*?"""
    r"""(?:name|property)\s*=\s*["'](?:citation_pdf_url|eprints\.document_url)["']""", re.I)


def pdf_from_landing_page(body: bytes, base_url: str) -> str | None:
    """The publisher-declared PDF link on a landing page, if it names one.

    Repository platforms (DSpace, EPrints, Pure, OJS) emit Google-Scholar
    citation metadata, in which ``citation_pdf_url`` points at the actual file.
    Institutional repositories routinely answer a "PDF" URL with their landing
    page, so honouring that tag is what turns those near-misses into downloads —
    and it uses the link the publisher itself advertises rather than guessing.
    """
    try:
        text = body[:400_000].decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None
    for rx in (_CITATION_PDF_RE, _CITATION_PDF_REV_RE):
        m = rx.search(text)
        if m:
            return requests.compat.urljoin(base_url, html.unescape(m.group(1)))
    return None


# A repository that answers a PDF request with HTTP 200 and a JS proof-of-work
# page or a CAPTCHA is not misconfigured and is not serving a landing page — it
# has decided this client is a robot. Saying so distinguishes "needs a smarter
# hop" from "needs a browser", which is the difference between a bug worth fixing
# and a wall worth recording.
_CHALLENGE_RE = re.compile(
    r"not a bot|captcha challenge|enable javascript and cookies"
    r"|checking your browser|unusual traffic from your client", re.I)


def download_pdf(sess: requests.Session, url: str, dest: Path,
                 timeout: int = 90, follow_landing: bool = True) -> tuple[bool, str]:
    """Fetch ``url`` to ``dest`` iff the body is a real PDF. Idempotent.

    When the response is HTML and ``follow_landing`` is set, take one hop via
    the page's ``citation_pdf_url`` before giving up.
    """
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
        if follow_landing and "html" in ctype:
            hop = pdf_from_landing_page(data, r.url)
            if hop and normalize_pdf_url(hop) != url:
                ok, msg = download_pdf(sess, hop, dest, timeout,
                                       follow_landing=False)
                return ok, (f"via landing page, {msg}" if ok else f"landing hop: {msg}")
        if _CHALLENGE_RE.search(data[:20_000].decode("utf-8", "ignore")):
            return False, "bot challenge (JS/CAPTCHA)"
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


# Hosts that publish open-access PDFs but refuse automated clients outright
# (Cloudflare / Akamai bot walls that a User-Agent cannot talk past). An OA
# record pointing only here is *legally* open and *practically* unreachable, so
# prefer any repository mirror of the same article before falling back to it.
BOT_WALLED_HOSTS = (
    "dl.acm.org", "ieeexplore.ieee.org", "link.springer.com",
    "www.sciencedirect.com", "onlinelibrary.wiley.com", "www.tandfonline.com",
    "journals.sagepub.com", "academic.oup.com", "www.researchgate.net",
)


def is_bot_walled(url: str) -> bool:
    return any(h in url.lower() for h in BOT_WALLED_HOSTS)


def unpaywall_locations(doi: str, email: str) -> list[str]:
    """Every OA PDF URL Unpaywall knows for a DOI, most fetchable first."""
    if not doi:
        return []
    try:
        r = requests.get(f"{UNPAYWALL}{doi}", params={"email": email},
                         headers=HEADERS, timeout=45)
    except Exception:  # noqa: BLE001
        return []
    if r.status_code != 200:
        return []
    d = r.json()
    best = d.get("best_oa_location") or {}
    out: list[str] = []
    for cand in [best, *(d.get("oa_locations") or [])]:
        u = (cand or {}).get("url_for_pdf")
        if u and u not in out:
            out.append(u)
    return sorted(out, key=is_bot_walled)


def unpaywall_pdf(doi: str, email: str) -> str | None:
    """Return a downloadable OA PDF URL for a DOI, if Unpaywall knows one."""
    locs = unpaywall_locations(doi, email)
    return locs[0] if locs else None


def _openalex_locations(work: dict) -> list[str]:
    """Every OA PDF URL an OpenAlex work record offers, best first."""
    out: list[str] = []
    best = work.get("best_oa_location") or {}
    for loc in [best, *(work.get("locations") or [])]:
        if not isinstance(loc, dict):
            continue
        for key in ("pdf_url", "landing_page_url"):
            u = loc.get(key)
            # Only trust landing pages that are already PDF-shaped.
            if u and (key == "pdf_url" or u.lower().endswith(".pdf")):
                if u not in out:
                    out.append(u)
    return out


def openalex_best(title: str, authors: list[str] | None = None,
                  year: str | int | None = None, email: str = "",
                  sleep: float = 0.4) -> dict | None:
    """OpenAlex title search -> best confirmed work record.

    The cross-domain counterpart to :func:`dblp_best`: OpenAlex covers
    philosophy, engineering and grey literature that DBLP/arXiv do not.
    Confirmation uses the same fuzzy-title + author-surname + year signals.
    """
    q = " ".join(re.findall(r"[A-Za-z0-9]+", clean(title))[:20])
    if not q:
        return None
    params = {"search": q, "per-page": 8}
    if email:
        params["mailto"] = email
    for attempt in range(3):
        try:
            r = requests.get(OPENALEX_API, params=params, headers=HEADERS, timeout=45)
        except Exception:  # noqa: BLE001
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code == 200:
            break
        if r.status_code in (429, 503):
            time.sleep(10 * (attempt + 1))
            continue
        return None
    else:
        return None
    time.sleep(sleep)
    try:
        results = r.json().get("results", [])
    except Exception:  # noqa: BLE001
        return None

    tgt_surn = {surname(a) for a in (authors or [])} - {""}
    best, best_score = None, 0.0
    for w in results:
        cand_title = clean(w.get("title") or w.get("display_name") or "")
        if not cand_title:
            continue
        ratio = _title_ratio(title, cand_title)
        names = [(a.get("author") or {}).get("display_name", "")
                 for a in (w.get("authorships") or [])]
        overlap = len({surname(n) for n in names if n} & tgt_surn)
        year_ok = bool(year and w.get("publication_year")
                       and str(year) == str(w["publication_year"]))
        accept = ratio >= 0.90 or (ratio >= 0.78 and (overlap or year_ok))
        score = ratio + 0.05 * overlap + (0.03 if year_ok else 0)
        if accept and score > best_score:
            best, best_score = w, score
    if not best:
        return None
    return {
        "title": clean(best.get("title") or best.get("display_name") or ""),
        "year": best.get("publication_year"),
        "doi": (best.get("doi") or "").replace("https://doi.org/", "") or None,
        "is_oa": bool(best.get("open_access", {}).get("is_oa")),
        "pdf_urls": _openalex_locations(best),
        "type": best.get("type"),
    }


def openalex_pdf(title: str, authors: list[str] | None = None,
                 year: str | int | None = None, email: str = "") -> str | None:
    """Best OA PDF URL for a title via OpenAlex, or ``None``."""
    hit = openalex_best(title, authors, year, email)
    if not hit:
        return None
    urls = hit.get("pdf_urls") or []
    return urls[0] if urls else None


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


def semanticscholar_pdf(title: str, authors: list[str] | None = None,
                        year: str | int | None = None, sleep: float = 1.2) -> str | None:
    """Open-access PDF for a title via Semantic Scholar, or ``None``.

    Worth having alongside OpenAlex and Unpaywall because its `openAccessPdf`
    frequently points at an **author or institutional-repository copy** that the
    other two miss — which is exactly the shape of the gap left after a harvest
    round: papers whose publisher copy is paywalled but whose author posted a PDF.

    **Requires ``SEMANTICSCHOLAR_API_KEY``.** Measured 2026-08-14: the
    unauthenticated tier 429s every request from this network, so retrying it
    costs ~150 s per title and yields nothing. Rather than slow every harvest
    down for no papers, the resolver returns ``None`` immediately when no key is
    set. Request a free key at https://www.semanticscholar.org/product/api and
    export it to switch this backend on.

    Confirmed the same way as the other resolvers (title ratio plus author
    surname overlap) so a fuzzy keyword match cannot smuggle in the wrong paper.
    """
    api_key = os.environ.get("SEMANTICSCHOLAR_API_KEY", "").strip()
    if not title or not api_key:
        return None
    headers = {**HEADERS, "x-api-key": api_key}
    params = {"query": clean(title)[:280], "limit": 8,
              "fields": "title,year,authors,openAccessPdf,externalIds"}
    data = None
    for attempt in range(3):
        try:
            r = requests.get(SEMANTICSCHOLAR_API, params=params, headers=headers, timeout=45)
        except Exception:  # noqa: BLE001
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 200:
            data = r.json()
            break
        if r.status_code in (429, 503):
            time.sleep(5 * (attempt + 1))
            continue
        return None
    time.sleep(sleep)
    if not data:
        return None

    tgt_surn = {surname(a) for a in (authors or [])} - {""}
    best, best_score = None, 0.0
    for paper in data.get("data") or []:
        oa = (paper.get("openAccessPdf") or {}).get("url")
        if not oa:
            continue
        ratio = _title_ratio(title, paper.get("title") or "")
        names = [a.get("name", "") for a in paper.get("authors") or []]
        overlap = len({surname(n) for n in names} & tgt_surn)
        if year and paper.get("year") and abs(int(paper["year"]) - int(year)) > 2:
            continue
        score = ratio + 0.05 * overlap
        if (ratio >= 0.92 or (ratio >= 0.80 and overlap)) and score > best_score:
            best, best_score = oa, score
    return best


def git_email(default: str = "research@localhost") -> str:
    """Contact email for Unpaywall - reuse the repo's git identity."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(DOCS_ROOT), "config", "user.email"], text=True).strip()
        return out or default
    except Exception:  # noqa: BLE001
        return default


def lookup(title: str | None = None, doi: str | None = None,
           authors: list[str] | None = None) -> dict:
    """Ad-hoc OA / preprint lookup via Unpaywall (DOI) and/or arXiv (title).

    Returns a dict with keys ``arxiv_url``, ``unpaywall_url``, ``openalex_url``,
    ``dblp`` (best hit or None). Missing inputs simply skip that resolver.
    """
    out: dict = {"title": title or "", "doi": doi or "", "arxiv_url": None,
                 "unpaywall_url": None, "openalex_url": None, "s2_url": None,
                 "dblp": None}
    if doi:
        out["unpaywall_url"] = unpaywall_pdf(doi, git_email())
    if title:
        out["arxiv_url"] = arxiv_pdf(title, authors)
        out["openalex_url"] = openalex_pdf(title, authors, email=git_email())
        out["s2_url"] = semanticscholar_pdf(title, authors)
        hit = dblp_best(title, authors)
        if hit:
            out["dblp"] = {
                "title": hit.get("title"),
                "year": hit.get("year"),
                "venue": hit.get("venue"),
                "doi": hit.get("doi"),
                "ee": hit.get("ee"),
            }
            # If the caller gave no DOI, try Unpaywall from the DBLP hit.
            if not doi and hit.get("doi"):
                out["doi"] = hit["doi"]
                out["unpaywall_url"] = unpaywall_pdf(hit["doi"], git_email())
    return out


# ---------------------------------------------------------------------------
# CLI — ad-hoc lookup
# ---------------------------------------------------------------------------

def _cli(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    p = argparse.ArgumentParser(
        description="Shared paper-fetch helpers. Subcommand: lookup")
    sub = p.add_subparsers(dest="cmd", required=True)
    lu = sub.add_parser("lookup", help="resolve a title/DOI to an OA or arXiv PDF")
    lu.add_argument("--title", default=None, help="paper title (arXiv + DBLP)")
    lu.add_argument("--doi", default=None, help="DOI (Unpaywall)")
    lu.add_argument("--author", action="append", default=[],
                    help="author name(s); repeatable; sharpens arXiv/DBLP match")
    lu.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = p.parse_args(argv)

    if args.cmd == "lookup":
        if not args.title and not args.doi:
            p.error("lookup needs --title and/or --doi")
        result = lookup(title=args.title, doi=args.doi, authors=args.author or None)
        if args.json:
            print(_json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(f"title:     {result['title'] or '(none)'}")
        print(f"doi:       {result['doi'] or '(none)'}")
        print(f"arxiv:     {result['arxiv_url'] or '(none)'}")
        print(f"unpaywall: {result['unpaywall_url'] or '(none)'}")
        print(f"openalex:  {result['openalex_url'] or '(none)'}")
        if result["dblp"]:
            d = result["dblp"]
            print(f"dblp:      {d.get('year')} {d.get('venue')} — {d.get('title')}")
            print(f"           doi={d.get('doi')} ee={d.get('ee')}")
        else:
            print("dblp:      (none)")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
