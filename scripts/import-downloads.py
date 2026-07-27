#!/usr/bin/env python3
"""Import files dropped in the top-level Inbox into the Literature library.

Layout (all under ~/docs):
  Inbox/        <- drop papers/documents here to be integrated
  Literature/   <- classified, named paper library (destination)
  scripts/      <- this script

Run:  python3 scripts/import-downloads.py   (from ~/docs)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

DOCS_ROOT = Path(__file__).resolve().parent.parent
LITERATURE_DIR = DOCS_ROOT / "Literature"
INBOX = DOCS_ROOT / "Inbox"
MANIFEST = INBOX / "_last-import.log"

SKIP_SUFFIXES = {
    ".dmg",
    ".zip",
    ".html",
    ".png",
    ".crdownload",
    ".localized",
    ".py",
}
SKIP_NAMES = {".ds_store", ".localized", "readme.md"}

IMPORT_SUFFIXES = {".pdf", ".docx", ".pptx", ".ipynb", ".bpmn", ".md", ".xlsx", ".txt", ".epub"}

BOILERPLATE_TITLES = {
    "untitled",
    "word document",
    "microsoft word - document",
    "document",
    "presentation",
}

CLASSIFICATION_RULES: list[tuple[str, list[str]]] = [
    ("Process Mining/Object-centric", [
        "object-centric", "object centric", "ocel", "ocpm", "multidimensional event",
        "event graph", "knowledge graph", "event knowledge graph", "pi graph",
    ]),
    ("Process Mining/Discovery", [
        "process discovery", "discovery algorithm", "process model discovery", "alpha miner",
        "inductive miner", "functional dependency", "unique discovery", "tane",
    ]),
    ("Process Mining/Conformance Checking", [
        "conformance", "alignment", "replay", "process model-log",
    ]),
    ("Process Mining/Stochastic Process Mining", [
        "stochastic", "queueing", "queue mining", "markov",
    ]),
    ("Process Mining/Simulation", [
        "simulation", "petri net", "colored petri", "cpn", "workflow net",
    ]),
    ("Process Mining/AI", [
        "graph neural", "large language model", " llm", "machine learning",
        "deep learning", "neural network", "differentiable pooling", "embedding",
    ]),
    ("Process Mining/Visual Analytics", [
        "visualization", "visual analytics", "graph drawing", "layout", "honvis",
    ]),
    ("Process Mining/Architecture", [
        "scalability", "data structure", "dataframe", "event store", "architecture",
    ]),
    ("Process Mining/Event Log extraction", [
        "event log extraction", "event data extraction", "event log generation",
    ]),
    ("Process Mining/Resource Mining", [
        "resource mining", "organizational", "organisational",
    ]),
    ("Process Mining/Uncertainty", [
        "uncertain", "probabilistic", "probability",
    ]),
    ("Process Mining/Methodology", [
        "comparative process mining", "process mining methodology",
    ]),
    ("Process Querying", [
        "query language", "sql", "sparql", "bpql", "process query", "pql",
        "query dependency", "querying structural",
    ]),
    ("Process Modeling", [
        "bpmn", "process model", "workflow model", "case management", "artifact",
        "dcr graph", "ontology", "bounded context", "entity relationship",
        "entity-relationship", "data model", "relational model", "er model",
        "business process model", "declarative process",
    ]),
    ("Engineering", [
        "software design", "philosophy of software",
    ]),
]


# --- Celonis-internal detection --------------------------------------------
# Docs matching these land in the "Celonis Internal/" collection, which the
# search index flags as internal. Office exports (Google Docs/Slides/Sheets)
# are treated as internal working material; PDFs need a strong Celonis codename
# so genuine external literature that merely mentions Celonis stays external.
CELONIS_INTERNAL_DIR = "Celonis Internal"
OFFICE_INTERNAL_SUFFIXES = {".docx", ".pptx", ".xlsx"}
# Celonis internal codenames / phrases. Matched with word boundaries (see
# is_celonis_internal) so short tokens like "wvda" no longer match unrelated
# words such as "wvdaalst" (van der Aalst's email in *public* papers).
STRONG_CELONIS_MARKERS = [
    "pig-sl", "pigsl", "pi graph", "pig level", "pig packages", "pig boxes",
    "pig data team", "saola", "celosphere", "ems 2.0", "ems2.0",
    "cpm meta model", "core meta model", "ccmm", "yet another celonis",
    "yet-another-ccmm", "charkha", "arcline", "relayering",
    "knowledge layer glossary", "pma-wvda", "etot", "comp-gateway", "slides-ems",
]
# Terms that also appear in *public* papers by Celonis-affiliated authors, e.g.
# van der Aalst ("execution management") or Polyvyanyy's academic "PQL" /
# Process Query Language. Only treat them as internal when "celonis" is present.
CELONIS_WEAK_MARKERS = [
    "pql", "object-centrism", "consistent ocdm", "execution management",
]


@dataclass
class Biblio:
    title: str
    authors: list[str]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def slugify_filename(text: str, max_len: int = 150) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s.,'()-]", "", text)
    text = text.replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text or "untitled"


def is_boilerplate(text: str) -> bool:
    lowered = clean(text).lower()
    if not lowered or lowered in BOILERPLATE_TITLES:
        return True
    if lowered.startswith("microsoft word"):
        return True
    if lowered.startswith("arxiv:") or re.match(r"arxiv[\d.v\[\]\s]+", lowered):
        return True
    if re.match(r"^\d+(st|nd|rd|th)\s+", lowered):
        return True
    if "@" in lowered and len(lowered.split()) <= 4:
        return True
    if lowered in {"abstract", "introduction"}:
        return True
    return False


def surname(full_name: str) -> str:
    name = clean(full_name)
    name = re.sub(r"^\d+(st|nd|rd|th)\s+", "", name, flags=re.I)
    name = re.sub(r"\s*\(B\)\s*$", "", name)
    parts = name.split()
    if not parts:
        return "Unknown"
    particles = {"van", "der", "de", "den", "von", "la", "le", "du"}
    if len(parts) >= 2 and parts[-2].lower() in particles:
        return " ".join(parts[-2:])
    return parts[-1]


def author_label(authors: list[str]) -> str:
    if not authors:
        return "Unknown"
    surnames = [surname(a) for a in authors if a.strip()]
    if not surnames:
        return "Unknown"
    if len(surnames) == 1:
        return surnames[0]
    if len(surnames) == 2:
        return f"{surnames[0]} and {surnames[1]}"
    return f"{surnames[0]} et al."


def literature_filename(biblio: Biblio, ext: str) -> str:
    title = slugify_filename(biblio.title)
    label = slugify_filename(author_label(biblio.authors))
    return f"{label} - {title}{ext.lower()}"


def parse_authors_from_lines(lines: list[str], title_idx: int) -> list[str]:
    authors: list[str] = []
    for line in lines[title_idx + 1 : title_idx + 12]:
        if is_boilerplate(line):
            continue
        lowered = line.lower()
        if lowered.startswith("abstract"):
            break
        if any(tok in lowered for tok in ("university", "institute", "department", "laboratory", "proceedings", "acm ", "ieee ")):
            continue
        if re.search(r"@|\.edu|\.ac\.|\.org|\.com", line, re.I):
            continue
        if re.match(r"^\d+(st|nd|rd|th)\s+", line, re.I):
            line = re.sub(r"^\d+(st|nd|rd|th)\s+", "", line, flags=re.I)
        if " and " in line or "," in line:
            chunks = re.split(r",|\band\b", line)
            for chunk in chunks:
                chunk = clean(chunk)
                if chunk and len(chunk.split()) <= 5 and not is_boilerplate(chunk):
                    authors.append(chunk)
            if authors:
                return authors[:8]
        if 2 <= len(line.split()) <= 5:
            authors.append(line)
            if len(authors) >= 6:
                break
    return authors[:8]


def extract_pdf_biblio(path: Path) -> Biblio:
    reader = PdfReader(str(path))
    title: str | None = None
    authors: list[str] = []

    meta = reader.metadata
    if meta and meta.title and not is_boilerplate(str(meta.title)):
        title = clean(str(meta.title))
    if meta and meta.author:
        authors = [clean(a) for a in str(meta.author).split(",") if clean(a)]

    text = ""
    for i in range(min(2, len(reader.pages))):
        text += (reader.pages[i].extract_text() or "") + "\n"
    lines = [clean(l) for l in text.splitlines()]
    lines = [l for l in lines if l]

    if not title:
        for i, line in enumerate(lines[:15]):
            if is_boilerplate(line):
                continue
            if len(line.split()) >= 3 and not re.search(r"@(uni|gmail)", line, re.I):
                title = line
                if not authors:
                    authors = parse_authors_from_lines(lines, i)
                break

    if title and not authors:
        for i, line in enumerate(lines):
            if line == title:
                authors = parse_authors_from_lines(lines, i)
                break

    if not title:
        title = path.stem

    return Biblio(title=title, authors=authors)


def extract_docx_biblio(path: Path) -> Biblio:
    doc = Document(str(path))
    title = None
    authors: list[str] = []
    if doc.core_properties.title and not is_boilerplate(doc.core_properties.title):
        title = clean(doc.core_properties.title)
    if doc.core_properties.author:
        authors = [clean(doc.core_properties.author)]
    for para in doc.paragraphs[:25]:
        text = clean(para.text)
        if not text or is_boilerplate(text):
            continue
        style = (para.style.name or "").lower()
        if not title and ("heading" in style or len(text.split()) >= 3):
            title = text
            continue
        if title and not authors and 2 <= len(text.split()) <= 8:
            authors = [text]
            break
    return Biblio(title=title or path.stem, authors=authors)


def extract_ipynb_biblio(path: Path) -> Biblio:
    nb = json.loads(path.read_text(encoding="utf-8"))
    title = path.stem.replace("_", " ")
    for cell in nb.get("cells", [])[:5]:
        if cell.get("cell_type") != "markdown":
            continue
        source = "".join(cell.get("source", []))
        for line in source.splitlines():
            if line.strip().startswith("#"):
                title = clean(line.lstrip("#"))
                break
    return Biblio(title=title, authors=[])


def extract_epub_biblio(path: Path) -> Biblio:
    import zipfile

    title = path.stem.replace("_", " ")
    authors: list[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            opf_name = next(
                (n for n in z.namelist() if n.endswith("content.opf")),
                None,
            )
            if opf_name:
                opf = z.read(opf_name).decode("utf-8", errors="ignore")
                m_title = re.search(r"<dc:title[^>]*>([^<]+)", opf)
                m_creator = re.search(r"<dc:creator[^>]*>([^<]+)", opf)
                if m_title:
                    title = clean(m_title.group(1))
                if m_creator:
                    authors = [clean(m_creator.group(1))]
    except Exception:
        pass
    return Biblio(title=title, authors=authors)


def extract_biblio(path: Path) -> Biblio:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return extract_pdf_biblio(path)
        if ext == ".docx":
            return extract_docx_biblio(path)
        if ext == ".ipynb":
            return extract_ipynb_biblio(path)
        if ext == ".epub":
            return extract_epub_biblio(path)
    except Exception as exc:  # noqa: BLE001 — corrupt/truncated file: don't abort the batch
        print(f"  ! biblio extraction failed for {path.name}: "
              f"{type(exc).__name__}: {exc}; falling back to filename")
    return Biblio(title=path.stem.replace("_", " "), authors=[])


def classify(path: Path, biblio: Biblio) -> str:
    name = path.name.lower()
    haystack = f"{name} {biblio.title.lower()}"
    try:
        if path.suffix.lower() == ".pdf":
            reader = PdfReader(str(path))
            haystack += " " + (reader.pages[0].extract_text() or "")[:2500].lower()
    except Exception:
        pass

    if path.suffix.lower() == ".bpmn":
        return "Process Modeling"
    if "taxonomy" in name:
        return "Process Mining/Object-centric"
    if "sql_query" in name or "query_dependency" in name:
        return "Process Querying"
    if "event_visual" in name:
        return "Process Mining/Visual Analytics"

    for folder, keywords in CLASSIFICATION_RULES:
        if any(k in haystack for k in keywords):
            return folder
    return "Inbox"


def _internal_text_sample(path: Path) -> str:
    """A small text sample used to spot Celonis codenames (best-effort)."""
    try:
        ext = path.suffix.lower()
        if ext == ".pdf":
            reader = PdfReader(str(path))
            meta = reader.metadata or {}
            # Slide-deck PDFs often carry no extractable body text but keep the
            # Celonis codename in the document metadata (title/author/subject).
            meta_text = " ".join(
                str(meta.get(k, "")) for k in ("/Title", "/Author", "/Subject", "/Keywords")
            )
            return (meta_text + " " + (reader.pages[0].extract_text() or ""))[:3000]
        if ext == ".docx":
            doc = Document(str(path))
            return " ".join(p.text for p in doc.paragraphs[:40])
    except Exception:
        pass
    return ""


def is_celonis_internal(path: Path) -> bool:
    haystack = f"{path.name} {_internal_text_sample(path)}".lower()

    def has(term: str) -> bool:
        # Word-boundary match so "wvda" no longer matches "wvdaalst", etc.
        return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", haystack) is not None

    if any(has(m) for m in STRONG_CELONIS_MARKERS):
        return True
    if "celonis" in haystack and any(has(w) for w in CELONIS_WEAK_MARKERS):
        return True
    return path.suffix.lower() in OFFICE_INTERNAL_SUFFIXES


def unique_path(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, ext = dest.stem, dest.suffix
    n = 2
    while True:
        candidate = dest.with_name(f"{stem} ({n}){ext}")
        if not candidate.exists():
            return candidate
        n += 1


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def find_duplicate_in_literature(path: Path, src_hash: str) -> Path | None:
    """Return an existing Literature file that is byte-identical to *path*.

    Size is a cheap pre-filter; a SHA-256 comparison then *confirms* the match,
    so unrelated files that merely share a byte count (e.g. a short markdown
    note vs. a blog post) are no longer treated as duplicates and deleted.
    """
    size = path.stat().st_size
    for candidate in LITERATURE_DIR.rglob("*"):
        if candidate.is_file() and candidate.stat().st_size == size:
            if file_sha256(candidate) == src_hash:
                return candidate
    return None


def collect_inbox_files() -> list[Path]:
    """Recursively collect importable files dropped anywhere in the Inbox."""
    files: list[Path] = []
    if not INBOX.exists():
        return files
    for path in INBOX.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if path.name.lower() in SKIP_NAMES:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.suffix.lower() not in IMPORT_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def import_inbox() -> list[str]:
    logs: list[str] = []
    seen_hashes: dict[str, str] = {}

    for src in collect_inbox_files():
        src_hash = file_sha256(src)
        if src_hash in seen_hashes:
            src.unlink()
            logs.append(f"[skip-dup-batch] {src.name} (identical to {seen_hashes[src_hash]})")
            continue

        existing = find_duplicate_in_literature(src, src_hash)
        if existing:
            src.unlink()
            logs.append(f"[skip-dup-lit] {src.name} -> Literature/{existing.relative_to(LITERATURE_DIR)}")
            continue

        if is_celonis_internal(src):
            # Internal working docs keep their (meaningful) original filename and
            # form their own collection, which the index flags as internal.
            folder = CELONIS_INTERNAL_DIR
            dest_dir = LITERATURE_DIR / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            filename = slugify_filename(src.stem) + src.suffix.lower()
        else:
            biblio = extract_biblio(src)
            folder = classify(src, biblio)
            dest_dir = LITERATURE_DIR / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            if src.suffix.lower() in {".pdf", ".docx", ".epub"} and " - " not in src.stem:
                filename = literature_filename(biblio, src.suffix)
            else:
                filename = slugify_filename(src.stem) + src.suffix.lower()

        dest = unique_path(dest_dir / filename)
        shutil.move(str(src), str(dest))
        seen_hashes[src_hash] = dest.name
        logs.append(
            f"[{folder}] {src.name} -> Literature/{dest.relative_to(LITERATURE_DIR)}"
        )

    return logs


def main() -> None:
    logs = import_inbox()
    INBOX.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text("\n".join(logs) + "\n")
    print("\n".join(logs))
    print(f"\nImported {len([l for l in logs if l.startswith('[') and not 'skip' in l])} files")
    print(f"Wrote {MANIFEST}")


if __name__ == "__main__":
    main()
