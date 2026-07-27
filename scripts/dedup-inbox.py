#!/usr/bin/env python3
"""Quarantine Inbox PDFs that duplicate a paper already in the KB.

A "duplicate" is decided by *normalised title*, checked against BOTH:
  * the search index (``search/index.duckdb`` — documents.title / rel_path), and
  * the files already on disk under ``Literature/`` (filename-derived titles),
because freshly-imported papers may not be indexed yet.

Duplicates are moved to ``imports/dup-rejected/`` (recoverable), not deleted.
Run this *before* scripts/import-downloads.py.

    scripts/.venv/bin/python scripts/dedup-inbox.py
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "Inbox"
LIT = ROOT / "Literature"
DB = ROOT / "search" / "index.duckdb"
REJECT = ROOT / "imports" / "dup-rejected"
MIN_KEY_LEN = 25  # ignore very short titles to avoid false-positive matches

# import the sibling importer module (hyphenated filename) for extract_biblio
_spec = importlib.util.spec_from_file_location("import_downloads", ROOT / "scripts" / "import-downloads.py")
_imp = importlib.util.module_from_spec(_spec)
sys.modules["import_downloads"] = _imp
_spec.loader.exec_module(_imp)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# Junk "titles" produced by bad PDF metadata/first-page extraction. These must
# never be used as dedup keys, or unrelated papers sharing a boilerplate header
# (e.g. every Elsevier paper starts "Contents lists available at ScienceDirect")
# would be wrongly treated as duplicates of each other.
_GENERIC = re.compile(
    r"contents lists available|sciencedirect|latex template|springer nature \d|"
    r"under consideration for publication|author.?s version|this may be the|"
    r"c documents and settings|^untitled|elsevier|^microsoft word|"
    r"journal homepage|available online at|^proof$", re.I)


def good_key(k: str) -> bool:
    return len(k) >= MIN_KEY_LEN and not _GENERIC.search(k)


def title_from_filename(stem: str) -> list[str]:
    keys = [norm(stem)]
    # importer names files "Author[ et al.] - Title"
    if " - " in stem:
        keys.append(norm(stem.split(" - ", 1)[1]))
    return [k for k in keys if good_key(k)]


def build_existing_keys() -> set[str]:
    keys: set[str] = set()
    # 1) search index
    if DB.exists():
        try:
            import duckdb
            con = duckdb.connect(str(DB), read_only=True)
            for (title,) in con.execute("SELECT title FROM documents").fetchall():
                k = norm(title)
                if good_key(k):
                    keys.add(k)
            for (rp,) in con.execute("SELECT rel_path FROM documents").fetchall():
                keys.update(title_from_filename(Path(rp).stem))
            con.close()
        except Exception as exc:  # noqa: BLE001
            print(f"  (index unreadable: {exc})", file=sys.stderr)
    # 2) files already on disk
    for p in LIT.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".epub", ".md", ".txt"}:
            keys.update(title_from_filename(p.stem))
    return keys


def main() -> int:
    REJECT.mkdir(parents=True, exist_ok=True)
    existing = build_existing_keys()
    print(f"existing title keys: {len(existing)}")

    dups, kept = [], 0
    for p in sorted(INBOX.glob("*.pdf")):
        cand = set(title_from_filename(p.stem))
        try:
            bib = _imp.extract_biblio(p)
            k = norm(bib.title)
            if good_key(k):
                cand.add(k)
        except Exception:
            pass
        match = next((k for k in cand if k in existing), None)
        if match:
            shutil.move(str(p), str(REJECT / p.name))
            dups.append((p.name, match[:70]))
        else:
            kept += 1
            # add so intra-batch duplicates are also caught
            existing.update(cand)

    print(f"kept: {kept}   duplicates quarantined: {len(dups)} -> imports/dup-rejected/")
    for n, k in dups:
        print(f"  dup {n}  ~ {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
