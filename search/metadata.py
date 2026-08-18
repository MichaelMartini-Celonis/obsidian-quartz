"""Phase A of ``DESIGN-ocr-metadata.md``: container metadata, abstracts, provenance.

Everything here is deterministic and free: a filesystem stat, a PDF container
read (no text extraction), or a scan of text the index already holds. No model,
no network, no GPU — which is why this phase runs regardless of what is decided
about OCR.

It fills three gaps the design measured:

* **Tier 0 container fields.** ``pdf_created`` is frequently the only reliable
  date on a preprint whose text shows no year; ``pdf_producer`` separates
  born-digital from scanned; ``has_text_layer`` / ``chars_per_page`` materialise
  the OCR trigger that was previously recomputed with ad-hoc SQL joins.
* **The empty ``abstract`` column.** The column has existed since Phase 0 and
  nothing ever wrote it. A keyword-anchored scan of the opening chunks recovers
  a real abstract where the document actually has one — deliberately *not*
  guessing "first paragraph", so an unpopulated abstract keeps meaning "no
  abstract found" rather than "some prose".
* **Per-field provenance.** ``field_provenance`` records where each value came
  from, so a corpus assembled from six extraction sources stays auditable and
  selectively refreshable, and a later LLM pass cannot silently overwrite a
  value that came from a stronger source.

The merge rule is precedence-based:

    manual > crossref/dblp/unpaywall > xmp > pdf_info > ocr_vlm > llm
           > text_heuristic > filename

A higher-precedence source overwrites; an equal one only fills NULLs. This
generalises what ``enrich.promote_cached`` already does informally with COALESCE.

Usage::

    scripts/.venv/bin/python -m search.cli metadata            # backfill what's missing
    scripts/.venv/bin/python -m search.cli metadata --redo     # recompute everything
    scripts/.venv/bin/python -m search.cli metadata --status   # coverage report
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

# Tier-0 columns, added to `documents` with additive ALTERs in the style db.py
# already uses. `metadata_at` is last so a partially-backfilled corpus is
# resumable: a NULL means "this document has not been through the stage".
TIER0_COLUMNS: list[tuple[str, str]] = [
    ("imported_at", "TIMESTAMP"),
    ("file_created", "TIMESTAMP"),
    ("pdf_created", "TIMESTAMP"),
    ("pdf_modified", "TIMESTAMP"),
    ("pdf_producer", "TEXT"),
    ("pdf_creator", "TEXT"),
    ("pdf_version", "TEXT"),
    ("is_encrypted", "BOOLEAN"),
    ("is_tagged", "BOOLEAN"),
    ("has_outline", "BOOLEAN"),
    ("has_text_layer", "BOOLEAN"),
    ("chars_per_page", "DOUBLE"),
    ("text_readable_ratio", "DOUBLE"),
    ("text_garbled", "BOOLEAN"),
    ("embedded_font_count", "INTEGER"),
    ("is_image_only", "BOOLEAN"),
    ("page_width_pt", "DOUBLE"),
    ("page_height_pt", "DOUBLE"),
    ("orientation", "TEXT"),
    ("xmp_title", "TEXT"),
    ("xmp_creators", "TEXT[]"),
    ("xmp_subjects", "TEXT[]"),
    ("language", "TEXT"),
    ("n_embedded_files", "INTEGER"),
    ("metadata_at", "TIMESTAMP"),
]

PRECEDENCE: dict[str, int] = {
    "manual": 100,
    "crossref": 90,
    "dblp": 88,
    "unpaywall": 86,
    "xmp": 70,
    "pdf_info": 60,
    "ocr_vlm": 50,
    "llm": 40,
    "text_heuristic": 30,
    "filename": 10,
}


def ensure_schema(con) -> None:
    for name, sqltype in TIER0_COLUMNS:
        con.execute(f"ALTER TABLE documents ADD COLUMN IF NOT EXISTS {name} {sqltype}")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS field_provenance (
            doc_id TEXT,
            field TEXT,
            source TEXT,
            confidence DOUBLE,
            extracted_at TIMESTAMP,
            PRIMARY KEY (doc_id, field, source)
        )
        """
    )


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def record_provenance(con, doc_id: str, field: str, source: str,
                      confidence: float = 1.0) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO field_provenance
            (doc_id, field, source, confidence, extracted_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [doc_id, field, source, confidence],
    )


