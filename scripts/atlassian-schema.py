#!/usr/bin/env python3
"""Harvest Atlassian's published Jira database-schema documents (the ERD PDFs).

Source: https://developer.atlassian.com/server/jira/platform/database-schema/

That page's prose is imported as markdown by ``import-docs.py --only jira-db``,
but the page's real payload is a list of *attachments*: one schema document per
Jira version, from 5.12 to 9.0. They are the only complete statement of the
schema Atlassian publishes — the prose pages describe five table groups (change
history, custom fields, issue fields, workflow, users & groups) out of 176
tables — so they are fetched as documents in their own right and filed next to
the markdown collection under
``Literature/Source Systems Knowledge/Atlassian/``.

Two things about these files decide how this harvester behaves:

* **Most of them are SchemaCrawler text, not pictures.** Six of the seven carry
  a full text layer listing every table and column with its type (Jira 8.20:
  176 tables in 26,000 characters), so they are searchable as soon as they are
  indexed, and grepping one answers "which table holds X" better than the prose
  does.
* **The newest one is not.** ``jira_9.0_database_schema.pdf`` is 3 MB of two
  embedded images with **zero** extractable characters, while every older
  edition is ~80 KB of text. That is the version a reader would reach for, and
  nothing about the download says so: it is a valid PDF, it is the largest file
  of the set, and it renders perfectly. So each download is probed for its text
  layer and the result is recorded per file — ``text_chars`` in the report,
  with a warning printed for anything that has none. 9.0 needs the OCR stage
  (``search/ocr.py``) to become searchable; until then 8.20 is the newest
  edition whose schema can actually be queried.

Versions come from the anchor text (``Jira_8.20_schema.pdf``) rather than from a
hard-coded list, so a Jira 10 schema appearing on the page is picked up by the
next run. Files are named ``Atlassian - Jira <version> Database Schema
(ERD).pdf``: the corporate author plus the version, following the
``Analyst Reports/`` convention for dated snapshots from one publisher, and
keeping the ``Author - Title`` shape that ``import-downloads.py`` preserves
verbatim.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - parse the attachment links off the database-schema page.
  2. download - fetch every schema not already held under Literature/, then
                probe each file's text layer.

Usage:
  scripts/.venv/bin/python scripts/atlassian-schema.py all
  scripts/.venv/bin/python scripts/atlassian-schema.py gather|download
  scripts/.venv/bin/python scripts/atlassian-schema.py all --force
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from lxml import html as H
from pypdf import PdfReader

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = "https://developer.atlassian.com/server/jira/platform/database-schema/"
OUT_DIR = DOCS_ROOT / "Inbox" / "jira-schema"
# where import-downloads.py files these (COHORT_FOLDERS), so an already-imported
# schema is not fetched again on a re-run
HELD_DIR = DOCS_ROOT / "Literature" / "Source Systems Knowledge" / "Atlassian"
CKPT = OUT_DIR / "_jira-schema.json"
REPORT = OUT_DIR / "_jira-schema-report.csv"
DL_SLEEP = 1.0

# "Jira_8.20_schema.pdf", "Jira_7.9.2_schema.pdf", and one typo the page has
# carried for years: "Jira_5.12_chema.pdf".
LINK_TEXT_RE = re.compile(
    r"Jira[_\s]*(?P<ver>\d+(?:\.\d+)*)[_\s]*(?:database[_\s]*)?s?chema", re.I)


def stem_for(version: str) -> str:
    return f"Atlassian - Jira {version} Database Schema (ERD)"


def text_layer(path: Path) -> tuple[int, int]:
    """(pages, extractable characters) — see the module docstring on why."""
    try:
        reader = PdfReader(str(path))
        return len(reader.pages), sum(
            len(page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 — a probe must not fail the harvest
        print(f"    ! could not read {path.name}: {type(exc).__name__}: {exc}")
        return 0, 0


def gather() -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r = pf.requests.get(PAGE_URL, headers=pf.HEADERS, timeout=60)
    r.raise_for_status()
    doc = H.fromstring(r.content)

    records: list[dict] = []
    seen: set[str] = set()
    for a in doc.xpath("//a[@href]"):
        href = urljoin(PAGE_URL, a.get("href"))
        # the anchor text carries the version; the href is an attachment id on
        # one of two CDN hosts and says nothing about which version it is
        m = LINK_TEXT_RE.search(pf.clean(a.text_content()))
        if not m or ".pdf" not in href.lower().split("?")[0]:
            continue
        version = m.group("ver")
        if version in seen:
            continue
        seen.add(version)
        records.append({
            "version": version,
            "url": href,
            "filename": stem_for(version) + ".pdf",
            "status": "pending",
            "pages": None,
            "text_chars": None,
        })
    print(f"parsed {len(records)} schema documents from {PAGE_URL}")

    for rec in records:
        if (HELD_DIR / rec["filename"]).exists():
            rec["status"] = "held"
    if held := sum(1 for r in records if r["status"] == "held"):
        print(f"  {held} already held in "
              f"Literature/{HELD_DIR.relative_to(DOCS_ROOT / 'Literature')}")

    records.sort(key=lambda r: [int(p) for p in r["version"].split(".")],
                 reverse=True)
    return records


def download(records: list[dict], force: bool) -> None:
    targets = [r for r in records
               if force or r.get("status") not in ("held", "downloaded")]
    print(f"downloading {len(targets)} schema documents -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, rec in enumerate(targets, 1):
        dest = OUT_DIR / rec["filename"]
        got, msg = pf.download_pdf(sess, rec["url"], dest)
        if got:
            rec["status"], ok = "downloaded", ok + 1
            rec["pages"], rec["text_chars"] = text_layer(dest)
            note = (f"{rec['text_chars']} chars of text"
                    if rec["text_chars"] else "NO TEXT LAYER \u2014 needs OCR")
            print(f"[{i}/{len(targets)}] OK  {dest.name}  ({msg}; {note})")
        else:
            rec["status"], fail = "dl_failed", fail + 1
            print(f"[{i}/{len(targets)}] --  Jira {rec['version']}  ({msg})")
        save_ckpt(records)
        time.sleep(DL_SLEEP)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["version", "status", "pages", "text_chars", "filename", "url"])
        for r in records:
            w.writerow([r["version"], r.get("status", ""), r.get("pages"),
                        r.get("text_chars"), r["filename"], r["url"]])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    print("\n=== Jira database schema documents ===")
    print(f"  versions: {len(records)} | downloaded: {st['downloaded']} | "
          f"held: {st['held']} | failed: {st['dl_failed']}")
    for r in records:
        if r.get("status") == "dl_failed":
            print(f"  ! Jira {r['version']} ({r['url']})")
        elif r.get("text_chars") == 0:
            print(f"  ! Jira {r['version']} has no text layer "
                  f"({r['pages']} page(s)) — searchable only after OCR")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "download", "all"])
    p.add_argument("--force", action="store_true",
                   help="re-download schemas already held in Literature/")
    args = p.parse_args(argv)

    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr)
            return 2
    else:
        recs = gather()
        save_ckpt(recs)
    if args.cmd != "gather":
        download(recs, args.force)
    print_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
