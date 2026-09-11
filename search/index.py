"""Incremental ingest pipeline: discover -> extract -> chunk -> embed -> upsert.

Idempotent: a file whose content hash (doc_id) and (mtime, size) are unchanged
is skipped. Embeddings are cached by (model, text_hash) so re-indexing never
re-embeds unchanged text.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from . import chunk as chunkmod
from . import config
from . import db as dbmod
from . import extract as extractmod

# Lone UTF-16 surrogate code points (U+D800–U+DFFF) occasionally leak out of
# PDF text extraction (e.g. mis-decoded ToUnicode CMaps). They are not valid in
# well-formed text and DuckDB refuses to encode them ("surrogates not allowed"),
# which would otherwise abort indexing of the whole document. Strip them.
_SURROGATE_RE = re.compile("[\ud800-\udfff]")


def _clean(s):
    if isinstance(s, str):
        return _SURROGATE_RE.sub("", s)
    if isinstance(s, list):
        return [_clean(x) for x in s]
    return s


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_source(path: Path) -> tuple[str, str, str]:
    resolved = path.resolve()
    for name, root in (
        ("Literature", config.LITERATURE_DIR),
        ("Transcripts", config.TRANSCRIPTS_DIR),
        ("Notebooks", config.NOTEBOOKS_DIR),
        ("DB Systems", config.DB_SYSTEMS_DIR),
        ("Internal", config.INTERNAL_DIR),
        ("Outbox", config.OUTBOX_DIR),
        ("Inbox", config.INBOX_DIR),
        ("Personal", config.PERSONAL_DIR),
    ):
        try:
            rel = resolved.relative_to(root.resolve())
        except ValueError:
            continue
        if name == "Literature":
            topic = "/".join(rel.parts[:-1]) if len(rel.parts) > 1 else "(root)"
        elif name == "Transcripts":
            # Group by channel sub-folder, e.g. "Transcripts/DuckDB".
            topic = f"Transcripts/{rel.parts[0]}" if len(rel.parts) > 1 else "Transcripts"
        elif name == "Notebooks":
            # A single flat topic — notebooks are indexed on their own, not as books.
            topic = f"Notebooks/{rel.parts[0]}" if len(rel.parts) > 1 else "Notebooks"
        elif name == "DB Systems":
            # Group by collection sub-folder, e.g. "DB Systems/dbdb".
            topic = f"DB Systems/{rel.parts[0]}" if len(rel.parts) > 1 else "DB Systems"
        elif name == "Internal":
            topic = "Internal/" + "/".join(rel.parts[:-1]) if len(rel.parts) > 1 else "Internal"
        elif name == "Personal":
            # e.g. Personal/drive/… or Personal/meet/… → Personal/<subdir>
            topic = "Personal/" + "/".join(rel.parts[:2]) if len(rel.parts) >= 2 else "Personal"
        else:
            topic = name
        return name, str(Path(name) / rel), topic
    return "Other", str(resolved), "Other"


def _is_split_monolith(path: Path) -> bool:
    """True if this PDF was split into a sibling '<stem> (papers)/' folder.

    Such monoliths are skipped so we index the per-paper PDFs, not the bundle.
    """
    if path.suffix.lower() != ".pdf":
        return False
    papers_dir = path.with_name(f"{path.stem} (papers)")
    return papers_dir.is_dir() and any(papers_dir.glob("*.pdf"))


def iter_files(roots):
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            if path.suffix.lower() not in config.IMPORT_SUFFIXES:
                continue
            if _is_split_monolith(path):
                continue
            yield path


def embed_with_cache(con, embedder, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    dim = embedder.dim
    model = embedder.model
    hashes = [_text_hash(t) for t in texts]
    unique = list(dict.fromkeys(hashes))

    cached: dict[str, list[float]] = {}
    placeholders = ",".join(["?"] * len(unique))
    rows = con.execute(
        f"SELECT text_hash, embedding FROM embedding_cache "
        f"WHERE model = ? AND text_hash IN ({placeholders})",
        [model, *unique],
    ).fetchall()
    for text_hash, emb in rows:
        cached[text_hash] = list(emb)

    hash_to_text: dict[str, str] = {}
    for h, t in zip(hashes, texts):
        hash_to_text.setdefault(h, t)
    missing = [h for h in unique if h not in cached]
    if missing:
        new_embs = embedder.embed([hash_to_text[h] for h in missing])
        for h, emb in zip(missing, new_embs):
            emb = list(emb)
            cached[h] = emb
            con.execute(
                f"INSERT OR REPLACE INTO embedding_cache VALUES (?, ?, ?::FLOAT[{dim}])",
                [model, h, emb],
            )
    return [cached[h] for h in hashes]


def index_file(con, embedder, path: Path) -> str:
    doc_id = file_hash(path)
    stat = path.stat()

    existing = con.execute(
        "SELECT mtime, size, path FROM documents WHERE doc_id = ?", [doc_id]
    ).fetchone()
    if existing and existing[1] == stat.st_size and existing[2] == str(path):
        # doc_id is a content hash, so identical hash + same path + same size means
        # the bytes (hence extraction/chunks/embeddings) are unchanged — nothing to
        # re-do. Only the filesystem mtime may have drifted (e.g. after a bulk copy
        # or LFS restore); refresh it so future runs fast-skip, and move on without
        # the expensive re-extraction/re-embedding.
        if abs(existing[0] - stat.st_mtime) >= 1.0:
            con.execute("UPDATE documents SET mtime = ? WHERE doc_id = ?",
                        [stat.st_mtime, doc_id])
        return "skip"

    # Clear any prior rows for this content or this path (moved/updated file).
    con.execute("DELETE FROM chunks WHERE doc_id = ?", [doc_id])
    con.execute(
        "DELETE FROM chunks WHERE doc_id IN (SELECT doc_id FROM documents WHERE path = ?)",
        [str(path)],
    )
    con.execute("DELETE FROM documents WHERE doc_id = ? OR path = ?", [doc_id, str(path)])

    ex = extractmod.extract_document(path)

    # A document whose own text layer is missing or thin gets the cached OCR text
    # instead, if the `ocr` stage has produced any. Extraction stays ignorant of
    # the database; the preference is applied here, where the doc_id is known.
    from . import ocr as ocrmod

    if path.suffix.lower() == ".pdf":
        ocrmod.prefer_ocr(con, doc_id, ex)

    chunk_rows: list[tuple[int, int, str]] = []
    total_chars = 0
    ordinal = 0
    for page_no, ptext in ex.pages:
        for piece in chunkmod.chunk_text(ptext, config.CHUNK_SIZE, config.CHUNK_OVERLAP):
            if config.MAX_CHARS_PER_DOC and total_chars >= config.MAX_CHARS_PER_DOC:
                break
            chunk_rows.append((ordinal, page_no, _clean(piece)))
            total_chars += len(piece)
            ordinal += 1

    embeddings = embed_with_cache(con, embedder, [c[2] for c in chunk_rows])

    source, rel_path, topic = classify_source(path)
    con.execute(
        """
        INSERT INTO documents
            (doc_id, path, rel_path, filetype, size, mtime, source, topic, title,
             authors, year, venue, abstract, n_pages, n_chunks,
             extraction_confidence, needs_review, internal, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [
            doc_id, str(path), rel_path, path.suffix.lower(), stat.st_size, stat.st_mtime,
            source, topic, _clean(ex.title), _clean(ex.authors), ex.year,
            _clean(ex.venue), _clean(ex.abstract),
            ex.n_pages, len(chunk_rows), ex.extraction_confidence, ex.needs_review,
            config.is_internal_rel_path(rel_path),
        ],
    )

    dim = embedder.dim
    for (ordinal, page, text), emb in zip(chunk_rows, embeddings):
        con.execute(
            f"INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?::FLOAT[{dim}])",
            [f"{doc_id}:{ordinal}", doc_id, ordinal, page, text, _text_hash(text), emb],
        )
    return "indexed" if chunk_rows else "empty"


