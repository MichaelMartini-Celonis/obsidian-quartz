"""Rename `Literature/` files to match their (enriched) `Author - Title` metadata.

The importer/splitter often leaves files with junk names  -  a numeric bookmark
index (``14 - Title.pdf``), an ``Unknown -`` prefix, a publisher/journal string
(``IEEETRANSACTIONS...``, ``ScienceDirect...``), or a ``.dvi``/arXiv-id stem  -  even
though the LLM enrichment pass has since populated a clean ``title`` / ``authors``
in the index. This tool detects those junk filenames and renames the file on
disk to ``<Author label> - <Title>.<ext>``, updating the ``documents`` row so the
index stays consistent (content hash is unchanged, so no re-embedding needed).

Dry-run by default; pass ``--apply`` to perform the renames.

    scripts/.venv/bin/python -m search.retitle              # preview
    scripts/.venv/bin/python -m search.retitle --apply      # do it
    scripts/.venv/bin/python -m search.retitle --all        # canonicalize every file, not just junky ones
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

from . import config, db

_PARTICLES = {"van", "der", "de", "den", "von", "la", "le", "du", "dos", "da", "ter", "ten"}
# Author tokens that are never real surnames (heuristic-extraction garbage).
_JUNK_AUTHOR = {
    "unknown", "approach", "language", "the", "research", "ieee", "sciencedirect",
    "erp", "springer", "press", "apa", "abstract", "proceedings", "taka05", "team",
    "adminuser", "author", "editors", "editor", "et", "al",
}
_JUNK_TITLE_RE = re.compile(
    r"IEEETRANSACTIONS|ScienceDirect|Journal of Intelligent|Proceedings of the IEEE|"
    r"\bLNCS\b|\.dvi\b|\bVol\b|\bNO\.\s*\d|\d{4}\.\d{4,}|978-3|Semantic Web \d|"
    r"Data Knowledge Engineering|Bulletin of|Springer Nature|-main\b|full-issue|^\d+$",
    re.I,
)
# Generic front-matter titles enrichment sometimes yields; don't overwrite a
# real per-paper name with these.
_FRONTMATTER_RE = re.compile(
    r"(Conference Organization|Committee Structure|Table of Contents|^Preface|"
    r"^Foreword|Author Index|^Proceedings of the \d|Front ?matter|Colophon)",
    re.I,
)


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip())


def slugify(text: str, max_len: int = 150) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s.,'()&-]", "", text).replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip().strip("-").strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text or "untitled"


def surname(full_name: str) -> str:
    name = _clean(full_name)
    name = re.sub(r"\s*\(B\)\s*$", "", name)
    name = re.sub(r"^\d+(st|nd|rd|th)?\s+", "", name, flags=re.I)
    parts = [p for p in name.split() if p]
    if not parts:
        return ""
    # Grab the family root plus any consecutive leading particles (van der Aalst).
    j = len(parts) - 1
    while j - 1 >= 0 and parts[j - 1].lower().strip(".") in _PARTICLES:
        j -= 1
    return " ".join(parts[j:])


def author_label(authors) -> str:
    surnames = [surname(a) for a in (authors or []) if a and a.strip()]
    surnames = [s for s in surnames if s]
    if not surnames:
        return ""
    if len(surnames) == 1:
        return surnames[0]
    if len(surnames) == 2:
        return f"{surnames[0]} and {surnames[1]}"
    return f"{surnames[0]} et al."


def desired_stem(title: str, authors) -> str:
    label = author_label(authors)
    title_s = slugify(title)
    if label:
        return f"{slugify(label)} - {title_s}"
    return title_s


def _is_junky(stem: str) -> bool:
    auth, sep, title = stem.partition(" - ")
    if not sep:
        auth, title = "", stem
    a = auth.strip().lower()
    first = a.split()[0] if a else ""
    if sep and (a.startswith("unknown") or first in _JUNK_AUTHOR
                or re.match(r"^\d", auth)
                or (len(auth.strip()) == 1 and not auth.strip().isalnum())):
        return True
    if _JUNK_TITLE_RE.search(title):
        return True
    if not sep and re.search(r"\d", title) and len(title.split()) <= 2:
        return True
    if title.isupper() and len(title) > 12:
        return True
    return False


def _unique(dest: Path, taken: set[str]) -> Path:
    if dest.name.lower() not in taken and not dest.exists():
        return dest
    stem, ext = dest.stem, dest.suffix
    i = 2
    while True:
        cand = dest.with_name(f"{stem} ({i}){ext}")
        if cand.name.lower() not in taken and not cand.exists():
            return cand
        i += 1


def plan(con, rename_all: bool = False) -> list[tuple[str, Path, Path]]:
    lit = str(config.LITERATURE_DIR)
    rows = con.execute(
        "SELECT doc_id, path, title, authors FROM documents WHERE path LIKE ?",
        [lit + "%"],
    ).fetchall()
    out: list[tuple[str, Path, Path]] = []
    taken: set[str] = set()
    for doc_id, path, title, authors in rows:
        src = Path(path)
        if not title or len(title.strip()) < 5:
            continue
        cur_stem = src.stem
        des = desired_stem(title, authors)
        if not des or des.lower() == cur_stem.lower():
            continue
        junky = _is_junky(cur_stem)
        if not (junky or rename_all):
            continue
        # Guard: don't overwrite a real per-paper name with a generic front-matter
        # title when we have no author to anchor it.
        if not author_label(authors) and _FRONTMATTER_RE.search(title):
            continue
        # Guard: proceedings split papers ("NN - Title") with no recovered author  - 
        # keep the paper title rather than dropping to a bare (possibly generic) title.
        if not author_label(authors) and "(papers)" in str(src.parent) and re.match(r"^\d+\s*-\s", cur_stem):
            continue
        dest = _unique(src.with_name(des + src.suffix), taken)
        taken.add(dest.name.lower())
        out.append((doc_id, src, dest))
    return out


def apply(con, items: list[tuple[str, Path, Path]]) -> int:
    done = 0
    for doc_id, src, dest in items:
        if not src.exists():
            continue
        src.rename(dest)
        rel = str(dest.relative_to(config.DOCS_ROOT))
        con.execute(
            "UPDATE documents SET path = ?, rel_path = ? WHERE doc_id = ?",
            [str(dest), rel, doc_id],
        )
        done += 1
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="perform the renames (default: dry-run)")
    p.add_argument("--all", dest="rename_all", action="store_true",
                   help="canonicalize every file, not just junky-named ones")
    p.add_argument("--limit", type=int, help="show at most N in the dry-run preview")
    args = p.parse_args(argv)

    con = db.connect(read_only=not args.apply)
    items = plan(con, rename_all=args.rename_all)
    print(f"{len(items)} file(s) to rename"
          + (" (canonicalize-all mode)" if args.rename_all else " (junky names)"))

    if not args.apply:
        for _id, src, dest in items[: args.limit or len(items)]:
            print(f"  {src.name}\n     -> {dest.name}")
        print(f"\nDry-run. Re-run with --apply to rename {len(items)} file(s).")
        return 0

    done = apply(con, items)
    con.close()
    print(f"renamed {done} file(s) and updated the index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
