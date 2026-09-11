#!/usr/bin/env python3
"""Rename library files from the *enriched* metadata in the index.

A harvester names a file from the citation it was given — the title printed on a
publication page, the authors guessed from the surrounding HTML. Enrichment
later reads the PDF itself and writes the title and author list its own front
matter states. Where those two disagree, the enriched pair is the better one,
and this script closes the gap.

The disagreement is not rare and it is not cosmetic. The time-series round
(`gap-timeseries.py`, `SOURCES.md` §3e) took 111 PDFs off Eamonn Keogh's
hand-maintained pages, whose entries carry no markup separating a title from the
authors and venue around it; the heuristic that reads them attributed **97 of
192 files** to a venue token rather than a person (`Icdm - …`, `Discovery et al
- …`, `Databases - …`). Worse, five of the page's hyperlinks point at a
*different paper* than the title above them — `Matrix Profile XIV` links
`consensus_Motif_ICDM_Long_version.pdf`, which is XV; `Matrix Profile XVII`
links `LAMP_Camera_Ready2.pdf`, which is XVIII. That is the §3d failure in a new
guise: a paper filed under a title it does not have, invisible to every check
that trusts the citation, and visible immediately to one that reads the file.

So the rule is: the PDF outranks the page it was linked from.

Conservative by construction, because a rename is destructive:

* **Dry run by default.** `--apply` is required to touch the filesystem.
* A candidate is skipped when the enriched author or title looks unusable — no
  authors, a surname that is not name-shaped, a title under 12 characters or one
  that is plainly cover-page furniture (`arXiv:2504.01702v1 [econ.EM]`, `NBER
  TECHNICAL WORKING PAPER SERIES`), which is exactly what the *unenriched*
  extraction produces and what this script must never write into a filename.
* Collisions are reported and skipped, never overwritten. Two files that
  genuinely are the same work will collide here; that is a duplicate to resolve
  by hand, not something to rename around.
* Names are built with `paperfetch.safe_stem`, so the result follows the same
  `Author et al - Title.pdf` convention as every other import path rather than a
  second one invented here.

Renaming moves a file, so the index rows keyed on its old path go stale; a plain
`search.cli index` run afterwards prunes them and re-indexes the new path (the
content hash is unchanged, but the path check in `index_file` is not, so the
document is re-read rather than fast-skipped).

Usage:
  scripts/.venv/bin/python scripts/rename-from-metadata.py --folder "Time Series"
  scripts/.venv/bin/python scripts/rename-from-metadata.py --folder "Time Series" --apply
  scripts/.venv/bin/python scripts/rename-from-metadata.py --folder "Time Series" --only-mismatched-title
"""

from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import paperfetch as pf  # noqa: E402

REPORT = ROOT / "imports" / "rename-from-metadata.csv"

# Cover-page furniture an unenriched extraction mistakes for a title. A file
# whose recorded title looks like this has not been enriched, and renaming from
# it would replace a merely wrong name with a much worse one.
JUNK_TITLE = re.compile(
    r"(?i)^(arxiv:|doi:|isbn|nber |proceedings of|technical (working )?report|"
    r"working paper|preprint|submitted to|copyright|vol\.? ?\d|"
    r"[\d\s.,;:()\[\]-]+$)"
)


def plausible_surname(name: str) -> bool:
    """True when the enriched first author looks like a person, not a token.

    Enrichment occasionally returns a fragment (`eamonn`, `Garwal`) where the
    PDF's author line is typeset oddly. A fragment is still a worse name than
    the venue token it would replace, so require a capitalised, alphabetic,
    3-character-or-longer surname.
    """
    s = pf.surname(name)
    return bool(s) and len(s) >= 3 and re.fullmatch(r"[a-z][a-z .\-]*", s) is not None


def fold(s: str) -> str:
    """Case- and diacritic-insensitive form, for comparing a name to a filename.

    `Blázquez-García` is written `Blazquez-Garcia` by the importer, and that is
    not a disagreement worth a rename.
    """
    d = unicodedata.normalize("NFKD", s)
    return "".join(c for c in d if not unicodedata.combining(c)).lower()