def best_source(con, doc_id: str, field: str) -> str | None:
    """The strongest source that has already written ``field``."""
    rows = con.execute(
        "SELECT source FROM field_provenance WHERE doc_id = ? AND field = ?",
        [doc_id, field],
    ).fetchall()
    known = [(PRECEDENCE.get(s, 0), s) for (s,) in rows]
    return max(known)[1] if known else None


def may_write(con, doc_id: str, field: str, source: str,
              current_value_is_null: bool) -> bool:
    """Apply the precedence rule: outrank to overwrite, tie to fill a NULL."""
    held = best_source(con, doc_id, field)
    if held is None:
        return True
    mine, theirs = PRECEDENCE.get(source, 0), PRECEDENCE.get(held, 0)
    if mine > theirs:
        return True
    return mine == theirs and current_value_is_null


# ---------------------------------------------------------------------------
# tier 0: the PDF container
# ---------------------------------------------------------------------------

_PDF_DATE_RE = re.compile(r"D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?")


def _pdf_date(raw) -> datetime | None:
    """Parse a PDF ``/CreationDate`` (``D:YYYYMMDDHHmmSS±HH'mm'``) leniently."""
    if not raw:
        return None
    m = _PDF_DATE_RE.match(str(raw).strip())
    if not m:
        return None
    year = int(m.group(1))
    if not 1980 <= year <= 2100:
        return None
    parts = [int(g) if g else d for g, d in
             zip(m.groups()[1:], [1, 1, 0, 0, 0])]
    try:
        return datetime(year, max(parts[0], 1), max(parts[1], 1),
                        parts[2] % 24, parts[3] % 60, parts[4] % 60)
    except ValueError:
        return None


def _xmp_values(reader) -> tuple[str | None, list[str], list[str], str | None]:
    """Title / creators / subjects / language from the XMP packet.

    The XMP packet is usually better than the Info dictionary — and Phase 0
    ignored it entirely.
    """
    try:
        xmp = reader.xmp_metadata
    except Exception:  # noqa: BLE001
        return None, [], [], None
    if xmp is None:
        return None, [], [], None

    def _first(value):
        if isinstance(value, dict):
            value = next(iter(value.values()), None)
        if isinstance(value, list):
            value = value[0] if value else None
        return str(value).strip() if value else None

    def _list(value) -> list[str]:
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, str):
            value = [value]
        return [str(v).strip() for v in (value or []) if str(v).strip()]

    title = creators = subjects = language = None
    try:
        title = _first(xmp.dc_title)
    except Exception:  # noqa: BLE001
        title = None
    try:
        creators = _list(xmp.dc_creator)
    except Exception:  # noqa: BLE001
        creators = []
    try:
        subjects = _list(xmp.dc_subject)
    except Exception:  # noqa: BLE001
        subjects = []
    try:
        language = _first(xmp.dc_language)
    except Exception:  # noqa: BLE001
        language = None
    return title, creators or [], subjects or [], language