def backfill_internal(con) -> int:
    """Re-derive the `internal` flag for every document from its rel_path.

    Cheap (no re-embedding) and idempotent, so it runs on every build and keeps
    the flag in sync when files are moved into/out of the Celonis-internal
    collection. Returns the number of documents currently flagged internal.
    """
    con.execute(
        """
        UPDATE documents SET internal = (
            rel_path = 'Internal' OR starts_with(rel_path, 'Internal/')
            OR rel_path = 'Personal' OR starts_with(rel_path, 'Personal/')
            OR rel_path = ?
            OR starts_with(rel_path, ?)
        )
        """,
        [
            f"Literature/{config.INTERNAL_COLLECTION}",
            f"Literature/{config.INTERNAL_COLLECTION}/",
        ],
    )
    return con.execute("SELECT count(*) FROM documents WHERE internal").fetchone()[0]


def reindex_ocr_documents(con, embedder) -> int:
    """Re-index every document that has usable OCR text, so it becomes searchable.

    `index_file` fast-skips unchanged files by content hash, which is exactly what
    we want everywhere except here: the file did not change, its *extraction* did.
    Deleting the document row forces the one path that consults the OCR cache.
    """
    rows = con.execute(
        """
        SELECT DISTINCT d.doc_id, d.path FROM documents d
        JOIN doc_ocr o ON o.doc_id = d.doc_id AND o.ocr_status = 'ok'
        """
    ).fetchall()
    done = 0
    for doc_id, path in rows:
        p = Path(path)
        if not p.exists():
            continue
        con.execute("DELETE FROM chunks WHERE doc_id = ?", [doc_id])
        con.execute("DELETE FROM documents WHERE doc_id = ?", [doc_id])
        try:
            index_file(con, embedder, p)
            done += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {p.name}: {exc}", file=sys.stderr)
    if done:
        dbmod.create_search_indexes(con)
    return done


