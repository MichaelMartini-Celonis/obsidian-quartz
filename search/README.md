# `search/` — Graph-RAG search engine over `~/docs`

- **Two indexes:** `search/index.duckdb` (papers + `Internal/` + `Personal/drive`, default) and
  `search/meet.duckdb` (`--db meet`, Google Meet / Gemini notes under `Personal/meet/`).
  The main index has an `internal` flag: `Internal/` and `Personal/` are `TRUE`; public
  `Literature/` is `FALSE`. Use `--internal-only` / `--external-only`.

- **Vector search:** DuckDB `vss` (HNSW, cosine) over chunk embeddings.
- **Lexical search:** DuckDB built-in `fts` (BM25).
- **Hybrid retrieval:** results from both are fused with Reciprocal Rank Fusion.
- **Embeddings:** a **local** model via `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim, ONNX/CPU) —
  no network at query time, data never leaves the machine. A network-free `hash` embedder exists for
  development, and a `gateway` client is retained for a future endpoint.
- **Knowledge graph:** authors / keywords / topics / similarity as a `duckpgq` property graph,
  with graph-expanded retrieval (`search --expand`). *(Phase 1)*
- **Metadata enrichment:** an optional LLM pass (Celonis AI Gateway chat models) cleans
  `title / authors / year / venue` and extracts `keywords`. *(Phase 1)*

## Status: Phase 0 + Phase 1

Implemented: incremental ingest (extract → chunk → embed → upsert), HNSW + BM25 indexes, hybrid
search, a proceedings splitter, LLM enrichment, and a `duckpgq` knowledge graph with graph-expanded
retrieval. See `PROGRESS.md` for the roadmap (Phase 2 = citations & Outbox `RELATED_TO`).

## Setup

Dependencies live in the shared venv at `../scripts/.venv`:

```bash
cd ~/docs
scripts/.venv/bin/python -m pip install -r search/requirements.txt
```

### Embeddings — local model (default)

The engine embeds with a **local** model via [`fastembed`](https://github.com/qdrant/fastembed):
`BAAI/bge-small-en-v1.5` (384-dim, ONNX, CPU). It requires no credentials, makes no network calls at
query time, and keeps all document text on the machine. The model (~130 MB) is downloaded once from
the Hugging Face Hub on first use and cached under `~/.cache/`.

No configuration is needed — just install the requirements and build the index:

```bash
scripts/.venv/bin/python -m search.cli index --reset
```

To use a different local model, set `SEARCH_LOCAL_MODEL` to any id
[supported by fastembed](https://qdrant.github.io/fastembed/examples/Supported_Models/), e.g.
`export SEARCH_LOCAL_MODEL="BAAI/bge-base-en-v1.5"` (768-dim — requires a `--reset` rebuild since the
vector dimension changes).

> **Why not the Celonis AI Gateway?** The gateway (`https://ai.celonis.dev`) proxies **chat models
> only** — `GET /v1/models` returns Claude/GPT/GLM/Qwen/etc., and every embedding model name is
> rejected with *"Invalid model name … Call /v1/models to view available models."* There is no
> embedding endpoint behind it today, so a local model is used instead. The `gateway` embedder
> (`SEARCH_EMBEDDER=gateway` + `CELONIS_AI_GATEWAY_*` vars) is kept ready for if/when an embedding
> model is added.

For pipeline testing without any model, `SEARCH_EMBEDDER=hash` uses a deterministic,
**non-semantic** hash embedder.

## Usage

Run from `~/docs`:

```bash
# Build / refresh the index (Literature + Transcripts + notebooks + db_systems + Outbox + Internal + Personal/drive).
scripts/.venv/bin/python -m search.cli index

# Limit / scope while testing:
scripts/.venv/bin/python -m search.cli index --roots literature --limit 50
scripts/.venv/bin/python -m search.cli index --roots notebooks     # just the notebooks/ root
scripts/.venv/bin/python -m search.cli index --roots internal
scripts/.venv/bin/python -m search.cli index --roots personal      # Personal/drive only
scripts/.venv/bin/python -m search.cli index --reset          # drop & rebuild (needed if the embedder dim changes)

# Query:
scripts/.venv/bin/python -m search.cli search "object-centric process discovery" -k 10
scripts/.venv/bin/python -m search.cli search "PQL" --internal-only
scripts/.venv/bin/python -m search.cli search "object-centric" --external-only

# Index statistics:
scripts/.venv/bin/python -m search.cli stats

# Meeting notes (separate DuckDB file; does not touch the paper index):
scripts/.venv/bin/python scripts/garden-sync.py pull-meet --index
scripts/.venv/bin/python -m search.cli --db meet index
scripts/.venv/bin/python -m search.cli --db meet search "event handling"
```

