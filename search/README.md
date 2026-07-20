# `search/` — Graph-RAG search engine over `~/docs`

An embedded search engine over the knowledge repository (the `Literature/` library and `Outbox/`
drafts). Everything runs in a single embedded **DuckDB** database — no server.

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
# Build / refresh the index (Literature + Outbox by default). Incremental & idempotent.
scripts/.venv/bin/python -m search.cli index

# Limit / scope while testing:
scripts/.venv/bin/python -m search.cli index --roots literature --limit 50
scripts/.venv/bin/python -m search.cli index --reset          # drop & rebuild (needed if the embedder dim changes)

# Query:
scripts/.venv/bin/python -m search.cli search "object-centric process discovery" -k 10

# Index statistics:
scripts/.venv/bin/python -m search.cli stats
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
| `split_proceedings.py` | Split proceedings PDFs into per-paper PDFs on outline bookmarks. |
| `cli.py` | `index` / `search` / `stats` / `enrich` / `graph` commands. |

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
