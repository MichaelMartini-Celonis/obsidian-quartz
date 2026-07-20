"""Graph-RAG search engine over the ~/docs knowledge repository.

Phase 0: embedded DuckDB (vss + fts) with incremental ingest and hybrid
(vector + BM25) retrieval. Graph queries (duckpgq) arrive in Phase 1.
"""
