"""Phase 1 knowledge graph: authors, topics, keywords, and similarity edges.

Builds normalized entity tables from the ``documents`` rows (plus keywords from
LLM enrichment), a document-level embedding for a ``SIMILAR_TO`` kNN edge set,
and a ``duckpgq`` property graph over all of it. The property graph powers the
``graph`` CLI queries (author papers, co-authors, keyword neighbours, paths) and
graph-expanded retrieval.

Node tables:  documents, authors, keywords, topics, companies
Edge tables:  doc_authors (doc->author), doc_keywords (doc->keyword),
              doc_topics (doc->topic), doc_similar (doc->doc),
              doc_companies (doc->company)

The ``companies`` layer indexes non-research tooling: the vendor/tool/standards-body
behind each imported blog post, piece of tool documentation, or specification. A
document's company is derived from its library path — files filed under
``Literature/Blogs/<Company>/``, ``Literature/Tool & Competitor Documentation/<Company>/``,
``Literature/Source Systems Knowledge/<Company>/`` or ``Literature/Specifications/<Company>/``
— so a vendor's blogs, dialect docs, source-system references and specifications
collapse onto a single ``Company`` node.
"""

from __future__ import annotations

import re
import unicodedata

PARTICLES = {"van", "der", "de", "den", "von", "la", "le", "du", "di", "dos"}

# Library top-level folders whose immediate subfolder names a company/tool
# (non-research tooling). The regex captures that subfolder from ``rel_path``.
COMPANY_PATH_RE = (
    r"^(?:\./)?(?:Literature/)?"
    r"(?:Blogs|Tool & Competitor Documentation|Source Systems Knowledge|Specifications)/([^/]+)/"
)


