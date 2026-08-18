"""LLM enrichment of document metadata via the Celonis AI Gateway.

The heuristic extractor leaves many documents with poor titles ("Unknown -
main.dvi.pdf"), author lists mashed into one string, or missing year/venue. This
pass sends the opening text of each document to a small chat model and stores
clean ``title / authors / year / venue / keywords``. Results are cached in
``doc_enrichment`` (keyed by content hash) so re-runs are cheap and idempotent.

Enrichment is optional: if the gateway is unreachable the index/graph still work
with the heuristic metadata.

Usage (from ~/docs):
    scripts/.venv/bin/python -m search.cli enrich            # all un-enriched docs
    scripts/.venv/bin/python -m search.cli enrich --only-review --limit 50
"""

from __future__ import annotations

import json

from . import db as dbmod
from .llm import ChatClient, GatewayError

SYSTEM = (
    "You extract bibliographic metadata from the opening text of a document "
    "(usually an academic paper, sometimes a book, thesis, or non-academic file). "
    "Return a STRICT JSON object with keys: "
    "title (string), authors (array of full person names in reading order; [] if "
    "unknown or not a paper), year (integer or null), venue (string or null: the "
    "journal/conference/publisher), keywords (array of 3-8 lowercase topical "
    "keyword phrases describing the subject). "
    "List at most 15 authors. Emit the JSON on a single line without indentation. "
    "Never invent authors. If the text is not a real document (ticket, cover page, "
    "boilerplate), set authors to [] and give a concise descriptive title. "
    "Reply with the JSON object only, no prose."
)

MAX_INPUT_CHARS = 5000


def ensure_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS doc_enrichment (
            doc_id TEXT PRIMARY KEY,
            title TEXT,
            authors TEXT[],
            year INTEGER,
            venue TEXT,
            keywords TEXT[],
            method TEXT,
            enriched_at TIMESTAMP
        )
    """)


def promote_cached(con) -> int:
    """Copy cached enrichment onto document rows (no LLM calls).

    Needed after a re-index rebuilds document rows from heuristic extraction:
    the clean metadata still lives in ``doc_enrichment`` (keyed by content hash),
    so we re-apply it to the freshly-inserted rows.
    """
    ensure_schema(con)
    n = con.execute("""
        UPDATE documents d SET
            title = COALESCE(e.title, d.title),
            authors = CASE WHEN len(e.authors) > 0 THEN e.authors ELSE d.authors END,
            year = COALESCE(e.year, d.year),
            venue = COALESCE(e.venue, d.venue),
            needs_review = FALSE
        FROM doc_enrichment e
        WHERE d.doc_id = e.doc_id
    """).fetchone()
    return con.execute(
        "SELECT count(*) FROM documents d JOIN doc_enrichment e USING (doc_id)"
    ).fetchone()[0]


def _opening_text(con, doc_id: str) -> str:
    rows = con.execute(
        "SELECT text FROM chunks WHERE doc_id = ? ORDER BY ordinal LIMIT 5", [doc_id]
    ).fetchall()
    text = "\n\n".join(r[0] for r in rows if r[0])
    return text[:MAX_INPUT_CHARS]


def _targets(con, only_review: bool, limit, redo: bool):
    where = []
    if not redo:
        where.append("d.doc_id NOT IN (SELECT doc_id FROM doc_enrichment)")
    if only_review:
        where.append("d.needs_review")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = f"SELECT d.doc_id FROM documents d{clause} ORDER BY d.doc_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in con.execute(sql).fetchall()]


def _clean_authors(authors) -> list[str]:
    if not isinstance(authors, list):
        return []
    out = []
    for a in authors:
        a = str(a).strip()
        if a and len(a) <= 80 and len(a.split()) <= 6:
            out.append(a)
    return out[:15]


def enrich(con, only_review: bool = False, limit=None, redo: bool = False) -> dict:
    ensure_schema(con)
    client = ChatClient()
    # Fail fast if the gateway is unreachable.
    try:
        _ = client.token
    except GatewayError as exc:
        raise SystemExit(f"gateway unavailable, cannot enrich: {exc}")

    promoted = promote_cached(con)  # re-apply cached metadata to (rebuilt) rows
    if promoted:
        print(f"  promoted {promoted} cached enrichments onto document rows")

    doc_ids = _targets(con, only_review, limit, redo)
    stats = {"enriched": 0, "failed": 0, "total": len(doc_ids)}
    for n, doc_id in enumerate(doc_ids, 1):
        text = _opening_text(con, doc_id)
        if not text.strip():
            stats["failed"] += 1
            continue
        try:
            meta = client.json(SYSTEM, f"Opening text:\n\n{text}", max_tokens=1024)
        except Exception as exc:  # noqa: BLE001
            print(f"[fail]  {doc_id[:12]}  {exc}")
            stats["failed"] += 1
            continue

        title = (meta.get("title") or "").strip() or None
        authors = _clean_authors(meta.get("authors"))
        year = meta.get("year") if isinstance(meta.get("year"), int) else None
        venue = (meta.get("venue") or None) if meta.get("venue") else None
        keywords = [str(k).strip().lower() for k in (meta.get("keywords") or [])
                    if str(k).strip()][:8]

        con.execute(
            """INSERT OR REPLACE INTO doc_enrichment
               VALUES (?, ?, ?, ?, ?, ?, 'gateway', CURRENT_TIMESTAMP)""",
            [doc_id, title, authors, year, venue, keywords],
        )
        # Promote clean metadata onto the document row (keep heuristic if empty).
        con.execute(
            """UPDATE documents SET
                 title = COALESCE(?, title),
                 authors = CASE WHEN ? THEN ? ELSE authors END,
                 year = COALESCE(?, year),
                 venue = COALESCE(?, venue),
                 needs_review = FALSE
               WHERE doc_id = ?""",
            [title, bool(authors), authors, year, venue, doc_id],
        )
        stats["enriched"] += 1
        if n % 25 == 0 or n == len(doc_ids):
            print(f"  enriched {n}/{len(doc_ids)} ...")
    return stats
