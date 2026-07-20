"""Split conference-proceedings PDFs into their constituent papers.

Many volumes under ``Literature/Proceedings/`` are single PDFs bundling dozens
of papers. Indexing them as one document hurts retrieval (one giant blob, one
title, one author set). This tool uses the PDF outline (bookmarks) to cut each
volume into per-paper PDFs so every paper becomes its own document with its own
title / authors in the graph.

Heuristics (robust, conservative — "split where possible"):
  * A *paper* bookmark is a top-level outline entry immediately followed by a
    nested sub-list (its author/section outline). Section headers ("Foundations")
    and front matter ("Preface", "Contents", "Author Index") are not.
  * Page ranges come from consecutive paper start pages. A volume is only split
    if its ranges are sane (mostly monotonic, per-paper length within bounds);
    otherwise it is left untouched and reported as not auto-splittable.

Usage (from ~/docs):
    scripts/.venv/bin/python -m search.split_proceedings --dry-run
    scripts/.venv/bin/python -m search.split_proceedings --apply --move-originals
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from . import config

warnings.filterwarnings("ignore")

PROCEEDINGS_DIR = config.LITERATURE_DIR / "Proceedings"
ORIGINALS_DIR = config.DOCS_ROOT / "imports" / "proceedings-originals"

# Bookmark titles that are front matter / section headers, never papers.
STOP_RE = re.compile(
    r"^\s*(preface|foreword|organization|committee|program committee|"
    r"additional reviewers|reviewers|sponsors?|partners|contents|"
    r"table of contents|author index|subject index|index|editors?|"
    r"message from|keynotes?|invited talks?|tutorials?|panels?|"
    r"title\s?page|copyright|frontmatter|front matter|back ?matter|"
    r"in memoriam|acknowledge?ments?|list of (figures|tables)|abstracts?|"
    r".*\b(forum|workshop|doctoral consortium|demo track)\b\s*\d*\s*$)",
    re.I,
)

# A code-like bookmark (e.g. ICPM "201-001-ICPM2024-51") — use first-page title.
CODE_RE = re.compile(r"^\s*\d")

MIN_VOLUME_PAGES = 100  # below this it is very likely a single paper, not a volume
MIN_PAGES = 5          # a paper shorter than this is almost certainly bogus
MAX_PAGES = 80         # a "paper" longer than this means the outline is wrong
MIN_PAPERS = 4         # volumes with fewer detected papers are left as-is
MIN_VALID_RATIO = 0.8  # fraction of ranges that must be sane to split a volume


@dataclass
class Paper:
    title: str
    start: int          # 1-based inclusive
    end: int = 0        # 1-based inclusive (filled later)

    @property
    def n_pages(self) -> int:
        return self.end - self.start + 1


@dataclass
class VolumePlan:
    path: Path
    n_pages: int
    papers: list[Paper] = field(default_factory=list)
    skipped: bool = False
    reason: str = ""


def _slug(text: str, max_len: int = 130) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s.,'()-]", "", text).replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text or "untitled"


def _first_page_title(reader, start: int) -> str | None:
    """Best-effort real title from the first page of the paper's range."""
    try:
        txt = reader.pages[start - 1].extract_text() or ""
    except Exception:
        return None
    lines = [re.sub(r"\s+", " ", l).strip() for l in txt.splitlines()]
    for line in lines:
        if not line or STOP_RE.match(line):
            continue
        if "@" in line or re.search(r"\.(edu|org|com|ac)\b", line, re.I):
            continue
        # Skip author lines: superscript affiliations ("Adams1"), "(B)", trailing comma.
        if re.search(r"[A-Za-z]\d", line) or "(B)" in line or line.rstrip().endswith(","):
            continue
        if len(line.split()) >= 4 and not line[0].isdigit():
            return line
    return None


