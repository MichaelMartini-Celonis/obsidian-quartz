# Search engine — progress & roadmap

A living status doc for the Graph-RAG search engine over the `~/docs` knowledge repository.
Last updated: 2026-07-20.

## Goal

A small, embedded "helper" search engine over the paper library (`Literature/`) and authored
drafts (`Outbox/`): hybrid lexical + semantic retrieval now, a knowledge graph (authors, topics,
keywords, citations) for Graph-RAG next.

## Key decisions

| Area | Decision | Rationale |
|---|---|---|
| Store | Single embedded **DuckDB** file | No server; one stack for vector + text + graph |
| Vector | `vss` (HNSW, cosine) | In-process ANN over chunk embeddings |
| Lexical | DuckDB built-in **`fts`** (BM25) | Avoids PyLucene/lupyne install pain; one dependency-light stack |
| Graph | `duckpgq` (SQL/PGQ) — **Phase 1** | Property-graph queries over the same tables |
| Fusion | Reciprocal Rank Fusion (vector + BM25) | Simple, robust hybrid ranking |
| Embeddings | **Local model** via `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim, ONNX/CPU) | AI Gateway has no embedding model; local keeps data on-machine, no cost, no query-time network |
| DuckDB version | **Pinned `duckdb==1.4.4`** | duckpgq (Phase 1) is version-sensitive; `vss` + `fts` verified on 1.4.4 |
| lupyne | Evaluated, **not used** | DuckDB `fts` covers BM25 without a JVM/PyLucene build |

### Decision log

- **2026-07-20 — Phase 1 knowledge graph shipped (`duckpgq`).** Added `authors`,
  `keywords`, `topics` node tables + `has_author` / `has_keyword` / `has_topic` /
  `similar_to` edges, and a `duckpgq` property graph `kg` over them. `SIMILAR_TO` is a
  cosine-kNN over mean per-document embeddings (computed in numpy). Graph-expanded
  retrieval (`search --expand`) adds related docs via shared authors / keywords /
  similarity. New CLI: `graph --build`, `graph --author`, `enrich`. Verified `duckpgq`
  loads on 1.4.4 and property-graph `MATCH` works (params don't bind inside
  `GRAPH_TABLE` → literals are inlined with escaping).
- **2026-07-20 — LLM metadata enrichment via the gateway (chat).** The gateway serves
  chat models only (re-confirmed: 19 models, 0 embedding), so we use it for enrichment,
  not vectors. `search/llm.py` gets a virtual key from `celai get api-key` and calls
  `claude-haiku-4-5` (small/fast) to re-extract clean `title/authors/year/venue/keywords`
  from each doc's opening text. Cached in `doc_enrichment` (keyed by content hash);
  optional and degrades gracefully offline. Fixes the heuristic importer's garbage
  titles/author-blobs, which feed the author graph.
- **2026-07-20 — Proceedings split into per-paper PDFs (`search/split_proceedings.py`).**
  18 conference volumes (BPM/CAiSE/ICPM) → ~432 per-paper PDFs, cut on PDF outline
  bookmarks (paper = bookmark followed by a nested author/section list; front matter and
  section headers filtered). Robust guards: min 100-page volume, per-paper 5–80 pages,
  ≥80% sane ranges or the volume is left whole. Originals stay in place; the indexer
  skips a monolith once a sibling `<stem> (papers)/` folder exists.
- **2026-07-17 — Embeddings run on a LOCAL model, not the AI Gateway.** Probed the gateway with the
  `celai get api-key` virtual key: `GET https://ai.celonis.dev/v1/models` returns **chat models
  only** (Claude/GPT/GLM/Qwen/…); every embedding model name (`text-embedding-3-small/-large`,
  `-ada-002`, `embed-english-v3.0`, `nomic-embed-text`) is rejected with *"Invalid model name … Call
  /v1/models to view available models."* So there is no embedding endpoint behind the gateway.
  Switched the default embedder to a local `fastembed` model (`BAAI/bge-small-en-v1.5`, 384-dim,
  ONNX/CPU) — no credentials, no query-time network, data stays on-machine. Verified semantically
  (query "process mining" scored 0.845 vs 0.297 on an unrelated sentence). The `gateway` embedder is
  retained behind `SEARCH_EMBEDDER=gateway` for a future endpoint.
- **2026-07-17 — Pinned `duckdb==1.4.4`.** For compatibility with the `duckpgq` community extension
  in Phase 1 (DuckDB docs recommend 1.4.4). Verified `vss` + `fts` + `array_cosine_distance` work on
  1.4.4; `search/requirements.txt` updated and the stale 1.5.4-built index removed.

## Done

- **Repo restructure:** `~/docs` is now a single git project (promoted the former `obsidian-quartz`
  git root up; remote unchanged). `context-model-documentation` moved to gitignored
  `reference/`. Top-level `.gitignore` covers `Literature/`, `Inbox/*`, `imports/`, `reference/`,
  `scripts/.venv/`, and the search DB.
