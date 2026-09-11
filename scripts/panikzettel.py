#!/usr/bin/env python3
"""Harvest the RWTH Aachen *Panikzettel* — student-written course cheat sheets.

Source: https://htwr-aachen.de/panikzettel (a maintained fork of the original
https://panikzettel.philworld.de collection; LaTeX sources and CC-BY-SA-4.0
licence at https://github.com/htwr-aachen/panikzettel).

A Panikzettel ("panic sheet") is a dense two-to-six page distillation of a whole
RWTH computer-science lecture, written by the students who sat it. That density
is the point for this library: *Berechenbarkeit und Komplexitaet*, *Formale
Systeme, Automaten und Prozesse*, *Datenbanken und Informationssysteme* and
*Mathematische Logik* state the definitions and theorems the process-mining and
database literature here assumes without restating, in a form short enough to
retrieve whole.

The listing page renders client-side from a JSON endpoint, so the *metadata*
comes from the API rather than from HTML — which is what makes it worth using:
each entry carries the course name, its curriculum slot (compulsory subject,
compulsory elective, application area) and the **revision date**, none of which
appear in the PDF itself.

Files are named ``Panikzettel - <Course> (<YYYY-MM-DD>).pdf`` — the collection as
corporate author plus the revision, following the ``Analyst Reports/`` and
``Specifications/IDSA/`` convention for dated publications from one publisher
(see ``README.md``). The date is not decoration: these are living documents
re-cut as a course changes, and *Elements of Machine Learning and Data Science*
exists in a German and an English edition that a title alone cannot tell apart.

Note on de-duplication: as with ``idsa-papers.py``, the ``paperfetch.IndexDedup``
title check does **not** decide whether to download, because a newer revision of
a sheet shares its title with the copy already held and would be silently
dropped. Skipping is decided by whether the exact dated filename is already in
``Literature/``; the index state is recorded in the report only.

German umlauts are transliterated (ae/oe/ue/ss) before the filename is written.
``import-downloads.py`` slugifies to ASCII by decomposition, which would turn
"Einfuehrung" into "Einfuhrung" and leave this harvester unable to recognise its
own output on the next run.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - read the API into per-sheet records.
  2. download - fetch every sheet not already held under Literature/.

Usage:
  scripts/.venv/bin/python scripts/panikzettel.py all
  scripts/.venv/bin/python scripts/panikzettel.py gather|download
  scripts/.venv/bin/python scripts/panikzettel.py all --force
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://api.htwr-aachen.de/api/panikzettel/"
SITE_URL = "https://htwr-aachen.de/panikzettel"
OUT_DIR = DOCS_ROOT / "Inbox" / "panikzettel"
# where import-downloads.py files these, so an already-imported sheet is not
# fetched again on a re-run
HELD_DIR = DOCS_ROOT / "Literature" / "Course Notes" / "RWTH Aachen Panikzettel"
CKPT = OUT_DIR / "_panikzettel.json"
REPORT = OUT_DIR / "_panikzettel-report.csv"
DL_SLEEP = 0.5

# the API's curriculum slots, in the order the site lists them
KINDS = {
    "compulsory": "Pflichtfach",
    "compulsory_elective": "Wahlpflichtfach",
    "application_area": "Anwendungsfach",
    "non_technical_elective": "Nichttechnisches Wahlfach",
    "other": "Sonstiges",
}

UMLAUTS = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
})


def ascii_title(title: str) -> str:
    """Transliterate to ASCII the way a German reader would spell it."""
    title = pf.clean(title).translate(UMLAUTS)
    title = unicodedata.normalize("NFKD", title)
    return title.encode("ascii", "ignore").decode("ascii").strip()


def sheet_stem(title: str, date: str | None) -> str:
    suffix = f" ({date})" if date else ""
    return f"Panikzettel - {ascii_title(title)}{suffix}"


def make_record(entry: dict) -> dict:
    title = pf.clean(entry.get("name") or "")
    date = (entry.get("date") or "").strip() or None
    downloads = entry.get("downloads") or {}
    return {
        "title": title,
        "kind": entry.get("type") or "other",
        "semester": entry.get("semester"),
        "shortname": entry.get("shortname") or "",
        "date": date,
        "url": entry.get("url") or "",
        "source_filename": entry.get("filename") or "",
        "filename": sheet_stem(title, date) + ".pdf",
        "downloads_30d": downloads.get("last_30_days"),
        "status": "pending",
        "in_index": None,
    }


def fetch_listing() -> list[dict]:
    r = pf.requests.get(API_URL, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list):
        raise ValueError(f"unexpected API payload: {type(payload).__name__}")
    return [make_record(e) for e in payload if e.get("url") and e.get("name")]


def gather(dedup: bool) -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = fetch_listing()
    print(f"parsed {len(records)} Panikzettel from {API_URL}")

    for r in records:
        if (HELD_DIR / r["filename"]).exists():
            r["status"] = "held"
    held = sum(1 for r in records if r["status"] == "held")
    if held:
        print(f"  {held} already held in "
              f"Literature/{HELD_DIR.relative_to(DOCS_ROOT / 'Literature')}")

    if dedup:
        # recorded for the report only — see the module docstring on why a title
        # match must not decide whether to download.
        idx = pf.IndexDedup()
        if idx.available:
            for r in records:
                r["in_index"] = idx.contains(r["title"])
            print(f"  {sum(1 for r in records if r['in_index'])} share a title "
                  f"with an indexed document (revisions may differ)")

    records.sort(key=lambda r: (r["kind"], r.get("semester") or 0,
                                r["title"].lower()))
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
        w.writerow(["date", "kind", "semester", "shortname", "status",
                    "title_in_index", "title", "filename", "url"])
        for r in records:
            w.writerow([r.get("date") or "", KINDS.get(r["kind"], r["kind"]),
                        r.get("semester") or "", r.get("shortname", ""),
                        r.get("status", ""), r.get("in_index"),
                        r["title"], r["filename"], r["url"]])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    st = Counter(r.get("status") for r in records)
    kinds = Counter(KINDS.get(r["kind"], r["kind"]) for r in records)
    print(f"\n=== Panikzettel summary ({SITE_URL}) ===")
    print(f"  sheets: {len(records)} | downloaded: {st['downloaded']} | "
          f"held: {st['held']} | failed: {st['dl_failed']}")
    print("  " + " | ".join(f"{k}: {n}" for k, n in sorted(kinds.items())))
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
                   help="re-download sheets already held in Literature/")
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
