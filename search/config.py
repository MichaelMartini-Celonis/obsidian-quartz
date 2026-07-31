"""Configuration for the search engine, driven by environment variables.

Embeddings default to a **local** model via ``fastembed`` (ONNX, no network at
query time, data never leaves the machine). The Celonis AI Gateway does not
expose an embedding model, so ``gateway`` is retained only for a future endpoint.
A network-free ``hash`` embedder (set ``SEARCH_EMBEDDER=hash``) exists purely to
exercise the pipeline; it is NOT semantically meaningful.
"""

from __future__ import annotations

import os
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIR = Path(__file__).resolve().parent

LITERATURE_DIR = DOCS_ROOT / "Literature"
INBOX_DIR = DOCS_ROOT / "Inbox"
OUTBOX_DIR = DOCS_ROOT / "Outbox"
# YouTube (and other) video transcripts, imported via scripts/import-youtube.py.
# A first-class search root so transcripts are indexed alongside the papers.
TRANSCRIPTS_DIR = DOCS_ROOT / "Transcripts"
# Jupyter notebooks, collected out of the library into their own top-level
# folder (like Transcripts). A first-class search root so notebooks are indexed
# under their own "Notebooks" topic rather than as library "Books".
NOTEBOOKS_DIR = DOCS_ROOT / "notebooks"
# Database-system reference pages (e.g. the CMU dbdb.io "Database of Databases"
# mirror under db_systems/dbdb/), tagged with the dbdb-aligned taxonomy. A
# first-class search root so systems are queryable alongside the papers.
DB_SYSTEMS_DIR = DOCS_ROOT / "db_systems"

DB_PATH = Path(os.environ.get("SEARCH_DB", str(SEARCH_DIR / "index.duckdb")))

# Documents under this Literature sub-collection are flagged as Celonis-internal
# (non-public working material) in the index. Internal-ness is a property of
# where a file lives, so it can be re-flagged simply by moving the file and
# re-indexing. The importer routes detected internal docs here.
INTERNAL_COLLECTION = "Celonis Internal"
INTERNAL_DIR = LITERATURE_DIR / INTERNAL_COLLECTION


def is_internal_rel_path(rel_path: str) -> bool:
    """True if a document rel_path belongs to the Celonis-internal collection."""
    prefix = f"Literature/{INTERNAL_COLLECTION}/"
    return rel_path == f"Literature/{INTERNAL_COLLECTION}" or rel_path.startswith(prefix)

# File types we ingest. Others are ignored.
IMPORT_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".ipynb", ".bpmn", ".epub", ".pptx"}

# Chunking (character based, paragraph aware).
CHUNK_SIZE = int(os.environ.get("SEARCH_CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.environ.get("SEARCH_CHUNK_OVERLAP", "150"))
# Optional cap on characters embedded per document (0 = no cap). Useful for huge books.
MAX_CHARS_PER_DOC = int(os.environ.get("SEARCH_MAX_CHARS", "0"))

# --- Embedder selection -----------------------------------------------------
# "local" (default; fastembed ONNX model), "gateway", or "hash" (dev fallback).
EMBEDDER = os.environ.get("SEARCH_EMBEDDER", "").strip().lower()

# Local (fastembed) — default. bge-small-en-v1.5 is 384-dim, strong for retrieval.
LOCAL_MODEL = os.environ.get("SEARCH_LOCAL_MODEL", "BAAI/bge-small-en-v1.5")

# Gateway — retained for a future embedding endpoint (the AI Gateway currently
# serves chat models only and rejects embedding model names).
GATEWAY_BASE_URL = os.environ.get("CELONIS_AI_GATEWAY_BASE_URL", "").rstrip("/")
GATEWAY_API_KEY = os.environ.get("CELONIS_AI_GATEWAY_API_KEY", "")
GATEWAY_EMBED_PATH = os.environ.get("CELONIS_AI_GATEWAY_EMBED_PATH", "/embeddings")
EMBEDDING_MODEL = os.environ.get("SEARCH_EMBEDDING_MODEL", "text-embedding-3-small")
# 0 -> let the embedder self-report its dimension (gateway probes once).
EMBEDDING_DIM = int(os.environ.get("SEARCH_EMBEDDING_DIM", "0"))

HASH_DIM = int(os.environ.get("SEARCH_HASH_DIM", "256"))

# --- Chat / LLM enrichment (Celonis AI Gateway, chat models only) -----------
# Used to clean bibliographic metadata and extract keywords/concepts. Optional:
# enrichment degrades gracefully when the gateway is unreachable.
CHAT_BASE_URL = os.environ.get("CELONIS_AI_GATEWAY_BASE_URL", "https://ai.celonis.dev/v1").rstrip("/")
CHAT_PATH = os.environ.get("CELONIS_AI_GATEWAY_CHAT_PATH", "/chat/completions")
# A small, fast model is plenty for structured extraction.
CHAT_MODEL = os.environ.get("SEARCH_CHAT_MODEL", "claude-haiku-4-5-20251001")
