#!/usr/bin/env python3
"""Harvester for the **BORO research corpus** — Chris Partridge, Sergio de Cesare
and colleagues on extensionalism, 4D ontology and re-engineering data models.

`scripts/gap-audit.py --topic temporality-ontology` rated *BORO / IDEAS /
extensionalism* as covered only through third-party surveys: the library holds
Partridge's CDBB reports and the 4D-SETL paper, but not the body of work that
develops the methodology itself. BORO Solutions publishes that corpus at
https://research.borosolutions.net/.

**Why this script does not read that site.** Its `robots.txt` allows crawling
(`Allow: /`, `Content-Signal: search=yes, use=reference`, which is exactly what a
local search index is), but the host sits behind Cloudflare bot management and
answers every unattended request — including `/sitemap.xml` — with an
interstitial challenge (HTTP 403, "Just a moment..."). Working around a bot
challenge is not something a harvester should do, so we take the legitimate
route instead: the *same works* are indexed by **OpenAlex**, and open copies are
served by publisher OA locations, institutional repositories and arXiv. That
also gives us proper metadata (DOI, year, venue) rather than scraped filenames.

Seeds are therefore OpenAlex identities, not URLs:

  * author ids for the recurring BORO authors, and
  * an affiliation search on ``raw_affiliation_strings`` ("BORO Solutions"),
    which catches co-authors we do not name explicitly.

**Author ids are not sufficient on their own.** OpenAlex has merged homonyms
into both author profiles: "Chris Partridge" also carries a 1950s *Neurospora
crassa* geneticist and a human-cytogenetics author, and "Sergio de Cesare" also
carries stock-sentiment and marine-biology papers. So every candidate must also
pass a topical filter (``ON_TOPIC``) before it is fetched; works that fail are
kept in the checkpoint with status ``off_topic`` rather than dropped silently, so
the filter itself stays auditable in the CSV report. Affiliation-seed hits are
precise by construction and bypass the filter.

OpenAlex returns byte-identical duplicate records for some works, so entries are
de-duplicated on DOI first and normalised title second, then checked against the
live index so anything already in the garden is skipped.

Downloads land in ``Inbox/boro/<section>/``, from where ``import-downloads.py``
files them into ``Literature/`` and the indexer picks them up. Resumable via a
JSON checkpoint; writes a CSV report.

Pipeline:
  1. gather   - query the seeds, de-duplicate, flag works already in the index.
  2. resolve  - for works with no OA PDF in OpenAlex, look for an open copy.
  3. download - fetch everything resolved.

Usage:
  scripts/.venv/bin/python scripts/boro-research.py all
  scripts/.venv/bin/python scripts/boro-research.py gather
  scripts/.venv/bin/python scripts/boro-research.py resolve --limit 20
  scripts/.venv/bin/python scripts/boro-research.py download --limit 20
  scripts/.venv/bin/python scripts/boro-research.py list --section partridge
  scripts/.venv/bin/python scripts/boro-research.py report
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "boro"
CKPT = OUT_DIR / "_boro.json"
REPORT = OUT_DIR / "_boro-report.csv"
OPENALEX_WORKS = "https://api.openalex.org/works"
PAGE_SIZE = 200
DL_SLEEP = 0.7
RESOLVE_SLEEP = 0.4
API_SLEEP = 0.4

# Work types that are not papers: OpenAlex files prefaces, editorials and
# indexing artefacts as works, and they carry no content worth a library slot.
DROP_TYPES = {"paratext", "editorial", "erratum", "letter", "peer-review",
              "grant", "retraction"}
DROP_TITLE_RE = re.compile(
    r"^\s*(preface|foreword|front\s+matter|back\s+matter|editorial|"
    r"table\s+of\s+contents|author\s+index|abstracts of meeting|"
    r"introduction to the special)\b", re.I)

# The vocabulary of the corpus we actually want: ontology engineering,
# conceptual modelling, 4D/extensionalism, enterprise and legacy data
# integration. This is what separates the ontologist from his homonyms.
ON_TOPIC = re.compile(r"""
    ontolog | ontologi[sz] | conceptual\s+(model|schema) | schema\s+turn
  | four[-\s]?dimension | \b4d\b | \b3d\b | perdurant | endurant | extensional
  | mereolog | composition | multi[-\s]?level\s+model | classification\s+pattern
  | \bboro\b | \bideas\b | iso\s*15926 | \bhqdm\b | foundation(al)?\s+(data\s+)?model
  | enterprise\s+(ontolog|integration|architect|comput|model)
  | business\s+object | legacy | semantic\s+(integration|interoperab|web|heterogen)
  | information\s+(model|system|base) | data\s+(model|integration|infrastructure)
  | digital\s+twin | reference\s+data | top[-\s]?level\s+ontolog
  | metaphysic | regimenting | identity | persistence | temporal
  | coordinate\s+system | spatial\s+object | uncertain\s+information
  | nomenclature\s+ontolog | agentology | debits\s+and\s+credits
  | model\s+(quality|reuse) | simulation\s+(model|component) | epistemic
  | requirements | taxonom | pattern\s+language | uniclass