### Proceedings → per-paper PDFs

Conference proceedings bundle dozens of papers in one PDF. Split them (on outline bookmarks) so
each paper is its own document — much better titles/authors and graph edges:

```bash
scripts/.venv/bin/python -m search.split_proceedings              # dry-run: show the plan
scripts/.venv/bin/python -m search.split_proceedings --apply      # write '<stem> (papers)/' PDFs
```

Originals stay in place; the indexer automatically skips a monolith once its `(papers)/` folder
exists. Only clean, sane outlines are split; ambiguous volumes are left whole.

### Metadata enrichment (Celonis AI Gateway, optional)

The heuristic importer often produces poor titles/authors. An LLM pass cleans them and adds
keywords (which become graph nodes). It uses the gateway **chat** models (there is no embedding
model — see below) with a virtual key from `celai get api-key`:

```bash
scripts/.venv/bin/python -m search.cli enrich                 # all un-enriched docs
scripts/.venv/bin/python -m search.cli enrich --only-review   # just low-confidence ones
```

Results are cached in `doc_enrichment` (keyed by content hash), so it is idempotent and resumable.
Override the model with `SEARCH_CHAT_MODEL` (default `claude-haiku-4-5-20251001`). Requires VPN.

### Container metadata + abstracts (no model, no network)

Deterministic reads of the PDF container — creation dates, producer, XMP packet, embedded font
count, text-layer density — plus an anchored abstract lifted from the existing text layer. Every
value is written with its provenance to `field_provenance`, so a later pass can tell a Crossref fact
from a model's guess and refresh only the weak fields:

```bash
scripts/.venv/bin/python -m search.cli metadata            # backfill everything missing
scripts/.venv/bin/python -m search.cli metadata --status   # coverage report
```

### OCR for scans — a local VLM (default), no data egress

Image-only PDFs are invisible to search; a document-parsing VLM makes them readable. It runs
**locally on Apple silicon via MLX** — `PaddleOCR-VL` (0.9B, Apache-2.0) at ~5 s/page on an M4 Max —
so page images never leave the machine and `Internal/` scans are fair game:

```bash
scripts/.venv/bin/python -m search.cli ocr --list                  # what would be processed
scripts/.venv/bin/python -m search.cli ocr --only-empty            # no text layer, or an unusable one
scripts/.venv/bin/python -m search.cli ocr --low-density --promote  # + thin ones, then re-index
scripts/.venv/bin/python -m search.cli ocr --retry-failed          # mop up GPU timeouts
scripts/.venv/bin/python -m search.cli ocr --status                # coverage + failure report
```

`--only-empty` covers more than empty PDFs, because "has text" and "has *readable* text" are
different questions. ~130 documents in this corpus extract thousands of characters per page of glyph
names (`/BW/CT/DA`), control codes, or words with every space dropped — a font without a usable
`ToUnicode` map. They pass every length-based check while being unsearchable, and their heuristic
titles are derived from the garbage (`and hN - 23, 254768.pdf`). The `metadata` stage flags them as
`text_garbled` on three independent measures: how language-like the layer is
(`text_readable_ratio`, function-word share across en/de/nl/fr), the share of characters that cannot
be text at all, and the share of letters stranded in 20+ character runs (`glued_ratio`, which is what
catches lost word boundaries — the case that defeats the other two). See `DESIGN-ocr-metadata.md`
§3.1–3.2 for why no single threshold separates these from Slovenian prose, slide decks and monographs.

The model stack lives in a **separate venv** so this one stays free of a GPU runtime:

```bash
uv venv --python 3.13 scripts/.venv-ocr
uv pip install --python scripts/.venv-ocr/bin/python mlx-vlm pypdfium2
```

`ocr` is never part of `index`: it is 3–4 orders of magnitude slower than `pypdf`, so it writes to the
`doc_ocr` cache and `index` merely *prefers* that cache for documents whose own text layer is missing
or thin. Re-indexing never re-OCRs. Output is validated before it is trusted — a repetition guard
(these models degenerate into loops), a yield guard that distinguishes a blank page from an unread
one by ink coverage, and a per-page timeout. Swap models with `--backend mlx-glm-ocr` /
`mlx-deepseek-ocr-2` / `mlx-granite-docling`, or set `SEARCH_OCR_BACKEND`. Rationale and measurements:
`DESIGN-ocr-metadata.md` §2.