def container_metadata(path: Path) -> dict:
    """Tier-0 fields for one file. Never raises; unknown fields stay absent."""
    out: dict = {}
    try:
        st = path.stat()
        birth = getattr(st, "st_birthtime", None)
        if birth:
            out["file_created"] = datetime.fromtimestamp(birth, timezone.utc).replace(tzinfo=None)
    except OSError:
        return out

    if path.suffix.lower() != ".pdf":
        return out

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception:  # noqa: BLE001
        return out

    try:
        out["is_encrypted"] = bool(reader.is_encrypted)
    except Exception:  # noqa: BLE001
        pass
    try:
        info = reader.metadata or {}
        out["pdf_created"] = _pdf_date(info.get("/CreationDate"))
        out["pdf_modified"] = _pdf_date(info.get("/ModDate"))
        producer = info.get("/Producer")
        creator = info.get("/Creator")
        out["pdf_producer"] = str(producer).strip() if producer else None
        out["pdf_creator"] = str(creator).strip() if creator else None
    except Exception:  # noqa: BLE001
        pass
    try:
        out["pdf_version"] = (reader.pdf_header or "").replace("%PDF-", "").strip() or None
    except Exception:  # noqa: BLE001
        pass
    try:
        root = reader.trailer["/Root"]
        out["is_tagged"] = "/StructTreeRoot" in root
        out["has_outline"] = "/Outlines" in root
        names = root.get("/Names") or {}
        embedded = names.get("/EmbeddedFiles") if hasattr(names, "get") else None
        out["n_embedded_files"] = len((embedded or {}).get("/Names", []) or []) // 2
        lang = root.get("/Lang")
        if lang:
            out["language"] = str(lang).strip() or None
    except Exception:  # noqa: BLE001
        pass

    # Page geometry + fonts from page 1 only: a slide deck is landscape 4:3, and
    # zero embedded fonts on the first page is the cheapest scan signal there is.
    try:
        page = reader.pages[0]
        box = page.mediabox
        width, height = float(box.width), float(box.height)
        out["page_width_pt"], out["page_height_pt"] = width, height
        out["orientation"] = "landscape" if width > height else "portrait"
        fonts = ((page.get("/Resources") or {}).get("/Font") or {})
        out["embedded_font_count"] = len(fonts)
    except Exception:  # noqa: BLE001
        pass

    xmp_title, creators, subjects, xmp_lang = _xmp_values(reader)
    out["xmp_title"] = xmp_title
    out["xmp_creators"] = creators
    out["xmp_subjects"] = subjects
    if xmp_lang and not out.get("language"):
        out["language"] = xmp_lang
    return out


# ---------------------------------------------------------------------------
# abstracts, from text the index already holds
# ---------------------------------------------------------------------------

# The anchor must open a line: prose like "in abstract terms, we ..." mentions
# the word mid-sentence and would otherwise be mistaken for a heading.
_ABSTRACT_START = re.compile(
    r"(?:\A|\n)[ \t]*(?:\d+[.)]\s*)?a\s?b\s?s\s?t\s?r\s?a\s?c\s?t\b"
    r"[ \t]*[:.\u2014\u2013-]?[ \t]*\n?", re.I)
# Where an abstract stops: the next structural heading of a paper.
_ABSTRACT_END = re.compile(
    r"\n\s*(?:1\s*[.)]?\s+introduction|i\.\s+introduction|introduction\s*\n"
    r"|keywords?\b|key\s+words\b|index\s+terms\b|ccs\s+concepts\b"
    r"|categories\s+and\s+subject\s+descriptors\b|acm\s+reference\b"
    r"|general\s+terms\b|\u00a9\s*\d{4})", re.I)

MIN_ABSTRACT_CHARS = 120
MAX_ABSTRACT_CHARS = 3000


def abstract_from_text(text: str) -> str | None:
    """Pull a real abstract out of front-matter text, or return ``None``.

    Anchored on the word "Abstract" (tolerating the letter-spaced form some
    typesetters emit) rather than assuming the opening paragraph is one, so the
    column keeps a precise meaning.
    """
    if not text:
        return None
    m = _ABSTRACT_START.search(text[:20000])
    if not m:
        return None
    body = text[m.end():m.end() + MAX_ABSTRACT_CHARS + 2000]
    end = _ABSTRACT_END.search(body)
    if end:
        body = body[:end.start()]
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) < MIN_ABSTRACT_CHARS:
        return None
    # An abstract begins a sentence. A lowercase opening means the anchor landed
    # inside running text (a hyphenated line break, a citation, a footnote).
    if not (body[0].isupper() or body[0].isdigit() or body[0] in "\"'“"):
        return None
    return body[:MAX_ABSTRACT_CHARS].strip()


