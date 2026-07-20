"""DuckDB connection, extension loading, and schema management."""

from __future__ import annotations

import duckdb

from . import config


def connect(db_path=None, read_only: bool = False, graph: bool = False):
    con = duckdb.connect(str(db_path or config.DB_PATH), read_only=read_only)
    exts = ["vss", "fts"]
    if graph:
        exts.append("duckpgq")
    for ext in exts:
        try:
            con.execute(f"INSTALL {ext}" + (" FROM community" if ext == "duckpgq" else ""))
        except Exception:
            pass  # may already be installed / offline
        try:
            con.execute(f"LOAD {ext}")
        except Exception:
            if ext == "duckpgq":
                raise
    # HNSW persistence in a disk-backed DB is still experimental in DuckDB.
    con.execute("SET hnsw_enable_experimental_persistence = true")
    # Normalization UDFs used by the graph builder / queries.
    from . import graph as graphmod
    graphmod.register_udfs(con)
    return con


def init_schema(con, dim: int) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            path TEXT,
            rel_path TEXT,
            filetype TEXT,
            size BIGINT,
            mtime DOUBLE,
            source TEXT,
            topic TEXT,
            title TEXT,
            authors TEXT[],
            year INTEGER,
            venue TEXT,
            abstract TEXT,
            n_pages INTEGER,
            n_chunks INTEGER,
            extraction_confidence DOUBLE,
            needs_review BOOLEAN,
            indexed_at TIMESTAMP
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT,
            ordinal INTEGER,
            page INTEGER,
            text TEXT,
            text_hash TEXT,
            embedding FLOAT[{dim}]
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS embedding_cache (
            model TEXT,
            text_hash TEXT,
            embedding FLOAT[{dim}],
            PRIMARY KEY (model, text_hash)
        )
        """
    )


def reset(con) -> None:
    con.execute("DROP INDEX IF EXISTS hnsw_chunks")
    for table in ("chunks", "documents", "embedding_cache", "meta"):
        con.execute(f"DROP TABLE IF EXISTS {table}")


def check_or_set_dim(con, embedder) -> None:
    row = con.execute("SELECT value FROM meta WHERE key = 'embedding_dim'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta VALUES ('embedding_dim', ?)", [str(embedder.dim)])
        con.execute(
            "INSERT OR REPLACE INTO meta VALUES ('embedder_model', ?)", [embedder.model]
        )
        return
    if int(row[0]) != embedder.dim:
        raise SystemExit(
            f"DB embedding dim {row[0]} != current embedder dim {embedder.dim} "
            f"({embedder.model}). Re-run with --reset to rebuild the index."
        )


def create_search_indexes(con) -> None:
    """(Re)build the HNSW vector index and the BM25 full-text index.

    Call after bulk ingest so both indexes see all rows.
    """
    n = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
    if n == 0:
        return
    con.execute("DROP INDEX IF EXISTS hnsw_chunks")
    con.execute(
        "CREATE INDEX hnsw_chunks ON chunks USING HNSW (embedding) WITH (metric = 'cosine')"
    )
    con.execute("PRAGMA create_fts_index('chunks', 'chunk_id', 'text', overwrite = 1)")