def norm_name(name) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s.-]", "", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def norm_term(term) -> str:
    if not term:
        return ""
    s = unicodedata.normalize("NFKD", str(term)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def register_udfs(con) -> None:
    """Register norm_name / norm_term as scalar SQL functions (idempotent)."""
    for name, fn in (("norm_name", norm_name), ("norm_term", norm_term)):
        try:
            con.create_function(name, fn, ["VARCHAR"], "VARCHAR")
        except Exception:
            pass  # already registered on this connection


def _dim(con) -> int:
    row = con.execute("SELECT value FROM meta WHERE key='embedding_dim'").fetchone()
    if not row:
        raise SystemExit("no embedding_dim in meta — build the index first")
    return int(row[0])


def init_graph_schema(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS authors (
            author_id BIGINT PRIMARY KEY, name TEXT, name_norm TEXT UNIQUE)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS keywords (
            keyword_id BIGINT PRIMARY KEY, term TEXT, term_norm TEXT UNIQUE)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            topic_id BIGINT PRIMARY KEY, name TEXT UNIQUE)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id BIGINT PRIMARY KEY, name TEXT, name_norm TEXT UNIQUE)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS doc_authors (
            doc_id TEXT, author_id BIGINT, position INTEGER)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS doc_keywords (
            doc_id TEXT, keyword_id BIGINT, score DOUBLE)
    """)
    con.execute("CREATE TABLE IF NOT EXISTS doc_topics (doc_id TEXT, topic_id BIGINT)")
    con.execute("CREATE TABLE IF NOT EXISTS doc_similar (doc_id TEXT, other_id TEXT, score DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS doc_companies (doc_id TEXT, company_id BIGINT)")


def _reset_graph_tables(con) -> None:
    for t in ("doc_authors", "doc_keywords", "doc_topics", "doc_companies",
              "authors", "keywords", "topics", "companies"):
        con.execute(f"DELETE FROM {t}")


def build_entities(con) -> dict:
    """(Re)populate author / topic / keyword nodes and their doc edges."""
    init_graph_schema(con)
    _reset_graph_tables(con)

    # Authors: explode documents.authors[] preserving order; normalize + dedupe.
    con.execute("""
        INSERT INTO authors (author_id, name, name_norm)
        SELECT row_number() OVER (ORDER BY name_norm) AS author_id, name, name_norm
        FROM (
            SELECT norm_name(a) AS name_norm, arg_min(a, position) AS name
            FROM (
                SELECT unnest(authors) AS a,
                       generate_subscripts(authors, 1) AS position
                FROM documents WHERE authors IS NOT NULL
            ) WHERE norm_name(a) <> ''
            GROUP BY norm_name(a)
        )
    """)
    con.execute("""
        INSERT INTO doc_authors (doc_id, author_id, position)
        SELECT d.doc_id, au.author_id, x.position
        FROM (
            SELECT doc_id, unnest(authors) AS a,
                   generate_subscripts(authors, 1) AS position
            FROM documents WHERE authors IS NOT NULL
        ) x
        JOIN documents d USING (doc_id)
        JOIN authors au ON au.name_norm = norm_name(x.a)
    """)

    # Topics: the Literature folder path (one per doc for now).
    con.execute("""
        INSERT INTO topics (topic_id, name)
        SELECT row_number() OVER (ORDER BY topic), topic
        FROM (SELECT DISTINCT topic FROM documents WHERE topic IS NOT NULL AND topic <> '')
    """)
    con.execute("""
        INSERT INTO doc_topics (doc_id, topic_id)
        SELECT d.doc_id, t.topic_id
        FROM documents d JOIN topics t ON t.name = d.topic
        WHERE d.topic IS NOT NULL AND d.topic <> ''
    """)

    # Companies: derived from the library path for non-research tooling
    # (Blogs/<Company>/… and Tool & Competitor Documentation/<Company>/…).
    con.execute(
        """
        INSERT INTO companies (company_id, name, name_norm)
        SELECT row_number() OVER (ORDER BY name_norm), name, name_norm FROM (
            SELECT norm_name(c) AS name_norm, arg_min(c, c) AS name
            FROM (
                SELECT regexp_extract(rel_path, ?, 1) AS c
                FROM documents WHERE rel_path IS NOT NULL
            ) WHERE c <> '' AND norm_name(c) <> ''
            GROUP BY norm_name(c)
        )
        """,
        [COMPANY_PATH_RE],
    )
    con.execute(
        """
        INSERT INTO doc_companies (doc_id, company_id)
        SELECT d.doc_id, co.company_id
        FROM (
            SELECT doc_id, regexp_extract(rel_path, ?, 1) AS c
            FROM documents WHERE rel_path IS NOT NULL
        ) d
        JOIN companies co ON co.name_norm = norm_name(d.c)
        WHERE d.c <> ''
        """,
        [COMPANY_PATH_RE],
    )

    # Keywords come from enrichment (doc_enrichment.keywords[]), when present.
    has_enrich = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='doc_enrichment'"
    ).fetchone()[0]
    if has_enrich:
        con.execute("""
            INSERT INTO keywords (keyword_id, term, term_norm)
            SELECT row_number() OVER (ORDER BY term_norm), term, term_norm FROM (
                SELECT norm_term(k) AS term_norm, arg_min(k, k) AS term
                FROM (SELECT unnest(keywords) AS k FROM doc_enrichment
                      WHERE keywords IS NOT NULL)
                WHERE norm_term(k) <> '' AND length(norm_term(k)) >= 3
                GROUP BY norm_term(k)
            )
        """)
        con.execute("""
            INSERT INTO doc_keywords (doc_id, keyword_id, score)
            SELECT e.doc_id, kw.keyword_id, 1.0
            FROM (SELECT doc_id, unnest(keywords) AS k FROM doc_enrichment
                  WHERE keywords IS NOT NULL) e
            JOIN keywords kw ON kw.term_norm = norm_term(e.k)
        """)

    return {
        "authors": con.execute("SELECT count(*) FROM authors").fetchone()[0],
        "topics": con.execute("SELECT count(*) FROM topics").fetchone()[0],
        "keywords": con.execute("SELECT count(*) FROM keywords").fetchone()[0],
        "companies": con.execute("SELECT count(*) FROM companies").fetchone()[0],
        "doc_authors": con.execute("SELECT count(*) FROM doc_authors").fetchone()[0],
        "doc_companies": con.execute("SELECT count(*) FROM doc_companies").fetchone()[0],
    }


def build_similar(con, k: int = 8, min_score: float = 0.5) -> int:
    """Materialize a SIMILAR_TO kNN edge set from mean per-document embeddings.

    Doc vector = L2-normalized mean of its chunk embeddings; cosine kNN is then a
    single normalized matrix product (fine for a corpus of a few thousand docs).
    """
    import numpy as np

    con.execute("DELETE FROM doc_similar")
    doc_ids = [r[0] for r in con.execute(
        "SELECT DISTINCT doc_id FROM chunks ORDER BY doc_id").fetchall()]
    if len(doc_ids) < 2:
        return 0

    dim = _dim(con)
    mat = np.zeros((len(doc_ids), dim), dtype=np.float32)
    for i, doc_id in enumerate(doc_ids):
        embs = con.execute(
            "SELECT embedding FROM chunks WHERE doc_id = ?", [doc_id]).fetchall()
        if embs:
            mat[i] = np.mean(np.asarray([list(e[0]) for e in embs], dtype=np.float32), axis=0)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / np.clip(norms, 1e-8, None)

    inserted = 0
    for i, doc_id in enumerate(doc_ids):
        sims = mat @ mat[i]
        sims[i] = -1.0  # exclude self
        top = np.argpartition(-sims, min(k, len(sims) - 1))[:k]
        top = top[np.argsort(-sims[top])]
        for j in top:
            s = float(sims[j])
            if s < min_score:
                continue
            con.execute("INSERT INTO doc_similar VALUES (?, ?, ?)",
                        [doc_id, doc_ids[int(j)], s])
            inserted += 1
    return inserted


def ensure_property_graph(con) -> None:
    """(Re)create the duckpgq property graph over the current tables.

    Cheap catalog-only operation; safe to call before each graph query.
    """
    con.execute("LOAD duckpgq")
    con.execute("DROP PROPERTY GRAPH IF EXISTS kg")
    con.execute("""
        CREATE PROPERTY GRAPH kg
        VERTEX TABLES (
            documents LABEL Document,
            authors   LABEL Author,
            keywords  LABEL Keyword,
            topics    LABEL Topic,
            companies LABEL Company
        )
        EDGE TABLES (
            doc_authors  SOURCE KEY (doc_id)   REFERENCES documents (doc_id)
                         DESTINATION KEY (author_id) REFERENCES authors (author_id)
                         LABEL has_author,
            doc_keywords SOURCE KEY (doc_id)   REFERENCES documents (doc_id)
                         DESTINATION KEY (keyword_id) REFERENCES keywords (keyword_id)
                         LABEL has_keyword,
            doc_topics   SOURCE KEY (doc_id)   REFERENCES documents (doc_id)
                         DESTINATION KEY (topic_id) REFERENCES topics (topic_id)
                         LABEL has_topic,
            doc_companies SOURCE KEY (doc_id)  REFERENCES documents (doc_id)
                         DESTINATION KEY (company_id) REFERENCES companies (company_id)
                         LABEL by_company,
            doc_similar  SOURCE KEY (doc_id)   REFERENCES documents (doc_id)
                         DESTINATION KEY (other_id) REFERENCES documents (doc_id)
                         LABEL similar_to
        )
    """)


def build_graph(con, similar_k: int = 8) -> dict:
    stats = build_entities(con)
    stats["similar_edges"] = build_similar(con, k=similar_k)
    ensure_property_graph(con)
    return stats


# --- graph queries ----------------------------------------------------------

def _lit(s: str) -> str:
    """Escape a string as a SQL literal (params don't bind inside GRAPH_TABLE)."""
    return "'" + str(s).replace("'", "''") + "'"


def papers_by_author(con, name: str, limit: int = 25):
    ensure_property_graph(con)
    nn = _lit(norm_name(name))
    return con.execute(
        f"""
        FROM GRAPH_TABLE (kg
            MATCH (d:Document)-[e:has_author]->(a:Author)
            WHERE a.name_norm = {nn}
            COLUMNS (d.title AS title, d.rel_path AS rel_path, d.year AS year))
        SELECT DISTINCT title, rel_path, year ORDER BY year DESC NULLS LAST
        LIMIT {int(limit)}
        """
    ).fetchall()


def coauthors(con, name: str, limit: int = 25):
    ensure_property_graph(con)
    nn = _lit(norm_name(name))
    return con.execute(
        f"""
        FROM GRAPH_TABLE (kg
            MATCH (a:Author)<-[e1:has_author]-(d:Document)-[e2:has_author]->(b:Author)
            WHERE a.name_norm = {nn} AND b.name_norm <> {nn}
            COLUMNS (b.name AS coauthor))
        SELECT coauthor, count(*) AS shared_papers
        GROUP BY coauthor ORDER BY shared_papers DESC LIMIT {int(limit)}
        """
    ).fetchall()


def companies(con, limit: int = 100):
    """List indexed companies/tools with their document counts."""
    return con.execute(
        """
        SELECT co.name, count(*) AS docs
        FROM companies co JOIN doc_companies dc USING (company_id)
        GROUP BY co.name ORDER BY docs DESC, co.name LIMIT ?
        """,
        [int(limit)],
    ).fetchall()


def docs_by_company(con, name: str, limit: int = 40):
    ensure_property_graph(con)
    nn = _lit(norm_name(name))
    return con.execute(
        f"""
        FROM GRAPH_TABLE (kg
            MATCH (d:Document)-[e:by_company]->(c:Company)
            WHERE c.name_norm = {nn}
            COLUMNS (d.title AS title, d.rel_path AS rel_path, d.topic AS topic))
        SELECT DISTINCT title, topic, rel_path ORDER BY topic, title
        LIMIT {int(limit)}
        """
    ).fetchall()


def related_by_keyword(con, doc_id: str, limit: int = 15):
    ensure_property_graph(con)
    did = _lit(doc_id)
    return con.execute(
        f"""
        FROM GRAPH_TABLE (kg
            MATCH (d:Document)-[e1:has_keyword]->(k:Keyword)<-[e2:has_keyword]-(o:Document)
            WHERE d.doc_id = {did} AND o.doc_id <> {did}
            COLUMNS (o.title AS title, o.rel_path AS rel_path))
        SELECT title, rel_path, count(*) AS shared_keywords
        GROUP BY title, rel_path ORDER BY shared_keywords DESC LIMIT {int(limit)}
        """
    ).fetchall()