def front_matter_text(con, doc_id: str, max_chunks: int = 6) -> str:
    rows = con.execute(
        "SELECT text FROM chunks WHERE doc_id = ? ORDER BY ordinal LIMIT ?",
        [doc_id, max_chunks],
    ).fetchall()
    return "\n".join(r[0] or "" for r in rows)


# ---------------------------------------------------------------------------
# the stage
# ---------------------------------------------------------------------------

# Function words carry no topical information, which is exactly why they make a
# good readability probe: any genuine page of prose has plenty of them. Scored
# per language and taken at the best-scoring one, so a German paper is measured
# against German rather than diluted by a merged vocabulary.
_FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the of and to in a is that for it as with on by are be this from or an "
        "at we which not have has can if but their they its all one more been "
        "also such when than then these those there our may each".split()),
    "de": frozenset(
        "der die das und in den von zu mit dem des auf für ist im nicht ein "
        "eine als auch es an werden aus er hat dass sie nach bei um sich oder "
        "durch wird beim eines einer diese".split()),
    "nl": frozenset(
        "de het een en van in is dat op te met voor zijn niet aan er om ook als "
        "door bij naar dan uit maar over deze worden wordt kan heeft".split()),
    "fr": frozenset(
        "le la les des de du et un une est en que dans pour qui sur pas au aux "
        "par plus avec ce cette ne se sont nous il elle mais ou son".split()),
}
_WORD_RE = re.compile(r"[a-zà-öø-ÿ]+")

# Below this share of function words the "text" is not language. Real prose in
# this corpus sits at 0.20–0.39; a slide deck, a SQL reference guide or a page of
# Slovenian still reaches 0.033, so the bar has to stay under that.
GARBLED_RATIO = 0.03
GARBLED_MIN_WORDS = 200

# ...which alone is not enough, because the worst offenders score *above* the
# bar: a CID font with identity encoding extracts as control codes with enough
# stray letters to fake a few function words. Those are caught on a second,
# orthogonal axis — characters with no textual meaning at all — but only as a
# tiebreaker for documents that already read poorly. Used on its own it condemns
# healthy papers, because maths and ligature-heavy PDFs legitimately emit private
# -use codepoints while extracting perfectly well otherwise.
UNMAPPABLE_RATIO = 0.02
WEAK_RATIO = 0.10

# A third failure mode escapes both tests: an extractor that recovers every
# glyph but no word boundaries, so a page arrives as
# "Thesearethewordsusedbyanoutstandingcritic". Enough short words survive to
# score just over the function-word bar, and every character is perfectly
# mappable, yet no query for a phrase in that page can ever match it. It shows
# up instead as characters marooned in absurdly long runs: healthy documents in
# this corpus sit at 0.003 (p90) and 0.10 (p99), the damaged ones at 0.26–0.85.
GLUED_RATIO = 0.25
GLUED_MIN_LEN = 20
_RUN_RE = re.compile(r"[a-zA-Z\u00c0-\u024f]+")


def glued_ratio(text: str) -> float:
    """Share of letters stranded inside words too long to be words."""
    runs = _RUN_RE.findall(text)
    total = sum(len(r) for r in runs)
    if not total:
        return 0.0
    return sum(len(r) for r in runs if len(r) >= GLUED_MIN_LEN) / total


def readable_ratio(text: str) -> float | None:
    """How language-like a text layer is, as a share of function words.

    A dense text layer is not the same as a *usable* one. Some PDFs extract to
    glyph names (``/BW/CT/DA``), which passes every length-based check while
    being unsearchable and worthless as index content.
    Returns None when there is too little text to judge.
    """
    words = _WORD_RE.findall(text.lower())
    if len(words) < GARBLED_MIN_WORDS:
        return None
    return max(sum(1 for w in words if w in vocab) / len(words)
               for vocab in _FUNCTION_WORDS.values())


