"""Hybrid retrieval: dense vector (vss/HNSW) + BM25 (fts), fused with RRF."""

from __future__ import annotations

from dataclasses import dataclass

RRF_K = 60


@dataclass
class Result:
    chunk_id: str
    doc_id: str
    title: str
    rel_path: str
    topic: str
    page: int
    score: float
    snippet: str
    via: str = "hybrid"  # "hybrid" (vector+BM25) or "graph" (expansion)


def _vector_hits(con, query_emb, dim, pool):
    return con.execute(
        f"""
        SELECT chunk_id, doc_id
        FROM chunks
        ORDER BY array_cosine_distance(embedding, ?::FLOAT[{dim}])
        LIMIT ?
        """,
        [query_emb, pool],
    ).fetchall()


def _bm25_hits(con, query, pool):
    return con.execute(
        """
        SELECT chunk_id, doc_id FROM (
            SELECT chunk_id, doc_id,
                   fts_main_chunks.match_bm25(chunk_id, ?) AS score
            FROM chunks
        )
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT ?
        """,
        [query, pool],
    ).fetchall()


def _row_to_result(row, score, via):
    _, doc_id, title, rel_path, topic, page, text = row
    snippet = " ".join((text or "").split())[:300]
    return Result(row[0], doc_id, title or "(untitled)", rel_path, topic or "",
                  page or 0, score, snippet, via)


def _has_graph(con) -> bool:
    n = con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_name IN ('doc_similar','doc_authors','doc_keywords')"
    ).fetchone()[0]
    return n == 3


def _graph_expand(con, embedder, query_emb, seed_scores: dict, exclude: set, limit: int):
    """Doc-level graph expansion over SIMILAR_TO / shared-author / shared-keyword
    edges. Returns representative chunk rows for neighbour documents."""
    if not seed_scores or not _has_graph(con):
        return []
    seed_rows = list(seed_scores.items())
    vals = ",".join(["(?, ?)"] * len(seed_rows))
    params = [x for pair in seed_rows for x in pair]
    neighbours = con.execute(
        f"""
        WITH seed(doc_id, w) AS (VALUES {vals}),
        sim AS (
            SELECT s.other_id AS doc, sum(s.score * seed.w) AS sc
            FROM seed JOIN doc_similar s ON s.doc_id = seed.doc_id GROUP BY s.other_id),
        auth AS (
            SELECT da2.doc_id AS doc, 0.6 * sum(seed.w) AS sc
            FROM seed JOIN doc_authors da1 ON da1.doc_id = seed.doc_id
            JOIN doc_authors da2 ON da2.author_id = da1.author_id GROUP BY da2.doc_id),
        kw AS (
            SELECT dk2.doc_id AS doc, 0.4 * sum(seed.w) AS sc
            FROM seed JOIN doc_keywords dk1 ON dk1.doc_id = seed.doc_id
            JOIN doc_keywords dk2 ON dk2.keyword_id = dk1.keyword_id GROUP BY dk2.doc_id),
        merged AS (SELECT doc, sc FROM sim UNION ALL SELECT doc, sc FROM auth
                   UNION ALL SELECT doc, sc FROM kw)
        SELECT doc, sum(sc) AS score FROM merged
        WHERE doc NOT IN (SELECT doc_id FROM seed)
        GROUP BY doc ORDER BY score DESC LIMIT ?
        """,
        [*params, limit * 3],
    ).fetchall()

    dim = embedder.dim
    out = []
    for doc_id, score in neighbours:
        if doc_id in exclude:
            continue
        row = con.execute(
            f"""
            SELECT c.chunk_id, c.doc_id, d.title, d.rel_path, d.topic, c.page, c.text
            FROM chunks c JOIN documents d USING (doc_id)
            WHERE c.doc_id = ?
            ORDER BY array_cosine_distance(c.embedding, ?::FLOAT[{dim}]) LIMIT 1
            """,
            [doc_id, query_emb],
        ).fetchone()
        if row:
            out.append(_row_to_result(row, float(score), "graph"))
        if len(out) >= limit:
            break
    return out


def search(con, embedder, query: str, k: int = 10, pool: int | None = None,
           expand: bool = False) -> list[Result]:
    pool = pool or max(k * 5, 50)
    embed_query = getattr(embedder, "embed_query", None)
    query_emb = embed_query(query) if callable(embed_query) else embedder.embed([query])[0]

    fused: dict[str, dict] = {}
    for rank, (chunk_id, doc_id) in enumerate(_vector_hits(con, query_emb, embedder.dim, pool)):
        fused.setdefault(chunk_id, {"doc_id": doc_id, "score": 0.0})["score"] += 1.0 / (RRF_K + rank + 1)
    try:
        bm = _bm25_hits(con, query, pool)
    except Exception:
        bm = []  # fts index may not exist yet
    for rank, (chunk_id, doc_id) in enumerate(bm):
        fused.setdefault(chunk_id, {"doc_id": doc_id, "score": 0.0})["score"] += 1.0 / (RRF_K + rank + 1)

    if not fused:
        return []

    top = sorted(fused.items(), key=lambda kv: -kv[1]["score"])[:k]
    ids = [cid for cid, _ in top]
    placeholders = ",".join(["?"] * len(ids))
    rows = con.execute(
        f"""
        SELECT c.chunk_id, c.doc_id, d.title, d.rel_path, d.topic, c.page, c.text
        FROM chunks c JOIN documents d USING (doc_id)
        WHERE c.chunk_id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    by_id = {r[0]: r for r in rows}

    results = []
    for chunk_id, info in top:
        row = by_id.get(chunk_id)
        if row is not None:
            results.append(_row_to_result(row, info["score"], "hybrid"))

    if expand:
        seed_scores: dict[str, float] = {}
        for r in results:
            seed_scores[r.doc_id] = seed_scores.get(r.doc_id, 0.0) + r.score
        seeds = dict(sorted(seed_scores.items(), key=lambda kv: -kv[1])[:5])
        seen_docs = {r.doc_id for r in results}
        results.extend(
            _graph_expand(con, embedder, query_emb, seeds, seen_docs, limit=max(3, k // 2))
        )
    return results
