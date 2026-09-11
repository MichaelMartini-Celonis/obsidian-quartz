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
# Personal Drive exports. Meet notes stay in a separate DuckDB; My Drive
# working files (`Personal/drive/`) live in the main index with `internal=TRUE`.
PERSONAL_DIR = DOCS_ROOT / "Personal"
MEET_NOTES_DIR = PERSONAL_DIR / "meet"
PERSONAL_DRIVE_DIR = PERSONAL_DIR / "drive"

# Celonis-internal working material (top-level, beside Personal/). Indexed in
# the main DuckDB and flagged `internal=TRUE`.
INTERNAL_DIR = DOCS_ROOT / "Internal"
# Historical Literature subfolder name — still recognised by path-flag logic.
INTERNAL_COLLECTION = "Celonis Internal"

DB_PATH = Path(os.environ.get("SEARCH_DB", str(SEARCH_DIR / "index.duckdb")))
MEET_DB_PATH = Path(os.environ.get("SEARCH_MEET_DB", str(SEARCH_DIR / "meet.duckdb")))


def is_internal_rel_path(rel_path: str) -> bool:
    """True if a document is non-public (Internal/ or Personal/, or the old
    Literature/Celonis Internal/ prefix). Public literature is False."""
    if not rel_path:
        return False
    if rel_path == "Internal" or rel_path.startswith("Internal/"):
        return True
    if rel_path == "Personal" or rel_path.startswith("Personal/"):
        return True
    prefix = f"Literature/{INTERNAL_COLLECTION}"
    return rel_path == prefix or rel_path.startswith(prefix + "/")


def resolve_db_path(alias: str | None) -> Path:
    """Map ``--db meet`` / ``--db main`` / a filesystem path to a DuckDB file."""
    if not alias or alias in ("main", "default", "papers"):
        return DB_PATH
    if alias in ("meet", "meetings"):
        return MEET_DB_PATH
    return Path(alias).expanduser()

# File types we ingest. Others are ignored.
IMPORT_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".ipynb", ".bpmn", ".epub",
                   ".pptx", ".ppsx", ".xlsx"}

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

# --- OCR / document parsing -------------------------------------------------
# Local by default: a small document-parsing VLM runs on Apple silicon through
# MLX, so page images never leave the machine (unlike the `gateway-vision`
# backend). The model stack lives in its own venv and is driven as a worker
# subprocess, keeping this venv free of mlx/torch. See DESIGN-ocr-metadata.md §2.
OCR_BACKEND = os.environ.get("SEARCH_OCR_BACKEND", "mlx-paddleocr-vl").strip().lower()
# Overrides the backend's default weights (e.g. an 8-bit conversion, or a
# locally converted PaddleOCR-VL-1.6 build).
OCR_MODEL = os.environ.get("SEARCH_OCR_MODEL", "").strip()
OCR_PYTHON = Path(os.environ.get(
    "SEARCH_OCR_PYTHON", str(DOCS_ROOT / "scripts" / ".venv-ocr" / "bin" / "python")))
OCR_DPI = int(os.environ.get("SEARCH_OCR_DPI", "200"))
# Longest rendered edge in pixels. 2200 ≈ a letter page at 200 dpi.
OCR_MAX_EDGE = int(os.environ.get("SEARCH_OCR_MAX_EDGE", "2200"))
# A dense journal page measures ~5k characters ≈ 1.5k tokens, so 4096 is ample.
# It is also a cost ceiling: a page the model loops on is abandoned sooner, and
# long generations are what trip the macOS GPU watchdog.
OCR_MAX_TOKENS = int(os.environ.get("SEARCH_OCR_MAX_TOKENS", "4096"))
# A page that takes longer than this is abandoned and the worker restarted.
OCR_PAGE_TIMEOUT = float(os.environ.get("SEARCH_OCR_PAGE_TIMEOUT", "240"))
# Below this, a PDF's text layer is treated as missing (the OCR trigger).
OCR_MIN_CHARS_PER_PAGE = int(os.environ.get("SEARCH_OCR_MIN_CHARS_PER_PAGE", "200"))

# --- Chat / LLM enrichment (Celonis AI Gateway, chat models only) -----------
# Used to clean bibliographic metadata and extract keywords/concepts. Optional:
# enrichment degrades gracefully when the gateway is unreachable.
CHAT_BASE_URL = os.environ.get("CELONIS_AI_GATEWAY_BASE_URL", "https://ai.celonis.dev/v1").rstrip("/")
CHAT_PATH = os.environ.get("CELONIS_AI_GATEWAY_CHAT_PATH", "/chat/completions")
# A small, fast model is plenty for structured extraction.
CHAT_MODEL = os.environ.get("SEARCH_CHAT_MODEL", "claude-haiku-4-5-20251001")