def unmappable_ratio(text: str) -> float:
    """Share of characters that cannot be text: C0 controls, PUA, U+FFFD."""
    if not text:
        return 0.0
    bad = sum(1 for ch in text
              if (ch < " " and ch not in "\t\n\r")
              or ch == "\ufffd"
              or "\ue000" <= ch <= "\uf8ff")
    return bad / len(text)


def is_garbled(text: str) -> tuple[bool, float | None]:
    """Whether a text layer is unusable, plus the readability score behind it."""
    ratio = readable_ratio(text)
    unmappable = unmappable_ratio(text)
    if glued_ratio(text) > GLUED_RATIO:
        return True, ratio
    if ratio is None:
        return unmappable > UNMAPPABLE_RATIO, None
    if ratio < GARBLED_RATIO:
        return True, ratio
    return (ratio < WEAK_RATIO and unmappable > UNMAPPABLE_RATIO), ratio


# Both the metadata stage and the indexer judge the same documents, so they have
# to read the same thing: sampling the opening alone would let a clean cover page
# vouch for a broken body, and disagreeing samples let a document be flagged in
# one place and silently skipped in the other.
SAMPLE_PARTS = 16


def spread_sample(parts: list[str], n: int = SAMPLE_PARTS) -> str:
    """Text drawn evenly across a document rather than from its first pages."""
    if not parts:
        return ""
    step = max(1, len(parts) // n)
    return "\n".join(parts[::step][:n])


def readability(text: str) -> float | None:
    """A single quality score for a text layer, for *comparing* two of them.

    The thresholds above answer "is this bad enough to OCR?". Choosing between an
    existing layer and a fresh reading of the same pages is a different question,
    and answering it with a threshold is what let a document sitting near the bar
    keep its unusable text: whichever side of the line it fell on, some stage
    disagreed. A comparison has no line to fall on. Function-word share carries
    the signal; glue discounts it, since text whose words have been run together
    is unsearchable however well it reads by vocabulary.
    """
    ratio = readable_ratio(text)
    if ratio is None:
        return None
    return ratio * (1.0 - glued_ratio(text))


def _derived_text_stats(con, doc_id: str, n_pages: int | None,
                        filetype: str) -> dict:
    row = con.execute(
        "SELECT count(*), coalesce(sum(length(text)), 0) FROM chunks WHERE doc_id = ?",
        [doc_id],
    ).fetchone()
    n_chunks, n_chars = int(row[0]), int(row[1])
    pages = n_pages or 0
    out = {
        "has_text_layer": n_chunks > 0,
        "chars_per_page": (n_chars / pages) if pages else None,
    }
    if filetype == ".pdf":
        out["is_image_only"] = n_chunks == 0
    if n_chunks:
        sample = spread_sample([
            r[0] or "" for r in con.execute(
                "SELECT text FROM chunks WHERE doc_id = ? ORDER BY ordinal",
                [doc_id]).fetchall()])
        garbled, ratio = is_garbled(sample)
        out["text_readable_ratio"] = ratio
        # `text_garbled` means "the text layer failed, re-read the pages", which
        # only a PDF can do. In markdown and notebooks the text *is* the
        # document, so a low score there says the content is structured (a dbdb
        # fact sheet, a post that is mostly a data blob) — true, but not a defect
        # and not actionable. Scoring stays; the verdict does not.
        out["text_garbled"] = garbled and filetype == ".pdf"
    return out


def backfill(con, limit: int | None = None, redo: bool = False,
             progress_every: int = 250) -> dict:
    """Populate tier-0 fields, abstracts and provenance for indexed documents."""
    ensure_schema(con)
    where = "" if redo else "WHERE metadata_at IS NULL"
    sql = (f"SELECT doc_id, path, filetype, n_pages, abstract, indexed_at, "
           f"imported_at FROM documents {where} ORDER BY rel_path")
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = con.execute(sql).fetchall()

    stats = {"total": len(rows), "updated": 0, "abstracts": 0, "missing_file": 0,
             "pdf_dates": 0, "image_only": 0}
    print(f"metadata backfill: {len(rows)} documents "
          f"({'redo' if redo else 'missing only'})")

    for i, (doc_id, path, filetype, n_pages, abstract, indexed_at,
            imported_at) in enumerate(rows, 1):
        p = Path(path)
        fields = {}
        if p.exists():
            fields.update(container_metadata(p))
        else:
            stats["missing_file"] += 1
        fields.update(_derived_text_stats(con, doc_id, n_pages, filetype or ""))
        # First-seen time: the best evidence available without a prior record is
        # when the indexer first saw the file.
        fields["imported_at"] = imported_at or indexed_at

        if fields.get("pdf_created"):
            stats["pdf_dates"] += 1
        if fields.get("is_image_only"):
            stats["image_only"] += 1

        sets, params = [], []
        for name, value in fields.items():
            if value is None and name not in ("chars_per_page",
                                              "text_readable_ratio"):
                continue
            sets.append(f"{name} = ?")
            params.append(value)
            if name in ("pdf_created", "pdf_modified", "pdf_producer",
                        "pdf_creator", "pdf_version", "language"):
                record_provenance(con, doc_id, name, "pdf_info")
            elif name.startswith("xmp_"):
                record_provenance(con, doc_id, name, "xmp")
            else:
                record_provenance(con, doc_id, name, "filesystem"
                                  if name in ("file_created", "imported_at")
                                  else "text_heuristic")

        if not abstract:
            found = abstract_from_text(front_matter_text(con, doc_id))
            if found and may_write(con, doc_id, "abstract", "text_heuristic",
                                   current_value_is_null=True):
                sets.append("abstract = ?")
                params.append(found)
                record_provenance(con, doc_id, "abstract", "text_heuristic", 0.7)
                stats["abstracts"] += 1

        sets.append("metadata_at = CURRENT_TIMESTAMP")
        con.execute(f"UPDATE documents SET {', '.join(sets)} WHERE doc_id = ?",
                    [*params, doc_id])
        stats["updated"] += 1
        if progress_every and i % progress_every == 0:
            print(f"  [{i}/{len(rows)}] abstracts={stats['abstracts']} "
                  f"pdf_dates={stats['pdf_dates']}")
    return stats


def status(con) -> list[tuple[str, str]]:
    ensure_schema(con)
    total = con.execute("SELECT count(*) FROM documents").fetchone()[0] or 1

    def pct(n) -> str:
        return f"{n:6d}  {100 * n / total:5.1f}%"

    checks = [
        ("documents", "SELECT count(*) FROM documents"),
        ("through the stage", "SELECT count(*) FROM documents WHERE metadata_at IS NOT NULL"),
        ("with abstract", "SELECT count(*) FROM documents WHERE abstract IS NOT NULL"),
        ("with pdf_created", "SELECT count(*) FROM documents WHERE pdf_created IS NOT NULL"),
        ("with pdf_producer", "SELECT count(*) FROM documents WHERE pdf_producer IS NOT NULL"),
        ("with xmp_title", "SELECT count(*) FROM documents WHERE xmp_title IS NOT NULL"),
        ("with language", "SELECT count(*) FROM documents WHERE language IS NOT NULL"),
        ("no text layer", "SELECT count(*) FROM documents WHERE has_text_layer = FALSE"),
        ("image-only PDFs", "SELECT count(*) FROM documents WHERE is_image_only"),
        ("thin text (<200 chars/page)",
         "SELECT count(*) FROM documents WHERE chars_per_page < 200 AND has_text_layer"),
        ("garbled text layer (unreadable, glued or unmappable)",
         "SELECT count(*) FROM documents WHERE text_garbled"),
        ("landscape (slide-shaped)",
         "SELECT count(*) FROM documents WHERE orientation = 'landscape'"),
        ("provenance rows", "SELECT count(*) FROM field_provenance"),
        ("year still missing", "SELECT count(*) FROM documents WHERE year IS NULL"),
        ("year missing but pdf_created known",
         "SELECT count(*) FROM documents WHERE year IS NULL AND pdf_created IS NOT NULL"),
    ]
    return [(label, pct(con.execute(q).fetchone()[0])) for label, q in checks]