### Knowledge graph (duckpgq) & graph-expanded search

```bash
scripts/.venv/bin/python -m search.cli graph --build          # build entity tables + property graph
scripts/.venv/bin/python -m search.cli graph                  # node/edge counts
scripts/.venv/bin/python -m search.cli graph --author "Wil van der Aalst"   # papers + co-authors
scripts/.venv/bin/python -m search.cli search "queue mining" --expand       # + related-via-graph hits
```

The property graph `kg` has `Document`, `Author`, `Keyword`, `Topic` vertices and `has_author` /
`has_keyword` / `has_topic` / `similar_to` edges. `similar_to` is a cosine-kNN over mean per-document
embeddings. Rebuild the graph after re-indexing or enriching.

## What gets extracted (Phase 0)

Per document: content hash (`doc_id`), path, filetype, size/mtime, `source` (Literature/Outbox/Inbox),
`topic` (the `Literature/` folder), best-effort `title` / `authors` / `year`, page-anchored text, and
page-anchored **chunks** with embeddings. Low-confidence bibliographic parses are flagged
`needs_review`. Richer author/keyword/topic/citation extraction is Phase 1–2.

Measured against the current index, this leaves large gaps: **68%** of documents have no authors and
**82%** no venue. Two of the gaps are now closed — `abstract` went from 0% to **61%** and the OCR
trigger (`has_text_layer`, `chars_per_page`, `is_image_only`, `text_garbled`) is materialized rather
than re-derived by ad-hoc SQL — by the `metadata` and `ocr` stages above. The remaining tiers (layout-aware author
and venue extraction, parsed references for `CITES`, external authority reconciliation) are specified
in **`DESIGN-ocr-metadata.md`** §4–6.

## Layout

| File | Purpose |
|---|---|
| `config.py` | Env-driven configuration (paths, chunking, embedder). |
| `db.py` | DuckDB connection, extension loading, schema, index creation. |
| `extract.py` | Per-filetype text + bibliographic extraction. |
| `chunk.py` | Paragraph-aware chunking with overlap. |
| `embeddings.py` | Local (fastembed) embedder + gateway client + dev hash embedder + `get_embedder()`. |
| `index.py` | Incremental ingest pipeline + embedding cache + prune. |
| `query.py` | Hybrid vector + BM25 retrieval (RRF) + graph expansion. |
| `llm.py` | Celonis AI Gateway chat client (token via `celai get api-key`). |
| `enrich.py` | LLM metadata cleanup → `doc_enrichment` + document rows. |
| `graph.py` | Entity tables, `SIMILAR_TO` kNN, `duckpgq` property graph + graph queries. |
| `metadata.py` | Tier-0 container metadata, abstract extraction, `field_provenance` merge rule. |
| `ocr.py` | OCR stage: candidate selection, worker protocol, output validation, `doc_ocr` cache. |
| `ocr_worker.py` | Runs in `scripts/.venv-ocr`: rasterizes pages (`pypdfium2`) and drives the VLM (MLX). |
| `split_proceedings.py` | Split proceedings PDFs into per-paper PDFs on outline bookmarks. |
| `cli.py` | `index` / `search` / `stats` / `enrich` / `metadata` / `ocr` / `graph` commands. |
| `DESIGN-ocr-metadata.md` | Design + measurements: local OCR backend choice, tiered metadata schema. |

The DuckDB file (`search/index.duckdb`) is gitignored and rebuilt from the corpus.

## Notes & caveats

- **DuckDB version / Phase 1:** pinned to `duckdb==1.4.4` (see `requirements.txt`) for `duckpgq`
  (SQL/PGQ, Phase 1) compatibility; `vss` + `fts` are verified on this version.
- **HNSW persistence** is experimental in a disk-backed DB (`hnsw_enable_experimental_persistence`);
  fine at this corpus size (index must fit in RAM).
- **Large PDFs:** multi-thousand-page conference proceedings are slow to extract. Use
  `SEARCH_MAX_CHARS` to cap characters embedded per document if needed.
- **Relocatable venv:** the venv was moved, so `scripts/.venv/bin/pip` has a stale shebang. Use
  `scripts/.venv/bin/python -m pip …` instead.
