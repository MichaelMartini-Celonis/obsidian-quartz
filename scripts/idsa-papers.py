#!/usr/bin/env python3
"""Harvest the International Data Spaces Association (IDSA) publications.

Source: https://internationaldataspaces.org/publications/papers/

IDSA is the standards body behind the IDS Reference Architecture Model and the
Dataspace Protocol, and its position papers are the argued-out version of the
problem Celonis Networks addresses: how independent companies share process
data across an organisational boundary without either side losing control of it
(data sovereignty, usage control, a shared semantic model, participant
onboarding, governance). The papers are CC-BY and published as free PDFs.

The page is a WordPress/Divi build whose download list is rendered by the
Download Monitor plugin. Each entry is a ``mz-download-item`` block

    <div class="... mz-download-item ...">
      <h3>Title</h3>
      <p>Position Paper | Version 1.1 | November 2025</p>
      ... <a href="https://internationaldataspaces.org/download/52879/">

so the *title, edition and version* come from the listing rather than from the
PDF's own front matter, which is what makes them worth parsing: several papers
exist in two editions under an identical title (Semantic Interoperability,
Standardization Landscape), and only the version and date tell them apart.
Featured entries (the Rulebook white paper) sit outside that markup as a cover
image linking to the same ``/download/<id>/`` endpoint, with their heading
*after* the link, so they are picked up in a second pass.

Files are named ``IDSA - <Title> (v<version>, <YYYY-MM>).pdf`` — the corporate
author plus the edition, following the ``Analyst Reports/`` convention for
dated, versioned publications from one publisher (see ``README.md``).

Note on de-duplication: the usual ``paperfetch.IndexDedup`` title check is
deliberately *not* used to skip downloads here. Two editions of one position
paper share a title, so a title match would silently drop the newer one; the
index state is recorded in the report instead, and skipping is decided by
whether the exact versioned filename is already held in ``Literature/``.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - parse the publications page into per-paper records.
  2. download - fetch every paper not already held under Literature/.

Usage:
  scripts/.venv/bin/python scripts/idsa-papers.py all
  scripts/.venv/bin/python scripts/idsa-papers.py gather|download
  scripts/.venv/bin/python scripts/idsa-papers.py all --force
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from pathlib import Path

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
LIST_URL = "https://internationaldataspaces.org/publications/papers/"
DOWNLOAD_URL = "https://internationaldataspaces.org/download/{id}/"
OUT_DIR = DOCS_ROOT / "Inbox" / "idsa"
# where import-downloads.py files these, so an already-imported paper is not
# fetched again on a re-run
HELD_DIR = DOCS_ROOT / "Literature" / "Specifications" / "IDSA"
CKPT = OUT_DIR / "_idsa.json"
REPORT = OUT_DIR / "_idsa-report.csv"
DL_SLEEP = 1.0

ITEM_SPLIT_RE = re.compile(r"(?=mz-download-item)")
DOWNLOAD_RE = re.compile(r"/download/(\d+)")
H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
P_RE = re.compile(r"<p>(.*?)</p>", re.S)
# featured (non-list) entries: the heading follows the cover-image link
HEADER_RE = re.compile(r"et_pb_module_header[^>]*>(?P<title>.*?)</h\d>", re.S)

VERSION_RE = re.compile(r"Version\s+(?P<v>[\d]+(?:\.[\d]+)*(?:-\d+)?)", re.I)
MONTH_YEAR_RE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+(?P<year>(?:19|20)\d{2})\b", re.I)
YEAR_RE = re.compile(r"\b(?P<year>(?:19|20)\d{2})\b")
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}

# IDSA's own listing renders "AI" as "Al" (capital A, lowercase L) in one title;
# the PDF does not. Fixed here so the filename and the index agree with the
# document, and so a search for "AI Act" finds it.
TITLE_FIXES = {"Al Act": "AI Act"}


def fetch(url: str) -> str:
    r = pf.requests.get(url, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def text_of(fragment: str) -> str:
    return pf.clean(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def normalize_title(title: str) -> str:
    # en/em dashes and colons do not survive the library's filename slug, so
    # they are folded here to keep the on-disk name deterministic.
    title = title.replace("\u2013", "-").replace("\u2014", "-")
    title = re.sub(r"\s*:\s*", " - ", title)
    for wrong, right in TITLE_FIXES.items():
        title = title.replace(wrong, right)
    return pf.clean(title).rstrip(".")


def parse_edition(subtitle: str) -> tuple[str | None, str | None, str]:
    """Return (version, date as YYYY[-MM], kind) from a listing subtitle."""
    vm = VERSION_RE.search(subtitle)
    version = vm.group("v") if vm else None

    date = None
    my = MONTH_YEAR_RE.search(subtitle)
    if my:
        date = f"{my.group('year')}-{MONTHS[my.group('month').lower()]:02d}"
    else:
        years = [y for y in YEAR_RE.findall(subtitle)]
        # a bare "Version 2026-2" is an edition number, not a publication year
        if version and version.split("-")[0] in years and len(years) == 1:
            years = []
        if years:
            date = years[-1]

    lowered = subtitle.lower()
    kind = "White Paper" if "white paper" in lowered else "Position Paper"
    return version, date, kind


def paper_stem(title: str, version: str | None, date: str | None) -> str:
    bits = [b for b in (f"v{version}" if version else None, date) if b]
    suffix = f" ({', '.join(bits)})" if bits else ""
    return f"IDSA - {title}{suffix}"


def make_record(download_id: str, title: str, subtitle: str) -> dict:
    title = normalize_title(title)
    version, date, kind = parse_edition(subtitle)
    stem = paper_stem(title, version, date)
    return {
        "id": download_id,
        "title": title,
        "subtitle": pf.clean(subtitle),
        "kind": kind,
        "version": version,
        "date": date,
        "url": DOWNLOAD_URL.format(id=download_id),
        "filename": stem + ".pdf",
        "status": "pending",
        "in_index": None,
    }


def parse_listing(page: str) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()

    for block in ITEM_SPLIT_RE.split(page)[1:]:
        block = block[:6000]
        ids = DOWNLOAD_RE.findall(block)
        titles = H3_RE.findall(block)
        subs = P_RE.findall(block)
        if not ids or not titles:
            continue
        if ids[0] in seen:
            continue
        seen.add(ids[0])
        records.append(make_record(ids[0], text_of(titles[0]),
                                   text_of(subs[0]) if subs else ""))

    # featured entries: a cover image linking to /download/<id>/, whose heading
    # and subtitle come *after* the link rather than inside a list item.
    for m in DOWNLOAD_RE.finditer(page):
        did = m.group(1)
        if did in seen:
            continue
        seen.add(did)
        tail = page[m.end(): m.end() + 6000]
        hm = HEADER_RE.search(tail)
        if not hm:
            continue
        title = text_of(hm.group("title"))
        subs = P_RE.findall(tail[hm.end(): hm.end() + 2000])
        records.append(make_record(did, title,
                                   text_of(subs[0]) if subs else ""))

    return records


def gather(dedup: bool) -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = parse_listing(fetch(LIST_URL))
    print(f"parsed {len(records)} IDSA publications from {LIST_URL}")

    for r in records:
        if (HELD_DIR / r["filename"]).exists():
            r["status"] = "held"
    held = sum(1 for r in records if r["status"] == "held")
    if held:
        print(f"  {held} already held in Literature/{HELD_DIR.relative_to(DOCS_ROOT/'Literature')}")

    if dedup:
        # recorded for the report only — see the module docstring on why a title
        # match must not decide whether to download.
        idx = pf.IndexDedup()
        if idx.available:
            for r in records:
                r["in_index"] = idx.contains(r["title"])
            print(f"  {sum(1 for r in records if r['in_index'])} share a title "
                  f"with an indexed document (editions may differ)")

    records.sort(key=lambda r: (r.get("date") or "", r["title"].lower()),
                 reverse=True)
    return records


def download(records: list[dict], force: bool) -> None:
    targets = [r for r in records
               if force or r.get("status") not in ("held", "downloaded")]
    print(f"downloading {len(targets)} PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        dest = OUT_DIR / r["filename"]
        got, msg = pf.download_pdf(sess, r["url"], dest)
        if got:
            r["status"], ok = "downloaded", ok + 1
            print(f"[{i}/{len(targets)}] OK  {dest.name}  ({msg})")
        else:
            r["status"], fail = "dl_failed", fail + 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:60]}  ({msg})")
        if i % 10 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "kind", "version", "status", "title_in_index",
                    "title", "filename", "url"])
        for r in records:
            w.writerow([r.get("date") or "", r.get("kind", ""),
                        r.get("version") or "", r.get("status", ""),
                        r.get("in_index"), r["title"], r["filename"], r["url"]])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    print("\n=== IDSA publications summary ===")
    print(f"  publications: {len(records)} | "
          f"downloaded: {st['downloaded']} | held: {st['held']} | "
          f"failed: {st['dl_failed']}")
    for r in records:
        if r.get("status") == "dl_failed":
            print(f"  ! {r['title']} ({r['url']})")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "download", "all"])
    p.add_argument("--force", action="store_true",
                   help="re-download papers already held in Literature/")
    p.add_argument("--no-dedup", action="store_true",
                   help="skip the (report-only) search-index title check")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup
    if args.cmd == "gather":
        recs = gather(dedup)
        save_ckpt(recs)
        print_summary(recs)
        return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr)
            return 2
        download(recs, args.force)
        print_summary(recs)
        return 0

    recs = gather(dedup)
    save_ckpt(recs)
    download(recs, args.force)
    print_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