def plan_volume(path: Path) -> VolumePlan:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        n_pages = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        return VolumePlan(path, 0, skipped=True, reason=f"unreadable: {exc}")

    if n_pages < MIN_VOLUME_PAGES:
        return VolumePlan(path, n_pages, skipped=True,
                          reason=f"only {n_pages} pages (likely a single paper)")

    try:
        outline = reader.outline
    except Exception as exc:  # noqa: BLE001
        return VolumePlan(path, n_pages, skipped=True, reason=f"no outline: {exc}")

    # Collect top-level entries flagged as "followed by a nested sub-list".
    candidates: list[tuple[str, int]] = []
    has_any_nested = any(isinstance(x, list) for x in outline)
    for i, entry in enumerate(outline):
        if isinstance(entry, list):
            continue
        title = re.sub(r"\s+", " ", str(getattr(entry, "title", "") or "")).strip()
        if not title or STOP_RE.match(title):
            continue
        followed_by_list = i + 1 < len(outline) and isinstance(outline[i + 1], list)
        # Primary signal: paper bookmarks carry a nested author/section list.
        # Fallback for volumes with no nesting at all: accept non-stoplist entries.
        if has_any_nested and not followed_by_list:
            continue
        try:
            page = reader.get_destination_page_number(entry) + 1
        except Exception:
            continue
        candidates.append((title, page))

    if len(candidates) < MIN_PAPERS:
        return VolumePlan(path, n_pages, skipped=True,
                          reason=f"only {len(candidates)} paper bookmarks")

    # Sort by page, drop non-increasing / duplicate starts.
    candidates.sort(key=lambda c: c[1])
    papers: list[Paper] = []
    last = 0
    for title, page in candidates:
        if page <= last:
            continue
        papers.append(Paper(title=title, start=page))
        last = page

    # Fill end pages; last paper runs to the end of the document.
    for j, p in enumerate(papers):
        p.end = (papers[j + 1].start - 1) if j + 1 < len(papers) else n_pages

    valid = [p for p in papers if MIN_PAGES <= p.n_pages <= MAX_PAGES]
    ratio = len(valid) / len(papers) if papers else 0.0
    if ratio < MIN_VALID_RATIO:
        return VolumePlan(path, n_pages, papers=papers, skipped=True,
                          reason=f"unreliable outline ({len(valid)}/{len(papers)} ranges sane)")

    # Keep only sane ranges (drops the odd bogus one in an otherwise-good volume).
    plan = VolumePlan(path, n_pages, papers=valid)
    # Prefer a real first-page title only when the bookmark is code-like (ICPM ids).
    for p in plan.papers:
        if CODE_RE.match(p.title):
            better = _first_page_title(reader, p.start)
            if better:
                p.title = better
    return plan


def apply_plan(plan: VolumePlan, move_originals: bool) -> int:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(plan.path))
    out_dir = plan.path.parent / f"{plan.path.stem} (papers)"
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for n, p in enumerate(plan.papers, 1):
        writer = PdfWriter()
        for page_idx in range(p.start - 1, p.end):
            writer.add_page(reader.pages[page_idx])
        fname = f"{n:02d} - {_slug(p.title)}.pdf"
        dest = out_dir / fname
        with dest.open("wb") as fh:
            writer.write(fh)
        written += 1

    if move_originals:
        rel = plan.path.relative_to(config.LITERATURE_DIR)
        target = ORIGINALS_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        plan.path.rename(target)
    return written


def iter_proceedings() -> list[Path]:
    if not PROCEEDINGS_DIR.exists():
        return []
    return sorted(
        p for p in PROCEEDINGS_DIR.rglob("*.pdf")
        if "(papers)" not in str(p.parent)
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Split proceedings PDFs into papers")
    ap.add_argument("--apply", action="store_true", help="write split PDFs (default: dry-run)")
    ap.add_argument("--move-originals", action="store_true",
                    help="move split monolith PDFs to imports/proceedings-originals/")
    ap.add_argument("--only", help="substring filter on path")
    args = ap.parse_args(argv)

    files = iter_proceedings()
    if args.only:
        files = [f for f in files if args.only.lower() in str(f).lower()]
    if not files:
        print(f"No proceedings PDFs under {PROCEEDINGS_DIR}")
        return 0

    total_papers = 0
    split_vols = 0
    for path in files:
        plan = plan_volume(path)
        rel = path.relative_to(config.LITERATURE_DIR)
        if plan.skipped:
            print(f"[skip] {rel}  ({plan.reason})")
            continue
        split_vols += 1
        total_papers += len(plan.papers)
        print(f"[split] {rel}  -> {len(plan.papers)} papers "
              f"(pages {plan.papers[0].start}-{plan.papers[-1].end})")
        if args.apply:
            n = apply_plan(plan, args.move_originals)
            print(f"         wrote {n} PDFs to '{path.stem} (papers)/'"
                  + ("  [original moved]" if args.move_originals else ""))
        else:
            for p in plan.papers[:4]:
                print(f"           p{p.start:>4}-{p.end:<4} ({p.n_pages:>2}p)  {p.title[:80]}")
            if len(plan.papers) > 4:
                print(f"           ... +{len(plan.papers) - 4} more")

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] {split_vols} volumes splittable, {total_papers} papers total, "
          f"{len(files) - split_vols} left as-is.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