def load_rows(folder: str) -> list[tuple[str, str, list[str]]]:
    import duckdb

    con = duckdb.connect(str(ROOT / "search" / "index.duckdb"), read_only=True)
    like = f"%/{folder.strip('/')}/%"
    rows = con.execute(
        "SELECT path, title, authors FROM documents "
        "WHERE path LIKE ? ORDER BY path", [like]
    ).fetchall()
    con.close()
    return [(r[0], r[1] or "", list(r[2] or [])) for r in rows]


def plan(folder: str, only_mismatched: bool) -> list[dict]:
    out: list[dict] = []
    seen: dict[str, str] = {}
    for path_s, title, authors in load_rows(folder):
        path = Path(path_s)
        cur = path.stem
        reason = ""
        if not path.exists():
            reason = "file-missing"
        elif not authors or not plausible_surname(authors[0]):
            reason = "no-usable-author"
        elif len(pf.clean(title)) < 12 or JUNK_TITLE.match(pf.clean(title)):
            reason = "no-usable-title"

        if reason:
            out.append({"action": "skip", "reason": reason, "current": cur,
                        "proposed": "", "title": title,
                        "authors": "; ".join(authors[:3])})
            continue

        stem = pf.safe_stem(authors, title)
        if stem == cur:
            continue

        # Does the disagreement concern the *title*, or only the author prefix?
        # The importer writes ":" as "_", so undo that before comparing.
        cur_title = cur.split(" - ", 1)[1] if " - " in cur else cur
        ratio = difflib.SequenceMatcher(
            None, pf.norm(cur_title.replace("_", ":")), pf.norm(title)
        ).ratio()
        kind = "title+author" if ratio < 0.75 else "author-prefix"

        cur_pre = fold(cur.split(" - ", 1)[0].replace(" et al", "").strip())
        if kind == "author-prefix" and cur_pre == fold(pf.surname(authors[0])):
            continue                      # diacritics only — not a disagreement
        if only_mismatched and kind != "title+author":
            continue

        target = path.with_name(stem + path.suffix)
        act = "rename"
        if target.exists() and target != path:
            act = "skip"
        elif str(target) in seen:
            act = "skip"
        else:
            seen[str(target)] = str(path)

        out.append({"action": act,
                    "reason": "target-exists" if act == "skip" else kind,
                    "current": cur, "proposed": stem, "title": title,
                    "authors": "; ".join(authors[:3]),
                    "path": str(path), "target": str(target),
                    "ratio": f"{ratio:.2f}"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", required=True,
                    help="Literature subfolder, e.g. 'Time Series'")
    ap.add_argument("--apply", action="store_true", help="perform the renames")
    ap.add_argument("--only-mismatched-title", action="store_true",
                    help="only where the recorded title disagrees, not just the author")
    args = ap.parse_args()

    rows = plan(args.folder, args.only_mismatched_title)
    renames = [r for r in rows if r["action"] == "rename"]
    skips = [r for r in rows if r["action"] == "skip"]

    for r in renames:
        print(f"[{r['reason']:>13}] {r['current'][:76]}\n"
              f"{'':>16}-> {r['proposed'][:76]}")
    for r in skips:
        print(f"[{r['reason']:>13}] {r['current'][:76]}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["action", "reason", "ratio", "current",
                                           "proposed", "title", "authors",
                                           "path", "target"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    done = 0
    if args.apply:
        for r in renames:
            src, dst = Path(r["path"]), Path(r["target"])
            if dst.exists():
                print(f"[   collision ] {dst.name}")
                continue
            src.rename(dst)
            done += 1

    print(f"\n{len(renames)} rename(s) planned, {len(skips)} skipped"
          f"{f', {done} applied' if args.apply else ' (dry run)'}")
    print(f"report: {REPORT.relative_to(ROOT)}")
    if done:
        print("re-index to refresh paths: "
              "scripts/.venv/bin/python -m search.cli index --roots literature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