def reindex_paths(con, embedder, paths) -> int:
    """Force re-ingest of specific files whose *extraction* changed.

    Same situation as ``reindex_ocr_documents`` and the same remedy: the bytes on
    disk are identical, so ``index_file`` would fast-skip on the content hash,
    but the text we now get out of them is different. Dropping the ``documents``
    row defeats that skip; ``index_file`` clears the stale chunks itself.
    """
    done = 0
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        con.execute("DELETE FROM documents WHERE path = ?", [str(path)])
        try:
            if index_file(con, embedder, path) == "indexed":
                done += 1
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop the batch
            print(f"[error] {path}: {exc}", file=sys.stderr)
    if done:
        dbmod.create_search_indexes(con)
    return done


def prune_missing(con) -> int:
    """Drop documents whose file is gone or has since been split into papers."""
    rows = con.execute("SELECT doc_id, path FROM documents").fetchall()
    removed = 0
    for doc_id, path in rows:
        p = Path(path)
        if not p.exists() or _is_split_monolith(p):
            con.execute("DELETE FROM chunks WHERE doc_id = ?", [doc_id])
            con.execute("DELETE FROM documents WHERE doc_id = ?", [doc_id])
            removed += 1
    return removed


def build_index(con, embedder, roots, limit: int | None = None, reset: bool = False) -> dict:
    if reset:
        dbmod.reset(con)
    dbmod.init_schema(con, embedder.dim)
    dbmod.check_or_set_dim(con, embedder)

    stats = {"indexed": 0, "skip": 0, "empty": 0}
    if not reset:
        pruned = prune_missing(con)
        if pruned:
            print(f"[prune] removed {pruned} stale/split documents")
        stats["pruned"] = pruned
    count = 0
    for path in iter_files(roots):
        if limit is not None and count >= limit:
            break
        count += 1
        try:
            result = index_file(con, embedder, path)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {path}: {exc}", file=sys.stderr)
            continue
        stats[result] = stats.get(result, 0) + 1
        if result != "skip":
            print(f"[{result:7s}] {path.name}")

    stats["internal"] = backfill_internal(con)
    dbmod.create_search_indexes(con)
    return stats