- **Cleanup:** removed stray `.DS_Store`; removed the Quartz site generator + its docs; kept and
  relocated the importer (`scripts/`), the agent rule (`.cursor/`), and `imports/` (incl. the
  Literature backup zip) to the top level; removed the obsolete one-off scripts, leaving only the
  maintained `import-downloads.py`.
- **Phase 0 search engine (`search/`):** incremental ingest (extract → chunk → embed → upsert),
  HNSW + BM25 indexes, embedding cache, and a hybrid-search CLI (`index` / `search` / `stats`).
  - Pinned `duckdb==1.4.4`; installed `fastembed` (local embeddings) into `scripts/.venv`.
  - **Local embedder wired in** (`BAAI/bge-small-en-v1.5`) after confirming the gateway serves no
    embedding model; default `get_embedder()` is now `local`, queries use the bge query prefix.
- **Inbox backlog imported (2026-07-20):** 230 files moved into `Literature/` by the importer
  (many with weak heuristic titles → cleaned by `enrich`). Some off-topic/junk files (e.g. train
  tickets) landed in `Literature/Inbox/` and are flagged for manual review, not auto-deleted.
- **Proceedings split (2026-07-20):** 18 volumes → ~432 per-paper PDFs (`split_proceedings.py`);
  monoliths kept but skipped by the indexer.
- **Phase 1 graph (2026-07-20):** `graph.py` (entities + `duckpgq` property graph + `SIMILAR_TO`),
  `llm.py` (gateway chat client), `enrich.py` (LLM metadata cleanup), and CLI `enrich` / `graph` /
  `search --expand`.
  - **Full index built** over Literature + Outbox (2026-07-19): **336 documents / 26,922 chunks**,
    0 errors, giant proceedings capped via `SEARCH_MAX_CHARS=400000`. Spot-checked `search` quality —
    on-topic papers surface correctly (e.g. object-centric process mining → van der Aalst OCPM /
    PromG / Berti SLR). 193 docs flagged `needs_review` for low-confidence biblio parses.

## Phase 0 — extraction implemented

Per document: content hash (`doc_id`), path, filetype, size/mtime, `source`
(Literature/Outbox/Inbox), `topic` (the `Literature/` folder), best-effort `title` / `authors` /
`year`, page-anchored text, page-anchored **chunks** + embeddings, and a `needs_review` flag for
low-confidence bibliographic parses.

## Roadmap

- **Phase 0 — hybrid search** ✅
- **Phase 1 — knowledge graph** ✅ (this)
  - ✅ Author nodes + `has_author` edges + co-authorship queries (`graph --author`)
  - ✅ Keywords from LLM enrichment → `Keyword` nodes + `has_keyword` edges
  - ✅ Topics (folder taxonomy) → `Topic` nodes + `has_topic` edges
  - ✅ `SIMILAR_TO` (materialized cosine-kNN over mean doc embeddings)
  - ✅ `duckpgq` property graph `kg`; graph-expanded retrieval (`search --expand`)
  - ⏳ Author disambiguation/merging beyond ascii-normalization (LLM enrichment helps)
  - ⏳ Multi-label / zero-shot topic tagging (currently one folder-topic per doc)
- **Phase 2 — citations & Outbox**
  - Reference parsing (GROBID/regex) + fuzzy title match → `CITES` edges
  - Outbox drafts as `Artifact` nodes with `RELATED_TO` links into `Literature/`
  - `needs_review` reconciliation report (surfaces mis-named / duplicate library files)
- **Phase 3 — surface (optional)**
  - Expose as an MCP tool / small API; revisit lupyne only if `fts` proves insufficient

## Open items / next steps

- [x] Choose an embedding backend — **local `fastembed` model** (gateway has no embeddings).
- [x] Confirm the gateway's models (`GET /v1/models`) — chat only, no embeddings.
- [x] Finish the full `index --reset` over Literature + Outbox and spot-check `search` quality —
      336 docs / 26,922 chunks, 0 errors; retrieval spot-checks look good (2026-07-19).
- [x] Handling for multi-thousand-page proceedings — **split into per-paper PDFs** on outline
      bookmarks (`split_proceedings.py`); non-proceedings books stay capped at 400k chars/doc.
      Also early-stop PDF extraction past the cap (extraction, not just embedding, was the bottleneck).
- [x] Pin a `duckpgq`-compatible DuckDB version — pinned `duckdb==1.4.4` (2026-07-17).
- [x] Inbox backlog import (2026-07-20, 230 files). Duplicate cleanup handled by the importer;
      mis-named files improved by `enrich`.
- [ ] Manual review: off-topic/junk imports now under `Literature/Inbox/` (train tickets, etc.)
      and remaining `needs_review` docs after enrichment.
- [ ] Author disambiguation across spelling variants; multi-label topic tagging.

## Caveats

- Embeddings are **local** (`BAAI/bge-small-en-v1.5`, 384-dim). Changing `SEARCH_LOCAL_MODEL` changes
  the vector dimension and requires `index --reset`.
- First run downloads the model (~130 MB) from the Hugging Face Hub; cached thereafter.
- HNSW disk persistence is experimental (fine at this corpus size).
- The relocated venv's `pip` shebang is stale — use `scripts/.venv/bin/python -m pip …`.
