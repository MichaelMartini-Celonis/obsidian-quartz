#!/usr/bin/env python3
"""Harvest PVLDB proceedings PDFs from the open vldb.org volume pages.

PVLDB is fully open. Each volume page (``vldb.org/pvldb/volumes/<N>/``) is a
Next.js listing whose ``__NEXT_DATA__`` JSON carries title, authors, issue and
a direct ``vol<N>/p*.pdf`` URL. Front-matter PDFs are skipped. There is no
paywall and no OA resolver.

Volume *N* is the research track of VLDB conference year *N+7* (vol 19 = VLDB
2026). Papers accepted after that year's cutoff roll over to the next
conference but stay in the same volume; this harvester takes the volume as
published.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - parse each volume's ``__NEXT_DATA__`` into per-paper records,
                flag titles already in the search index.
  2. download - fetch every not-yet-indexed PDF into
                ``Inbox/pvldb-papers/<year>/``.

    scripts/.venv/bin/python scripts/pvldb-papers.py gather --volumes 19
    scripts/.venv/bin/python scripts/pvldb-papers.py download
    scripts/.venv/bin/python scripts/pvldb-papers.py all --volumes 19
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "pvldb-papers"
HTML_CACHE = OUT_DIR / "_html_cache"
CKPT = OUT_DIR / "_pvldb-papers.json"
REPORT = OUT_DIR / "_pvldb-papers-report.csv"
DL_SLEEP = 0.5

BASE = "https://www.vldb.org/pvldb/volumes/{vol}/"
# PVLDB volume N is presented at VLDB (N+7). Vol 14 = 2021 … vol 19 = 2026.
VOL_TO_YEAR = {v: v + 7 for v in range(1, 30)}
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
FRONT_RE = re.compile(r"front\s*matter", re.I)


def parse_volumes(spec: str | None) -> list[int]:
    if not spec:
        return [19]
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def split_authors(raw: str) -> list[str]:
    txt = pf.clean(raw)
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r",?\s+and\s+", ", ", txt, flags=re.I)
    return [p.strip() for p in txt.split(",") if p.strip()]


def fetch_volume(vol: int, force: bool = False) -> str:
    HTML_CACHE.mkdir(parents=True, exist_ok=True)
    cache = HTML_CACHE / f"vol{vol}.html"
    if cache.exists() and cache.stat().st_size > 2000 and not force:
        return cache.read_text(encoding="utf-8")
    url = BASE.format(vol=vol)
    r = pf.requests.get(url, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    cache.write_text(r.text, encoding="utf-8")
    return r.text


def parse_volume(vol: int, html: str) -> list[dict]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise SystemExit(f"vol {vol}: no __NEXT_DATA__ on the volume page")
    data = json.loads(m.group(1))
    grouped = data.get("props", {}).get("pageProps", {}).get("groupedIssues") or {}
    year = VOL_TO_YEAR.get(vol)
    records: list[dict] = []
    seen: set[str] = set()
    for issue_key, items in grouped.items():
        for it in items:
            title = pf.clean(it.get("title") or "")
            pdf_url = (it.get("pdf") or "").strip()
            if not title or not pdf_url:
                continue
            if FRONT_RE.search(title) or "FrontMatter" in pdf_url:
                continue
            if pdf_url in seen:
                continue
            seen.add(pdf_url)
            records.append({
                "key": f"vol{vol}:{Path(pdf_url).name}",
                "volume": vol,
                "year": year,
                "issue": it.get("issue") or int(issue_key),
                "title": title,
                "authors": split_authors(it.get("authors") or ""),
                "pdf_url": pdf_url,
                "start_page": it.get("start_page"),
                "end_page": it.get("end_page"),
                "status": "pending",
                "in_index": None,
            })
    return records


def gather(volumes: list[int], dedup: bool) -> list[dict]:
    recs: list[dict] = []
    for vol in volumes:
        html = fetch_volume(vol)
        vol_recs = parse_volume(vol, html)
        year = VOL_TO_YEAR.get(vol)
        print(f"  vol {vol} (VLDB {year}): {len(vol_recs)} papers")
        recs.extend(vol_recs)
    print(f"parsed {len(recs)} PVLDB papers")
    if dedup:
        idx = pf.IndexDedup()
        for r in recs:
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in recs if r['in_index'])} already in the search index")
    recs.sort(key=lambda r: (-(r.get("year") or 0), r.get("issue") or 0, r["title"].lower()))
    return recs


def merge_ckpt(fresh: list[dict], existing: list[dict]) -> list[dict]:
    old = {r["key"]: r for r in existing}
    out = []
    for r in fresh:
        prev = old.get(r["key"])
        if prev and prev.get("status") in ("downloaded", "dl_failed"):
            r["status"] = prev["status"]
        out.append(r)
    return out


def download(records: list[dict]) -> None:
    targets = [r for r in records
               if r.get("pdf_url") and not r.get("in_index")
               and r.get("status") not in ("downloaded",)]
    print(f"downloading {len(targets)} PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        year = r.get("year") or VOL_TO_YEAR.get(r["volume"], "unknown")
        dest = OUT_DIR / str(year) / (pf.safe_stem(r["authors"], r["title"]) + ".pdf")
        got, msg = pf.download_pdf(sess, r["pdf_url"], dest)
        if got:
            r["status"] = "downloaded"
            ok += 1
            print(f"[{i}/{len(targets)}] OK  {dest.name}  ({msg})")
        else:
            r["status"] = "dl_failed"
            fail += 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:60]}  ({msg})")
        if i % 20 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["volume", "year", "issue", "status", "in_index",
                    "title", "authors", "pdf_url"])
        for r in records:
            w.writerow([r.get("volume") or "", r.get("year") or "", r.get("issue") or "",
                        r.get("status", ""), r.get("in_index"),
                        r["title"], "; ".join(r.get("authors", [])),
                        r.get("pdf_url") or ""])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    st = Counter(r.get("status") for r in records)
    print("\n=== PVLDB summary ===")
    print(f"  papers: {len(records)} | with PDF: {sum(1 for r in records if r.get('pdf_url'))}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}"
          f" | pending: {sum(1 for r in records if r.get('status') == 'pending')}"
          f" | downloaded: {sum(1 for r in records if r.get('status') == 'downloaded')}")
    print(f"  status: {dict(st)}")
    print(f"  backlog: {CKPT.relative_to(DOCS_ROOT)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="gather",
                   choices=["gather", "download", "all"])
    p.add_argument("--volumes", default="19",
                   help="comma/range list, e.g. 19 or 14-19 (default: 19 = VLDB 2026)")
    p.add_argument("--no-dedup", action="store_true",
                   help="do not skip papers already indexed")
    p.add_argument("--refresh-html", action="store_true",
                   help="re-fetch volume pages instead of using the cache")
    args = p.parse_args(argv)

    volumes = parse_volumes(args.volumes)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup
    if args.refresh_html:
        for v in volumes:
            cache = HTML_CACHE / f"vol{v}.html"
            if cache.exists():
                cache.unlink()

    if args.cmd == "gather":
        recs = gather(volumes, dedup)
        recs = merge_ckpt(recs, load_ckpt())
        save_ckpt(recs)
        print_summary(recs)
        return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr)
            return 2
        wanted = set(volumes)
        scoped = [r for r in recs if r.get("volume") in wanted]
        if not scoped:
            print(f"checkpoint has no volumes {sorted(wanted)}; run gather first",
                  file=sys.stderr)
            return 2
        download(scoped)
        by_key = {r["key"]: r for r in recs}
        by_key.update({r["key"]: r for r in scoped})
        recs = list(by_key.values())
        save_ckpt(recs)
        print_summary(recs)
        return 0
    recs = gather(volumes, dedup)
    recs = merge_ckpt(recs, load_ckpt())
    save_ckpt(recs)
    download(recs)
    print_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