""", re.I | re.X)

# The years the merged geneticist profile occupies; nothing from the BORO corpus
# predates the 1996 monograph, so an early date is corroborating evidence.
ON_TOPIC_YEAR_FLOOR = 1990


@dataclass
class Seed:
    section: str
    label: str
    filter: str                   # an OpenAlex ``filter`` expression
    note: str = ""


# The recurring authors of the BORO corpus. Author ids were confirmed against
# their publication lists (extensionalism, 4D ontology, conceptual modelling) —
# OpenAlex holds several homonyms for both names, so the ids matter.
SEEDS: list[Seed] = [
    Seed("partridge", "Chris Partridge (BORO Solutions)",
         "author.id:A5102965201",
         note="Author of 'Business Objects: Re-engineering for Re-use'; the "
              "origin of BORO's 4D/extensionalist commitment"),
    Seed("decesare", "Sergio de Cesare (Westminster)",
         "author.id:A5071422923",
         note="Partridge's long-standing co-author on extensional conceptual "
              "modelling and ontology-driven software engineering"),
    Seed("affiliation", "Works affiliated to BORO Solutions",
         "raw_affiliation_strings.search:BORO Solutions",
         note="Catches co-authors not named explicitly above"),
]

SELECT = ("id,doi,title,display_name,publication_year,type,authorships,"
          "best_oa_location,locations,open_access,primary_location")


@dataclass
class Work:
    section: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str = ""
    openalex_id: str = ""
    type: str = ""
    kind: str = "pdf"
    note: str = ""
    # runtime state
    in_index: bool | None = None
    pdf_url: str | None = None
    source: str | None = None
    status: str = "pending"


# ---------------------------------------------------------------------------
# 1. gather
# ---------------------------------------------------------------------------

def _openalex_page(filt: str, cursor: str, email: str) -> dict:
    params = {"filter": filt, "per-page": PAGE_SIZE, "cursor": cursor,
              "select": SELECT}
    if email:
        params["mailto"] = email
    for attempt in range(4):
        try:
            r = requests.get(OPENALEX_WORKS, params=params,
                             headers=pf.HEADERS, timeout=60)
        except Exception:  # noqa: BLE001
            time.sleep(4 * (attempt + 1))
            continue
        if r.status_code == 200:
            time.sleep(API_SLEEP)
            return r.json()
        if r.status_code in (429, 503):
            time.sleep(10 * (attempt + 1))
            continue
        raise RuntimeError(f"OpenAlex HTTP {r.status_code} for {filt}")
    raise RuntimeError(f"OpenAlex unreachable for {filt}")


def _works_for(seed: Seed, email: str) -> list[dict]:
    out, cursor = [], "*"
    while cursor:
        page = _openalex_page(seed.filter, cursor, email)
        out.extend(page.get("results") or [])
        cursor = (page.get("meta") or {}).get("next_cursor")
        if not page.get("results"):
            break
    return out


def _as_work(seed: Seed, w: dict) -> Work | None:
    title = pf.clean(w.get("title") or w.get("display_name") or "")
    if not title or DROP_TITLE_RE.match(title):
        return None
    if (w.get("type") or "") in DROP_TYPES:
        return None
    authors = [(a.get("author") or {}).get("display_name", "")
               for a in (w.get("authorships") or [])]
    rec = Work(
        section=seed.section,
        title=title,
        authors=[a for a in authors if a],
        year=w.get("publication_year"),
        doi=(w.get("doi") or "").replace("https://doi.org/", ""),
        openalex_id=(w.get("id") or "").rsplit("/", 1)[-1],
        type=w.get("type") or "",
    )
    if seed.section != "affiliation" and not _on_topic(rec):
        rec.status = "off_topic"
        return rec
    urls = pf._openalex_locations(w)
    if urls:
        rec.pdf_url, rec.source, rec.status = urls[0], "openalex", "resolved"
    return rec


def _on_topic(rec: Work) -> bool:
    if rec.year and rec.year < ON_TOPIC_YEAR_FLOOR:
        return False
    return bool(ON_TOPIC.search(rec.title))


def gather(dedup: bool) -> list[dict]:
    email = pf.git_email()
    recs: list[Work] = []
    seen_doi: set[str] = set()
    seen_title: set[str] = set()
    for seed in SEEDS:
        raw = _works_for(seed, email)
        kept = 0
        for w in raw:
            rec = _as_work(seed, w)
            if rec is None:
                continue
            key_doi = rec.doi.lower()
            key_title = pf.norm(rec.title)
            if (key_doi and key_doi in seen_doi) or key_title in seen_title:
                continue
            if key_doi:
                seen_doi.add(key_doi)
            seen_title.add(key_title)
            recs.append(rec)
            kept += 1
        print(f"  {seed.section:12s} {len(raw):4d} works -> {kept:4d} new  "
              f"({seed.label})")
    out = [asdict(r) for r in recs]
    off = sum(1 for r in out if r["status"] == "off_topic")
    with_pdf = sum(1 for r in out if r["pdf_url"])
    print(f"gathered {len(out)} distinct works; {off} filtered as off-topic "
          f"(homonym profiles), {with_pdf} of the rest already carry an "
          f"OpenAlex OA PDF link")
    if dedup:
        idx = pf.IndexDedup()
        for r in out:
            if r["status"] == "off_topic":
                continue
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in out if r['in_index'])} already in the search index")
    return out


# ---------------------------------------------------------------------------
# 2. resolve
# ---------------------------------------------------------------------------

def resolve_one(r: dict, email: str) -> None:
    """Find an open copy for a work OpenAlex has no PDF location for."""
    if r.get("doi"):
        up = pf.unpaywall_pdf(r["doi"], email)
        if up:
            r["pdf_url"], r["source"], r["status"] = up, "unpaywall", "resolved"
            return
    ax = pf.arxiv_pdf(r["title"], r.get("authors") or [])
    if ax:
        r["pdf_url"], r["source"], r["status"] = ax, "arxiv", "resolved"
        return
    r["status"] = "unresolved"


def resolve(records: list[dict], limit: int | None) -> None:
    todo = [r for r in records
            if not r.get("in_index") and not r.get("pdf_url")
            and r.get("status") in ("pending", "unresolved")]
    if limit:
        todo = todo[:limit]
    if not todo:
        print("nothing to resolve (every work has a URL or is already indexed)")
        return
    print(f"resolving open copies for {len(todo)} works without an OA location...")
    email = pf.git_email()
    for i, r in enumerate(todo, 1):
        try:
            resolve_one(r, email)
        except Exception as exc:  # noqa: BLE001
            r["status"] = "unresolved"
            print(f"[{i}/{len(todo)}] ERR {type(exc).__name__} {r['title'][:55]}")
            continue
        print(f"[{i}/{len(todo)}] {(r['source'] or '--'):10s} {r['title'][:64]}")
        if i % 10 == 0:
            save_ckpt(records)
        time.sleep(RESOLVE_SLEEP)
    save_ckpt(records)


# ---------------------------------------------------------------------------
# 3. download
# ---------------------------------------------------------------------------

def download(records: list[dict], limit: int | None) -> None:
    targets = [r for r in records if r.get("pdf_url") and not r.get("in_index")
               and r.get("status") in ("resolved", "dl_failed")]
    if limit:
        targets = targets[:limit]
    print(f"downloading {len(targets)} works -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        stem = pf.safe_stem(r.get("authors") or [], r["title"])
        dest = OUT_DIR / r["section"] / f"{stem}.pdf"
        got, msg = pf.download_pdf(sess, r["pdf_url"], dest)
        if got:
            r["status"] = "downloaded"
            ok += 1
            print(f"[{i}/{len(targets)}] OK  ({r['source']}) {dest.name}  ({msg})")
        else:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:52]}  ({msg})")
        if i % 10 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


# ---------------------------------------------------------------------------
# checkpoint / report
# ---------------------------------------------------------------------------

def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "status", "in_index", "source", "year", "title",
                    "authors", "type", "doi", "openalex_id", "url"])
        for r in records:
            w.writerow([r["section"], r.get("status", ""), r.get("in_index"),
                        r.get("source") or "", r.get("year") or "", r["title"],
                        "; ".join(r.get("authors", [])), r.get("type", ""),
                        r.get("doi", ""), r.get("openalex_id", ""),
                        r.get("pdf_url") or ""])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    by_status = Counter(r.get("status", "") for r in records)
    print(f"\n=== {len(records)} works ===")
    for k, v in sorted(by_status.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4d}  {k}")
    print("\nby section:")
    for sec in {r["section"] for r in records}:
        rows = [r for r in records if r["section"] == sec]
        got = sum(1 for r in rows if r.get("status") == "downloaded")
        print(f"  {sec:12s} {len(rows):4d} works, {got:4d} downloaded")
    print(f"\nreport: {REPORT.relative_to(DOCS_ROOT)}")


def cmd_list(records: list[dict], section: str | None) -> int:
    for r in records:
        if section and r["section"] != section:
            continue
        flag = "idx" if r.get("in_index") else (r.get("status") or "")[:10]
        print(f"{r['section']:12s} {str(r.get('year') or '----'):4s} "
              f"{flag:10s} {r['title'][:80]}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("stage", choices=["all", "gather", "resolve", "download",
                                     "list", "report"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--section", default=None)
    p.add_argument("--no-dedup", action="store_true",
                   help="do not skip works already in the search index")
    args = p.parse_args(argv)

    if args.stage in ("gather", "all"):
        records = gather(dedup=not args.no_dedup)
        save_ckpt(records)
    else:
        records = load_ckpt()
        if not records:
            print("no checkpoint — run 'gather' first", file=sys.stderr)
            return 1

    if args.stage in ("resolve", "all"):
        resolve(records, args.limit)
    if args.stage in ("download", "all"):
        download(records, args.limit)
    if args.stage == "list":
        return cmd_list(records, args.section)

    print_summary(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
