#!/usr/bin/env python3
"""Harvest the papers of Matei Zaharia, Reynold Xin, and Snowflake's founding
technical staff (Dageville, Cruanes, Żukowski).

Enumeration: Google Scholar for Zaharia
(``citations?user=I1EvjZsAAAAJ``, the profile the harvest was pointed at) and
Xin; OpenAlex for the Snowflake trio, because Scholar's author-search page is
captcha-walled from this network. Patents and trademark filings are dropped.
Each title is resolved through ``paperfetch`` (arXiv → OpenAlex OA → Unpaywall
via DBLP DOI) and skipped when the search index already holds it.

    scripts/.venv/bin/python scripts/scholar-authors.py all
    scripts/.venv/bin/python scripts/scholar-authors.py all --only zaharia
    scripts/.venv/bin/python scripts/scholar-authors.py gather|resolve|download
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import requests
import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCHOLAR = "https://scholar.google.com/citations"
OPENALEX = "https://api.openalex.org"
CACHE = ROOT / "imports"
DL_SLEEP = 0.6
RESOLVE_SLEEP = 0.05

DROP_VENUE = re.compile(r"\bpatent|\buspto\b|\bwipo\b|trademark|patent office", re.I)
DROP_TITLE = re.compile(
    r"\bpatent application\b|^us\s*\d{7,}|trademark|"
    r"pzpr|październik|składek członkowskich|nursing mobile robot|"
    r"humanoid medical|robotic medical assist|pacjent",
    re.I,
)
SKIP_OA_TYPE = {"paratext", "erratum", "letter", "editorial"}

PROFILES = [
    {
        "key": "zaharia",
        "who": "Matei Zaharia",
        "scholar": "I1EvjZsAAAAJ",
        "folder": "zaharia",
    },
    {
        "key": "rxin",
        "who": "Reynold Xin",
        "scholar": "X22nUYgAAAAJ",
        "folder": "rxin-pubs",
    },
    {
        "key": "dageville",
        "who": "Benoît Dageville",
        "openalex": "A5004037878",
        "folder": "snowflake-staff",
    },
    {
        "key": "cruanes",
        "who": "Thierry Cruanes",
        "openalex": "A5084497894",
        "folder": "snowflake-staff",
    },
    {
        "key": "zukowski",
        "who": "Marcin Żukowski",
        "openalex": "A5061001401",
        "folder": "snowflake-staff",
    },
]


def _text(fragment: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))
    return re.sub(r"\s+", " ", plain).strip()


def _authors(blob: str) -> list[str]:
    parts = [a.strip() for a in re.split(r",| and ", blob or "") if a.strip()]
    out = []
    for a in parts[:8]:
        tok = a.split()
        out.append(tok[-1] if tok else a)
    return out or ["Unknown"]


def scholar_profile(sess, user: str, pagesize: int = 100,
                    max_pages: int = 8) -> list[dict]:
    cache = CACHE / f"scholar-{user}.json"
    rows: list[dict] = []
    blocked = False
    for start in range(0, pagesize * max_pages, pagesize):
        params = {
            "user": user, "hl": "en", "view_op": "list_works",
            "sortby": "pubdate", "cstart": start, "pagesize": pagesize,
        }
        try:
            body = sess.get(SCHOLAR, params=params, timeout=60).text
        except Exception as exc:  # noqa: BLE001
            print(f"  [scholar] {user} page {start} failed ({type(exc).__name__})")
            blocked = True
            break
        if "gsc_a_tr" not in body:
            if start == 0:
                print(f"  [scholar] {user} returned no publication rows")
                blocked = True
            break
        page_rows = []
        for row in re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', body, re.S):
            tm = re.search(r'class="gsc_a_at"[^>]*>(.*?)</a>', row, re.S)
            grey = re.findall(r'class="gs_gray">(.*?)</div>', row, re.S)
            ym = re.search(r'class="gsc_a_h[^"]*"[^>]*>(.*?)</span>', row, re.S)
            title = _text(tm.group(1)) if tm else ""
            if not title:
                continue
            page_rows.append({
                "title": title,
                "authors": _text(grey[0]) if grey else "",
                "venue": _text(grey[1]) if len(grey) > 1 else "",
                "year": _text(ym.group(1)) if ym else "",
            })
        rows += page_rows
        if len(page_rows) < pagesize:
            break
        time.sleep(3.0)
    if rows:
        seen, uniq = set(), []
        for r in rows:
            k = pf.norm(r["title"])
            if k and k not in seen:
                seen.add(k)
                uniq.append(r)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(uniq, indent=1), encoding="utf-8")
        print(f"  [scholar] {user}: {len(uniq)} publications")
        return uniq
    if blocked and cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        print(f"  [scholar] {user}: using cache ({len(cached)} works)")
        return cached
    return []


def openalex_works(sess, author_id: str) -> list[dict]:
    cache = CACHE / f"openalex-{author_id}.json"
    rows, cursor = [], "*"
    while cursor:
        r = sess.get(
            f"{OPENALEX}/works",
            params={
                "filter": f"author.id:{author_id}",
                "per_page": 50,
                "cursor": cursor,
                "mailto": pf.git_email(),
            },
            timeout=40,
        )
        r.raise_for_status()
        payload = r.json()
        for w in payload.get("results") or []:
            wtype = (w.get("type") or "").lower()
            if wtype in SKIP_OA_TYPE:
                continue
            title = _text(w.get("display_name") or "")
            if not title:
                continue
            authors = [
                ((a.get("author") or {}).get("display_name") or "").split()[-1]
                for a in (w.get("authorships") or [])[:8]
                if (a.get("author") or {}).get("display_name")
            ]
            loc = w.get("best_oa_location") or w.get("primary_location") or {}
            pdf = loc.get("pdf_url") or (w.get("open_access") or {}).get("oa_url")
            doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
            venue = ((w.get("primary_location") or {}).get("source") or {}).get(
                "display_name") or ""
            rows.append({
                "title": title, "authors": ", ".join(authors),
                "venue": venue, "year": str(w.get("publication_year") or ""),
                "doi": doi, "oa_url": pdf,
            })
        cursor = (payload.get("meta") or {}).get("next_cursor")
        time.sleep(0.2)
    seen, uniq = set(), []
    for r in rows:
        k = pf.norm(r["title"])
        if k and k not in seen:
            seen.add(k)
            uniq.append(r)
    cache.write_text(json.dumps(uniq, indent=1), encoding="utf-8")
    print(f"  [openalex] {author_id}: {len(uniq)} works")
    return uniq


def keep(rec: dict) -> bool:
    if DROP_TITLE.search(rec.get("title") or ""):
        return False
    if DROP_VENUE.search(rec.get("venue") or ""):
        return False
    return True


def out_dir(folder: str) -> Path:
    return ROOT / "Inbox" / folder


def ckpt_path(folder: str) -> Path:
    return out_dir(folder) / f"_{folder}.json"


def report_path(folder: str) -> Path:
    return out_dir(folder) / f"_{folder}-report.csv"


def rec_of(profile: dict, item: dict) -> dict:
    authors = item.get("authors")
    if isinstance(authors, str):
        authors = _authors(authors)
    return {
        "who": profile["who"], "title": item["title"], "authors": authors,
        "venue": item.get("venue") or "", "year": item.get("year") or "",
        "doi": item.get("doi"), "url_override": item.get("oa_url") or None,
        "status": "pending", "how": "", "url": "", "file": "",
        "folder": profile["folder"],
    }


def gather(profiles: list[dict], dedup: bool) -> dict[str, list[dict]]:
    sess = pf.session()
    oa = pf.session()
    oa.headers["Accept"] = "application/json"
    by_folder: dict[str, list[dict]] = {}
    idx = pf.IndexDedup() if dedup else None
    for p in profiles:
        print(f"\n=== enumerate {p['who']} ===")
        if p.get("scholar"):
            items = scholar_profile(sess, p["scholar"])
        else:
            items = openalex_works(oa, p["openalex"])
        kept = [rec_of(p, it) for it in items if keep(it)]
        dropped = len(items) - len(kept)
        if dropped:
            print(f"  dropped {dropped} patents / trademark rows")
        # merge into folder (Snowflake trio share a drop zone)
        bucket = by_folder.setdefault(p["folder"], [])
        seen = {pf.norm(r["title"]) for r in bucket}
        for r in kept:
            k = pf.norm(r["title"])
            if k in seen:
                continue
            seen.add(k)
            if idx and idx.available and idx.contains(r["title"]):
                r["status"] = "held"
            bucket.append(r)
        print(f"  kept {len(kept)} → folder {p['folder']} now {len(bucket)}")
    for folder, records in by_folder.items():
        save_ckpt(folder, records)
    return by_folder


def arxiv_quick(title: str, authors: list[str]) -> str | None:
    """One-shot arXiv lookup. ``paperfetch.arxiv_pdf`` retries for minutes."""
    words = re.findall(r"[A-Za-z0-9]+", pf.clean(title))
    phrase = " ".join(words[:12])
    if len(phrase) < 12:
        return None
    try:
        r = requests.get(
            pf.ARXIV_API,
            params={"search_query": f'ti:"{phrase}"', "max_results": 5},
            headers=pf.HEADERS, timeout=12,
        )
        if r.status_code != 200:
            return None
    except Exception:  # noqa: BLE001
        return None
    tgt = {pf.surname(a) for a in authors} - {""}
    best, score = None, 0.0
    for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
        idm = re.search(r"<id>(.*?)</id>", e)
        tm = re.search(r"<title>(.*?)</title>", e, re.S)
        if not idm or not tm:
            continue
        ratio = pf._title_ratio(title, tm.group(1))
        names = re.findall(r"<name>(.*?)</name>", e)
        overlap = len({pf.surname(n) for n in names} & tgt)
        if (ratio >= 0.92 or (ratio >= 0.80 and overlap)) and ratio + 0.05 * overlap > score:
            best = idm.group(1).rsplit("/abs/", 1)[-1]
            score = ratio + 0.05 * overlap
    return f"https://arxiv.org/pdf/{best}" if best else None


def resolve_one(r: dict) -> tuple[str | None, str]:
    if r.get("url_override") and str(r["url_override"]).lower().endswith(".pdf"):
        return r["url_override"], "oa-pdf"
    title, authors = r["title"], r["authors"]
    if got := arxiv_quick(title, authors):
        return got, "arxiv"
    doi = r.get("doi")
    if doi:
        try:
            for loc in pf.unpaywall_locations(doi, pf.git_email()):
                return loc, "unpaywall"
        except Exception:  # noqa: BLE001
            pass
    if r.get("url_override"):
        return r["url_override"], "oa-url"
    return None, "unresolved"


def resolve(by_folder: dict[str, list[dict]]) -> None:
    for folder, records in by_folder.items():
        targets = [r for r in records
                   if r["status"] not in ("held", "downloaded", "no-open-copy")
                   and not r["url"]]
        print(f"\n=== resolve {folder}: {len(targets)} ===")
        for i, r in enumerate(targets, 1):
            url, how = resolve_one(r)
            r["url"], r["how"] = url or "", how
            if not url:
                r["status"] = "no-open-copy"
            print(f"[{i}/{len(targets)}] {how:>16}  {r['title'][:68]}")
            if i % 15 == 0:
                save_ckpt(folder, records)
            time.sleep(RESOLVE_SLEEP)
        save_ckpt(folder, records)


def download(by_folder: dict[str, list[dict]], force: bool) -> None:
    sess = pf.session()
    for folder, records in by_folder.items():
        dest_dir = out_dir(folder)
        dest_dir.mkdir(parents=True, exist_ok=True)
        targets = [r for r in records if r["url"]
                   and (force or r["status"] not in ("held", "downloaded"))]
        print(f"\n=== download {folder}: {len(targets)} → {dest_dir} ===")
        ok = fail = 0
        for i, r in enumerate(targets, 1):
            stem = pf.safe_stem(r["authors"][:1], r["title"])
            dest = dest_dir / f"{stem}.pdf"
            got, msg = pf.download_pdf(sess, r["url"], dest)
            if got:
                r["status"] = "downloaded"
                r["file"] = str(dest.relative_to(ROOT))
                ok += 1
                print(f"[{i}/{len(targets)}] OK  {dest.name}")
            else:
                r["status"] = f"dl_failed: {msg}"
                fail += 1
                print(f"[{i}/{len(targets)}] --  {r['title'][:60]}  ({msg})")
            if i % 10 == 0:
                save_ckpt(folder, records)
            time.sleep(DL_SLEEP)
        save_ckpt(folder, records)
        print(f"  downloaded {ok}, failed {fail}")


def save_ckpt(folder: str, records: list[dict]) -> None:
    dest_dir = out_dir(folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path(folder).write_text(json.dumps(records, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    with report_path(folder).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["who", "status", "how", "year", "title", "url", "file"])
        for r in records:
            w.writerow([r["who"], r["status"], r["how"], r["year"],
                        r["title"], r["url"], r["file"]])


def load_all(profiles: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for p in profiles:
        path = ckpt_path(p["folder"])
        if path.exists() and p["folder"] not in out:
            out[p["folder"]] = json.loads(path.read_text(encoding="utf-8"))
    return out


def summary(by_folder: dict[str, list[dict]]) -> None:
    for folder, records in by_folder.items():
        st = Counter(r["status"].split(":")[0] for r in records)
        print(f"\n=== {folder} ({len(records)}) ===")
        print(f"  downloaded {st['downloaded']} | held {st['held']} | "
              f"no-open-copy {st['no-open-copy']} | failed {st['dl_failed']} | "
              f"pending {st['pending']}")
        print(f"  next: scripts/.venv/bin/python scripts/import-downloads.py "
              f"--only {folder}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "resolve", "download", "all"])
    p.add_argument("--only", nargs="*", metavar="KEY",
                   help="zaharia / rxin / dageville / cruanes / zukowski")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-dedup", action="store_true")
    args = p.parse_args(argv)

    profiles = PROFILES
    if args.only:
        keys = set(args.only)
        profiles = [x for x in PROFILES if x["key"] in keys or x["folder"] in keys]
        if not profiles:
            print(f"no matching profiles for {args.only}", file=sys.stderr)
            return 2

    if args.cmd == "gather":
        by = gather(profiles, dedup=not args.no_dedup)
    else:
        by = load_all(profiles)
        if args.cmd in ("all",) or not by:
            by = gather(profiles, dedup=not args.no_dedup)
        if args.cmd in ("resolve", "all"):
            resolve(by)
        if args.cmd in ("download", "all"):
            download(by, force=args.force)
    summary(by)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
