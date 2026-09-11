# Design proposal — OCR stage + richer document metadata

Status: written 2026-08-13 against index `9,931 documents / 651,138 chunks`.

- **Phase A: implemented** 2026-08-14 (`search/metadata.py`, `search.cli metadata`). Results in §8.
- **Model choice: settled** 2026-08-14 in favour of a **local MLX model as the default**, after
  measuring one on this machine. §2 has been rewritten from proposal to measurement.
- Phases C–F: still proposals.

Two related additions to the ingest pipeline:

1. An **OCR / document-parsing stage** that turns page images into text, so image-only PDFs stop
   being invisible to search.
2. A **metadata extraction stage** built on the same page images, which fills in the bibliographic
   and structural fields the current heuristic extractor cannot reach.

---

## 1. Why — what the index actually looks like today

The motivation for OCR is usually "we have unreadable scans". Measured, that problem is small; the
metadata problem is large. Both numbers come from the live index:

| Symptom | Count | Share |
|---|---|---|
| PDFs with **zero** extracted text (pure scans) | 10 docs, 611 pages | 0.1% |
| PDFs with text but **< 200 chars/page** (partial/failed text layer) | 8 docs, 158 pages | 0.1% |
| Documents with **no authors** | 6,726 | 68% |
| Documents with **no year** | 2,319 | 23% |
| Documents with **no venue** | 8,109 | 82% |
| Documents with **no abstract** | 9,931 | 100% |
| Documents flagged `needs_review` | 4,239 | 43% |
| Documents LLM-enriched so far | 2,076 | 21% |

Reading that table:

- **OCR alone is an ~18 document, ~770 page job.** Worth doing (it includes real papers such as the
  SRQL tech report we just added), but it would be a poor justification for the infrastructure on
  its own.
- **The `abstract` column is populated for zero documents** even though it exists in the schema and
  in `ExtractedDoc`. Nothing ever writes it. That is a pure bug-shaped gap.
- **Two thirds of the corpus has no author list**, which directly starves the `authors` node table
  and every co-authorship query in the knowledge graph.
- Layout is the root cause for most of it. `pypdf.extract_text()` returns a flat character stream,
  so a two-column paper's title block, author list, affiliations and abstract arrive interleaved
  with running heads and footnotes. The heuristic in `_extract_pdf` copes by taking "the first line
  with ≥3 words and no `@`" as the title and never attempting authors beyond the PDF Info dict.

**The design consequence:** a document-parsing VLM is worth adopting not because 18 files are
scanned, but because it reads *layout*. Running it over **page 1–2 of every PDF** is what fixes the
68%/82%/100% rows — and that is the same machinery the 18 scans need for all their pages. So OCR and
metadata extraction should be one subsystem with two entry points, not two projects.

---

## 2. Model choice — local by default, measured on this machine

The earlier draft of this section proposed a remote multimodal chat model as the default and treated
local execution as a risky optimization. **That is reversed.** The default is now a local model, and
the reversal is not an aesthetic preference: it was cheaper to verify than to argue about, so it was
verified. Everything below is measured on this machine unless marked otherwise.

### 2.1 The machine and the constraint that actually bites

Apple **M4 Max, 36 GB unified memory, arm64**, macOS 26.5.1, no CUDA. The search venv runs **Python
3.14.6** and is deliberately lean — `fastembed` + `onnxruntime`, no torch.

Memory is not the constraint: every candidate below, up to 5.3B parameters at bf16, fits in 36 GB
unified memory with room to spare. The constraints that bite are **installability on Python 3.14
arm64** and **whether the vision stack runs on Apple silicon at all**. Checked against PyPI:

| Package | Verdict |
|---|---|
| `mlx` 0.32.0 | ✅ ships `cp314` wheels including `macosx_26_0_arm64` |
| `mlx-vlm` 0.6.13 | ✅ pure Python (`py3-none-any`); its compiled deps (`opencv-python` abi3, `miniaudio`, `llguidance`) all have arm64 wheels |
| `torch` 2.13.0 | ✅ `cp314` macOS arm64 wheel exists, so an MPS path is *possible* |
| `PyMuPDF` 1.28.2 | ❌ **no macOS arm64 `cp314` wheel** (Linux x86-64 only) |
| `pypdfium2` 5.13.0 | ✅ `py3-none-macosx_13_0_arm64` (abi3, version-independent) |

Two corrections to §3 follow from that table. **Rasterize with `pypdfium2`, not PyMuPDF** — it is
the only one that installs here, and as a bonus it is Apache-2.0/BSD-3 rather than AGPL-3.0, which
retires the licensing caveat this document used to carry. And the OCR dependencies go in a
**separate venv** (`scripts/.venv-ocr`, Python 3.13 for widest wheel coverage) driven as a
subprocess worker, so the lean ONNX-only search venv stays lean and the model stack can be swapped
without touching the search install.

### 2.2 Rejecting the vendor's own pipeline

`PaddleOCR-VL` is the model that was asked for, and it is the right one. Its *official* runtime is
not usable here. The model card's install path is PaddlePaddle plus `paddleocr[doc-parser]`, and it
states plainly: **"For macOS users, please use Docker to set up the environment."** A Docker-wrapped
Linux PaddlePaddle runtime on this Mac would be CPU-only — the worst of both worlds.

The card also documents a `transformers` path (`AutoModelForImageTextToText`, transformers ≥ 5.0,
**no `trust_remote_code`** — `paddleocr_vl` is one of 504 native model directories in transformers
`main`). It carries a caveat: the model-only path "only supports element-level recognition and text
spotting", because the official pipeline is two-stage — a layout detector (PP-DocLayoutV2/V3) crops
regions and the VLM recognizes each one. GLM-OCR is built the same way. So the honest question was
not "does the model load" but **"does a compact region-recognizer produce usable whole-page text
when handed a whole page?"**

### 2.3 What was measured

`mlx-vlm` turns out to support the entire candidate field natively — `paddleocr_vl`, `glm_ocr`,
`deepseekocr_2`, `unlimited_ocr`, `dots_ocr`, `idefics3`, `qwen3_5` are all in its model registry.
That removes the "unpatched remote code on MPS" gamble the earlier draft worried about: MLX runs on
Metal directly, with no `.cuda()` calls, no flash-attention dependency and no MPS op gaps.

Spike: `mlx-community/PaddleOCR-VL-1.5-bf16` (1.82 GB) against page 4 of a real corpus scan —
`Literature/Process Querying/…SRQL….pdf`, an image-only 14-page technical report, rendered at
200 dpi to 1707×2200 px with `pypdfium2`:

| Step | Measurement |
|---|---|
| Rasterize one page, 200 dpi | 0.10–0.35 s |
| Model load, weights cached | **0.8 s** (first run: 173 s to download 15 files) |
| `OCR:` on the **full page** | **4,997 chars in 4.6 s, 310 tok/s** |
| `Spotting:` on the full page | 9,069 chars in 5.9 s, 309 tok/s |

The `OCR:` output is continuous, correctly ordered prose with inline LaTeX for the mathematics
(`\(\tau\)`, `\(f_{\text{synch-write}}\)`) — not a bag of fragments. **The element-level caveat is
conservative for single-column pages: whole-page `OCR:` is usable as-is.** `Spotting:` returns the
same text interleaved with `<|LOC_n|>` quadrilateral tokens, which is what makes multi-column
reading order and title-block localisation solvable without a separate layout model.

Two useful by-products of the spike. Page 1 of that file is the cover sheet of *"A Customized MVA
Model for ILP Multiprocessors", Technical Report #1369, May 1998* — so the document is **mis-titled
in the library**, filed under Ramakrishnan's SRQL. Invisible before OCR, obvious after; a small
preview of what the metadata pass is for. And at ~5 s/page the arithmetic is: **~770 candidate pages
≈ 1 hour**, while a two-page front-matter pass over ~9,900 PDFs is ~20–25 hours and therefore has to
be chunked and resumable rather than run in one sitting.

### 2.4 The backend table

Pluggable exactly as `config.EMBEDDER` already is for `local`/`gateway`/`hash`. `OCR_BACKEND` ∈:

| Backend | Where it runs | Weights | Verdict |
|---|---|---|---|
| `mlx-paddleocr-vl` | **This Mac, MLX/Metal** | `mlx-community/PaddleOCR-VL-1.5-bf16`, 1.82 GB | **Default.** Measured above. Apache-2.0, 0.96B params. 8-bit (1.10 GB) and 4-bit conversions exist if memory ever matters. `PaddleOCR-VL-1.6` is SOTA on OmniDocBench v1.6 (96.33%) and *architecturally identical* to 1.5 — no MLX build is published yet, but `mlx_vlm.convert` produces one locally, so 1.6 is a one-command upgrade. |
| `mlx-glm-ocr` | This Mac, MLX | `mlx-community/GLM-OCR-{bf16,8bit,4bit}` | First alternative. 1.33B, MIT, native `glm_ocr` in transformers, #1 on OmniDocBench v1.5 at time of writing. Same two-stage caveat as PaddleOCR-VL. |
| `mlx-deepseek-ocr-2` | This Mac, MLX | `mlx-community/DeepSeek-OCR-2-{bf16,8bit}` | For pages where region recognition disappoints: 3.39B, Apache-2.0, designed for single-pass whole-page markdown, so no layout stage is implied. |
| `mlx-granite-docling` | This Mac, MLX or ONNX | `ibm-granite/granite-docling-258M{,-mlx}` | The cheap end: 258M, Apache-2.0, whole-page DocTags in one shot. An ONNX build exists, which the **already-installed** `onnxruntime` could run with no new heavy dependency at all. Lowest quality of the set. |
| `gateway-vision` | Celonis AI Gateway | — | **Demoted to fallback.** Still trivially available (`llm.py:chat()` already forwards OpenAI-style `messages`, so multimodal `image_url` blocks need no transport change), but it sends page images off the machine. |
| `unlimited-ocr-vllm` | Rented GPU | `baidu/Unlimited-OCR` | Only if the front-matter pass over the whole corpus is wanted in one sitting rather than chunked overnight. Its `infer_multi` multi-page-single-pass trick remains attractive, and its documented repetition degeneration (`no_repeat_ngram_size=35` is *required*) remains a reason for the validation layer in §3. |
| `none` | — | — | Skip OCR; pipeline degrades exactly as today. |

Choosing local by default also dissolves the data-egress question §7 used to raise. Three of the 28
OCR candidates are `Internal/` documents — including
`wvdaalst - PQL Engine Saola DB (2).pdf`. With a local default there is no decision to get wrong:
nothing leaves the machine, and `internal = TRUE` only needs guarding on the two remote backends.

The interface each backend implements stays tiny:

```python
def parse_pages(images: list[Path], mode: str) -> list[PageParse]:
    """mode: "text" (plain reading order) | "document" (markdown w/ tables+formulas)."""
```

---

## 3. Where OCR fits in the pipeline

Today: `discover → extract → chunk → embed → upsert`, and `index` is fast and idempotent because a
document whose content hash is unchanged is skipped outright.

**OCR must not go inline in `index`.** It is 3–4 orders of magnitude slower than `pypdf`, and
burying it in `index_file()` would make every routine re-index unpredictable. Instead it becomes a
**separate, explicitly-invoked stage that writes to a cache**, and `extract` merely *prefers* the
cache when present:

```
                    ┌─────────────────────────────────────────┐
  index  ──────────▶│ extract.py                              │
                    │   pypdf text layer                      │
                    │   └─ if cached OCR exists → prefer it  ─┼──┐
                    └─────────────────────────────────────────┘  │
                                                                 │ reads
  ocr  ────▶ select ─▶ rasterize ─▶ backend ─▶ validate ─▶ ┌─────▼──────┐
             (policy)   (PyMuPDF)    (VLM)    (repetition)  │  doc_ocr   │
                                                            └─────┬──────┘
  metadata ─▶ front matter + references pages ─▶ VLM/LLM ─▶ ┌─────▼──────────────┐
                                                            │ doc_bibliography,  │
                                                            │ doc_contributors,  │
                                                            │ doc_references, …  │
                                                            └────────────────────┘
```

This mirrors the two caching patterns already in the codebase — `embedding_cache` keyed by
`(model, text_hash)` and `doc_enrichment` keyed by content hash — so the properties are familiar:
re-indexing never re-OCRs, and a `--reset` rebuild re-promotes cached OCR instead of re-paying for
it.

### Selection policy

A document is an OCR candidate when any of:

- `n_chunks = 0` and `filetype = '.pdf'` — the 10 pure scans;
- `chars_per_page < 200` **and `filetype = '.pdf'`** — the partial failures (threshold
  `SEARCH_OCR_MIN_CHARS_PER_PAGE`). The filetype guard is not decoration: running the Phase A
  columns unfiltered returns 28 rows of which 10 are `.md`, `.docx`, `.pptx` and `.bpmn` files that
  are simply short, not scanned. Ten of the 18 remaining are the pure scans, so the honest size of
  the Phase B job is **18 PDFs / ~770 pages**;
- `text_garbled` — the PDF extracts *plenty* of characters, none of which are language (§3.1);
- the PDF has no embedded fonts / no text-layer operators — catches scans *before* they are indexed
  as empty (`embedded_font_count = 0`, now a Phase A column);
- `--all-front-matter`: page 1–2 of **every** PDF, for the metadata pass.

### 3.1 The third defect class: a dense text layer that is not text

Both rules above measure the *volume* of extracted text, which turns out to miss the largest group of
unsearchable documents in the corpus. A PDF can hand over 6,500 characters per page of which none is
a word:

| Failure | What extraction yields | Cause |
|---|---|---|
| Glyph names | `/BW/CT/DA/CT/D0/D3/D4` | Type 1 subset with no `ToUnicode` map |
| Control codes | `\x00\x02\x01\x04\x03` | CID font with identity encoding |
| Lost word boundaries | `themythicalman-monthEssayson` | No space glyphs; only positioning moves |

All three sail past a density threshold and are worse than absent: they are indexed, embedded,
retrieved against, and they poison the heuristic title (this is where `Literature/Inbox/and hN - 23,
254768.pdf` comes from). Detection uses two orthogonal, cheap measures over the first 12 chunks:

- **`text_readable_ratio`** — the share of lowercase word tokens that are *function words*, scored
  against English, German, Dutch and French vocabularies and taken at the best-scoring language.
  Function words carry no topical information, which is exactly what makes them a language detector:
  real prose in this corpus scores **0.20–0.39**, the Snodgrass monograph **0.005**.
- **`unmappable_ratio`** — the share of characters that cannot be text at all (C0 controls, U+FFFD,
  private-use area).

Neither works alone. A threshold on readability has to sit below **0.033**, because a slide deck, a
SQL reference guide and a page of Slovenian all live there — yet the control-code failures score up
to **0.041** by accidentally spelling function words out of noise. And unmappable characters used as
a verdict condemn healthy papers, since maths- and ligature-heavy PDFs legitimately emit private-use
codepoints. So the rule is *readability first, unmappable characters as a tiebreaker*:

```
garbled  ⟺  readable_ratio < 0.03
         ∨  (readable_ratio < 0.10 ∧ unmappable_ratio > 0.02)
```

Measured over the whole corpus this flags **98 documents / 2,736 pages** — five times the size of the
original Phase B job, and it validates cleanly in both directions on the hard cases (Slovenian,
German, slide decks and reference guides stay out; all three failure modes above come in).

`prefer_ocr` needs one adjustment for this class: its "more characters wins" tie-break between a thin
text layer and a reading of the same page is wrong here, because a garbled layer can be arbitrarily
long while containing nothing. Volume only decides the *thin* case.

### 3.2 Lost word boundaries need their own measure

Row three of the table above — `themythicalman-monthEssayson` — survives the rule in §3.1, and it
took verifying the promoted text to notice. Whitespace loss is not a *language* failure: the letters
are all correct and all mappable, so `unmappable_ratio` is 0 and enough short words fall out of the
wreckage to clear the function-word bar. Whitehead's *Science and the Modern World* scored **0.031**
against a 0.03 threshold and kept its unreadable layer in the index while 193 successfully OCR'd
pages sat unused in `doc_ocr`. No phrase query can match such a document, and no threshold on §3.1's
two axes separates it from a healthy one.

The signal that does is **run length**. Words have a bounded length; glued text does not:

- **`glued_ratio`** — the share of letters stranded inside alphabetic runs of ≥20 characters.

Over the 8,300 PDFs in the corpus, healthy documents sit at **0.003** (p90) and **0.10** (p99) while
the damaged ones sit at **0.26–0.92**, with an empty gap between. Two checks matter for trusting it:

- **It is not a front-matter artefact.** Sampling the opening of a document and sampling evenly
  across it agree on every case (0 documents scored high on the head and low on the spread), so the
  glue is a property of the whole extraction, not of an Elsevier cover page.
- **It does not condemn the healthy.** On a random 300-document sample the combined rule flags 1,
  consistent with the ~0.35% base rate.

So the rule gains a third, independent clause:

```
garbled  ⟺  glued_ratio > 0.25
         ∨  readable_ratio < 0.03
         ∨  (readable_ratio < 0.10 ∧ unmappable_ratio > 0.02)
```

This caught **28 further documents / ~2,400 pages**, mostly monographs whose length had made them
look like the corpus's most substantial holdings: Ullman's *Principles of Database and Knowledge-base
Systems* (654 pp), Beer's *Brain of the Firm* (343 pp), Naumann's *Informationsintegration* (481 pp).

**The sampling has to be shared.** The second bug behind Whitehead was that the metadata stage judged
a document by its first 12 *chunks* while `prefer_ocr` judged it by its first 12 *pages* — different
text, so a document could be flagged in one place and declined in the other, and the OCR cache was
never consulted. Both now call `metadata.spread_sample`, which draws 16 samples evenly across the
document. Agreement between the flagging stage and the substituting stage is a correctness property,
not a nicety: disagreement is silent, and it costs a full OCR run that is then thrown away.

### Stage mechanics

- **Rasterize** with `pypdfium2` at `--dpi` (default 200; 300 for hard scans), longest edge clamped
  to the backend's `image_size`. Measured at 0.10–0.35 s/page. (The earlier draft specified PyMuPDF;
  see §2.1 — it has no macOS arm64 wheel for this Python, and `pypdfium2` avoids its AGPL-3.0
  licence into the bargain.)
- **Batch** via `infer_multi` where the backend supports it; chunk into windows of N pages
  (`SEARCH_OCR_PAGES_PER_CALL`, default 8) so one bad page cannot poison a 482-page book.
- **Validate** every result before it is trusted:
  - repetition guard — longest repeated n-gram as a share of output; reject above ~30%;
  - yield guard — reject pages under ~40 chars that were not blank in the source image;
  - a per-document wall-clock timeout.
- **Record status** per page in `ocr_status` ∈ `{ok, blank, repetition, low_yield, error, timeout}`,
  so failures are queryable and retryable rather than silently absent.
- **Store** markdown *and* a plain-text reduction. Markdown preserves tables/formulas for reading;
  the plain text is what gets chunked and embedded, since `bge-small-en-v1.5` should not be
  embedding pipe-table syntax.

### CLI

```bash
scripts/.venv/bin/python -m search.cli ocr --only-empty          # the 10 zero-text PDFs
scripts/.venv/bin/python -m search.cli ocr --low-density         # + the 8 partial failures
scripts/.venv/bin/python -m search.cli ocr --all-front-matter    # p1-2 of every PDF (metadata)
scripts/.venv/bin/python -m search.cli ocr --doc-id <hash> --redo --dpi 300
scripts/.venv/bin/python -m search.cli ocr --backend mlx-glm-ocr # swap the local model
scripts/.venv/bin/python -m search.cli ocr --status              # coverage + failure report
```

The stage runs in the `scripts/.venv-ocr` interpreter (`SEARCH_OCR_PYTHON`), spawned as a worker
subprocess; the search venv itself never imports `mlx`.

Resumable and checkpointed, in the style of the existing harvesters — long runs get reaped on this
machine after ~45 minutes, so the stage must survive being killed and restarted.

---

## 4. Proposed metadata

Grouped by **provenance tier**, because provenance determines cost, trust and refresh policy. Tier 0
is free and deterministic; tier 3 needs the network. `[existing]` marks what the schema already has.

### Tier 0 — filesystem & PDF container (no model, milliseconds)

Cheap, exact, and currently under-used. Every one of these is a `pypdf`/`fitz` attribute read.

| Field | Type | Why it earns its place |
|---|---|---|
| `doc_id`, `path`, `rel_path`, `size`, `mtime`, `filetype` | — | `[existing]` |
| `source`, `topic`, `internal` | — | `[existing]` derived from location |
| `n_pages` | int | `[existing]` |
| `imported_at` | timestamp | First time seen. Distinct from `indexed_at` (last touch) — lets you ask "what entered the garden this week", which the current schema cannot answer. |
| `file_created` | timestamp | macOS birthtime; survives re-indexing. |
| `pdf_created`, `pdf_modified` | timestamp | From `/CreationDate`. Frequently the **only** reliable date on a preprint whose text shows no year — directly attacks the 2,319 missing years. |
| `pdf_producer`, `pdf_creator` | text | `"LaTeX with hyperref"` vs `"Microsoft Word"` vs `"ScanSnap"`. Identifies born-digital vs scanned, and is a strong document-type prior. |
| `pdf_version` | text | Ancient PDFs correlate with bad text layers. |
| `is_encrypted`, `is_tagged`, `has_outline` | bool | `has_outline` is what `split_proceedings.py` already keys on; making it a column stops it being re-derived. |
| `has_text_layer`, `chars_per_page` | bool, double | **The OCR trigger, materialized.** Currently recomputed by ad-hoc SQL joins against `chunks`. |
| `embedded_font_count`, `is_image_only` | int, bool | Detects scans *before* wasting an extraction pass. |
| `page_width_pt`, `page_height_pt`, `orientation` | double, text | Landscape + 4:3 ⇒ slide deck, not a paper. Cheap document-type signal. |
| `xmp_title`, `xmp_creators`, `xmp_subjects` | text, text[] | The XMP packet is usually *better* than the Info dict and is currently ignored entirely. |
| `language` | text | Detected once; lets non-English docs be handled or excluded deliberately. |
| `n_embedded_files` | int | Papers shipping datasets/code as attachments. |

### Tier 1 — document structure, from the VLM parse of front matter + back matter

This is the tier that repays the OCR investment. A layout-aware parse of pages 1–2 plus the
reference pages yields what flat text extraction cannot.

| Field | Type | Notes |
|---|---|---|
| `title` | text | `[existing]` — but re-derived from the *title block*, not "first long line". |
| `subtitle` | text | Common in books/theses. |
| `authors` | text[] | `[existing]`, currently empty for 68%. |
| `author_affiliations` | text[] | Positionally aligned to `authors`. Enables institution-level graph nodes alongside the existing `companies` layer. |
| `author_emails`, `corresponding_author` | text[], text | Email domains are a robust affiliation fallback. |
| `abstract` | text | `[existing]` column, **0% populated**. High value: a clean abstract is the best single chunk for retrieval and the best input for every downstream LLM task. |
| `keywords_declared` | text[] | The author's own `Keywords:` line. Deliberately **separate** from LLM-inferred `keywords` — never conflate what the author claimed with what a model guessed. |
| `venue` | text | `[existing]`, 82% missing. |
| `venue_type` | enum | `journal / conference / workshop / book / chapter / thesis / preprint / techreport / spec / blog / documentation`. The library mixes all of these and cannot currently distinguish them. |
| `publication_date` | date | Full date where available; `year` `[existing]` stays as the coarse key. |
| `volume`, `issue`, `page_range`, `publisher`, `series`, `edition` | text | Proper citation export (BibTeX/CSL) becomes possible. |
| `doi`, `arxiv_id`, `isbn`, `issn`, `pmid`, `handle`, `source_url` | text | **Join keys to the outside world.** Their absence is why `paperfetch.py` re-resolves titles from scratch every run and why dedup is hash-only. |
| `license`, `copyright_holder` | text | Which documents may be quoted or redistributed. |
| `section_headings` | text[] | A cheap document outline; also a retrieval feature. |
| `toc` | JSON | For books. |
| `n_figures`, `n_tables`, `n_equations`, `n_algorithms` | int | Structural fingerprint: heavy equations ⇒ theory, heavy tables ⇒ empirical. Nearly free once the VLM parse exists, since it labels these elements. |
| `references_raw` | text[] → own table | **The Phase 2 `CITES` prerequisite**, already on the roadmap in `PROGRESS.md`. Getting reference strings out is the hard half; matching them is easier. |
| `n_references` | int | Survey vs. short paper discriminator. |
| `funding`, `grant_ids` | text[] | Funder/project graph. |
| `artifact_links` | text[] | GitHub/Zenodo/dataset URLs — reproducibility, and a second bridge to the `companies` layer. |
| `document_type` | enum | `research / survey / thesis / slides / book / spec / blog / documentation / internal`. The library already mixes these across `Blogs/`, `Specifications/`, `Tool & Competitor Documentation/`; making it explicit lets search filter them. |

### Tier 2 — semantic, from the LLM (extends the existing `doc_enrichment`)

| Field | Type | Notes |
|---|---|---|
| `keywords` | text[] | `[existing]`, 2,073 docs. |
| `summary_short` | text | 1–2 sentences. Displayed in results; far better than a raw first chunk. |
| `contributions` | text[] | The paper's own claims. |
| `research_problem`, `method`, `evaluation_type` | text, text, enum | `evaluation_type` ∈ `empirical / theoretical / survey / tool / case-study / benchmark`. |
| `datasets_used`, `systems_used` | text[] | Links papers to the **`db_systems/` dbdb mirror** — a real, already-present join target. |
| `limitations` | text[] | Useful when writing related work. |
| `topic_labels` | text[] | **Multi-label, from a controlled vocabulary** — closes the `⏳ multi-label topic tagging` item in `PROGRESS.md`. The vocabulary already exists: `scripts/dbdb-taxonomy.json` (24 dbdb technical features across Data & Storage, Query Processing, Transactions & Recovery, Distributed Architecture). Today each document gets exactly one folder-derived topic. |
| `related_work_claims` | text[] | Seeds `RELATED_TO` in Phase 2. |

### Tier 3 — external authority reconciliation (network, optional, refreshable)

Once a `doi`/`arxiv_id` exists from tier 1, this is nearly free — and `scripts/paperfetch.py`
**already implements DBLP, Unpaywall and arXiv resolvers** that can be reused directly.

| Field | Source | Notes |
|---|---|---|
| `canonical_doi`, `canonical_venue`, `canonical_authors` | Crossref / DBLP | Authoritative correction of tier-1 guesses. |
| `author_orcids` | Crossref / ORCID | The principled fix for author disambiguation — the other open `⏳` item in `PROGRESS.md`. Beats any amount of string normalization in `graph.norm_name`. |
| `citation_count`, `reference_dois` | OpenAlex / Semantic Scholar | Turns `CITES` from parsed strings into resolved edges. |
| `oa_status`, `best_oa_url` | Unpaywall | Records where an open copy lives, so future harvest rounds skip what is already resolved. |
| `venue_rank` | CORE / CCF | Optional ranking signal. |
| `authority_checked_at` | — | These fields go stale; the rest do not. Must be timestamped separately. |

---

## 5. Schema changes

Keep the wide, hot, one-per-document scalars on `documents`; move anything repeating or optional
into satellite tables. This matches the existing split between `documents` and `doc_enrichment`.

```sql
-- Tier 0/1 scalars: additive ALTERs, in the ADD COLUMN IF NOT EXISTS style db.py already uses.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS has_text_layer BOOLEAN;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS chars_per_page DOUBLE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS pdf_producer TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS venue_type TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS language TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS imported_at TIMESTAMP;
-- … etc.

-- OCR cache. Keyed by content hash + model + dpi, so it survives --reset and never re-pays.
CREATE TABLE IF NOT EXISTS doc_ocr (
    doc_id TEXT, page INTEGER, backend TEXT, model TEXT, dpi INTEGER,
    text TEXT, markdown TEXT,
    ocr_status TEXT, ocr_confidence DOUBLE, repetition_ratio DOUBLE,
    created_at TIMESTAMP,
    PRIMARY KEY (doc_id, page, model, dpi)
);

-- One row per author: fixes the author graph properly (position, affiliation, ORCID).
CREATE TABLE IF NOT EXISTS doc_contributors (
    doc_id TEXT, position INTEGER, name TEXT, name_norm TEXT,
    affiliation TEXT, email TEXT, orcid TEXT, is_corresponding BOOLEAN,
    PRIMARY KEY (doc_id, position)
);

-- Typed external identifiers (doi / arxiv / isbn / issn / url / handle).
CREATE TABLE IF NOT EXISTS doc_identifiers (
    doc_id TEXT, id_type TEXT, id_value TEXT,
    PRIMARY KEY (doc_id, id_type, id_value)
);

-- Bibliographic detail that is mostly NULL and shouldn't widen `documents`.
CREATE TABLE IF NOT EXISTS doc_bibliography (
    doc_id TEXT PRIMARY KEY,
    subtitle TEXT, volume TEXT, issue TEXT, page_range TEXT,
    publisher TEXT, series TEXT, edition TEXT,
    publication_date DATE, license TEXT, copyright_holder TEXT,
    keywords_declared TEXT[], funding TEXT[], grant_ids TEXT[], artifact_links TEXT[]
);

-- Structure profile + outline.
CREATE TABLE IF NOT EXISTS doc_structure (
    doc_id TEXT PRIMARY KEY,
    section_headings TEXT[], toc JSON,
    n_figures INTEGER, n_tables INTEGER, n_equations INTEGER,
    n_algorithms INTEGER, n_references INTEGER
);

-- Parsed references: the Phase 2 CITES substrate.
CREATE TABLE IF NOT EXISTS doc_references (
    doc_id TEXT, ordinal INTEGER, raw TEXT,
    title TEXT, authors TEXT[], year INTEGER, venue TEXT, doi TEXT,
    matched_doc_id TEXT,          -- resolved into the library, when we can
    PRIMARY KEY (doc_id, ordinal)
);

-- Per-field provenance. The keystone: makes every value auditable and selectively refreshable.
CREATE TABLE IF NOT EXISTS field_provenance (
    doc_id TEXT, field TEXT,
    source TEXT,          -- filesystem | pdf_info | xmp | text_heuristic | ocr_vlm | llm | crossref | dblp | unpaywall | manual
    confidence DOUBLE, extracted_at TIMESTAMP,
    PRIMARY KEY (doc_id, field, source)
);
```

`field_provenance` is the piece I would argue hardest for. Without it, a corpus assembled from six
extraction sources becomes unauditable: you cannot tell whether a venue came from Crossref or from a
model's guess, you cannot re-run only the weak fields, and a bad LLM pass silently overwrites good
data. With it, the merge rule is explicit and re-runnable:

```
manual  >  crossref/dblp  >  xmp/pdf_info  >  ocr_vlm  >  llm  >  text_heuristic  >  filename
```

A higher-precedence source overwrites; an equal one only fills NULLs. This is a generalization of
what `enrich.promote_cached()` already does informally with `COALESCE`.

---

## 6. Phasing

Ordered by value per unit of work, cheapest first. Each phase is independently useful.

| Phase | Work | Cost | Payoff |
|---|---|---|---|
| **A** | ✅ **Done** 2026-08-14. Tier 0 container metadata + `has_text_layer`/`chars_per_page`; populate `abstract` from the existing text layer; `field_provenance` table + merge rule | 4.9 min of compute, no model, no GPU | Fixes the 100%-empty abstract column, materializes the OCR trigger, makes everything after it auditable. Results in §8. |
| **B** | ✅ **Done** 2026-08-17. `ocr.py` + `ocr_worker.py` + `doc_ocr` cache + `mlx-paddleocr-vl` backend; `--only-empty --low-density`, then runs over the `text_garbled` sets found by §3.1 and §3.2 | ~1 day + ~9 h of local inference | ~148 invisible documents become searchable, entirely offline. Results in §9. |
| **C** | Front-matter metadata pass over all PDFs (`--all-front-matter`) → `doc_contributors`, `doc_identifiers`, `doc_bibliography` | ~2 days + ~10–20k pages | **The main event.** Attacks 68% missing authors, 82% missing venue, 43% `needs_review`. |
| **D** | Tier 3 reconciliation via the existing `paperfetch.py` resolvers; ORCID-based author merging | ~1 day | Canonical venues, real author identity, `oa_status` for future harvests. |
| **E** | `doc_references` extraction + matching → `CITES` edges | ~2–3 days | Unblocks the Phase 2 roadmap item. |
| **F** | Alternative backends: `mlx-glm-ocr` / `mlx-deepseek-ocr-2` for pages the default fumbles; `unlimited-ocr-vllm` only if the Phase C pass must finish in one sitting | ~1 day | Model-quality insurance without re-plumbing the stage. |

---

## 7. Risks and open questions

- ~~The model may not run locally at all.~~ **Resolved** — measured, §2.3. MLX sidesteps the
  CUDA/`trust_remote_code`/MPS-op problem entirely because `mlx-vlm` implements the architectures
  natively.
- ~~PyMuPDF is AGPL-3.0.~~ **Resolved** — `pypdfium2` replaces it for unrelated reasons (wheels) and
  is permissively licensed.
- ~~Sending page images to the gateway is a data-egress decision.~~ **Resolved** by making the
  default local. Remote backends still need the `internal = TRUE` guard, but nothing depends on it.
- **Repetition degeneration is a documented property of this model class, not an edge case.**
  Unlimited-OCR's card *requires* `no_repeat_ngram_size=35`. Not yet observed with PaddleOCR-VL on
  MLX, but the validation layer stays: output is checked, never trusted.
- **Whole-page recognition is off-label.** Both PaddleOCR-VL and GLM-OCR ship a two-stage
  layout-then-recognize pipeline, and the model card scopes model-only use to element level. It
  worked well on a single-column scan; **multi-column pages are the open question**, and the
  mitigation is already available — `Spotting:` returns `<|LOC_n|>` boxes per line, from which
  column-aware reading order can be reconstructed without a layout model.
- **Cost/time at corpus scale.** At ~5 s/page, Phase B is ~1 hour but Phase C is ~20–25 hours of
  local inference. That is fine for a chunked, resumable overnight job and not fine as one
  foreground run — the stage must checkpoint per page.
- **Do not let markdown reach the embedder.** Store both representations and chunk the plain-text
  one, or retrieval quality will drift as table syntax dilutes the vectors.

### Decisions

1. **Default backend: `mlx-paddleocr-vl`, local.** Settled 2026-08-14.
2. **Rasterizer: `pypdfium2`.** Settled — PyMuPDF does not install on this Python.
3. **Phase A: done**, independently of the OCR decision, as proposed.
4. `internal = TRUE` is excluded from remote backends; irrelevant while the default is local.

Still open: the scope of the Phase C front-matter pass — all ~9,900 PDFs (~25 h), Literature-only,
or start with the 4,239 flagged `needs_review`.

---

## 8. Phase A results (2026-08-14)

`search/metadata.py`, exposed as `search.cli metadata [--redo|--status|--limit N]`. Full corpus
backfill: **10,011 documents in 4.9 minutes**, no model, no network.

| Field | Before | After |
|---|---|---|
| `abstract` | 0 | **6,124 (61.2%)** |
| `pdf_created` | — | 5,853 (58.5%) |
| `pdf_producer` | — | 7,179 (71.7%) |
| `xmp_title` | — | 1,884 (18.8%) |
| `language` | — | 2,273 (22.7%) |
| `field_provenance` rows | 0 | 162,364 |

Three things worth carrying forward:

- **Abstracts are anchored, not guessed.** The extractor requires the word "Abstract" to open a line
  (tolerating the letter-spaced `A b s t r a c t` some typesetters emit) and stops at the next
  structural heading. Spot-checked on 25 random PDFs: 23 real abstracts, no prose false positives.
  The 38.8% without one are, as far as the anchor can tell, genuinely abstract-free — which keeps
  `abstract IS NULL` meaning "none found" rather than "some prose".
- **The year gap is mostly closeable for free.** Of 2,361 documents with no `year`, **1,714 now have
  a `pdf_created`**. That is a deterministic backfill waiting to happen, subject to a judgement call
  about whether a PDF creation date may stand in for a publication year (it is the typesetting date
  for a preprint and the scanning date for a scan — `pdf_producer` distinguishes the two cases).
- **OCR is a much smaller job than assumed.** 10 PDFs with no text layer, 8 more thin. Phase B is an
  18-document chore, which is precisely why paying for GPU hardware was never the right move here.
  *(Corrected below: counting only what is missing hid a much larger set of documents whose text
  layer is present and useless.)*

---

## 9. Phase B results (2026-08-14)

Three runs, all on `mlx-paddleocr-vl` at 200 dpi, entirely local.

| Run | Selection | Documents | Pages | Recovered | Wall clock |
|---|---|---|---|---|---|
| B1 | `--only-empty --low-density` | 18 | 769 | 1.97 M chars | 65 min (4.9 s/page) |
| B2 | `--only-empty` (now incl. `text_garbled`) | 99 | 2,759 | 7.17 M chars | ~5.5 h |
| B3 | `--only-empty` (after adding `glued_ratio`, §3.2) | 29 | 2,276 | 6.56 M chars | 159 min (4.2 s/page) |

Cumulative: **146 documents, 5,804 pages, 15.7 M characters, 437 min of inference, zero `error`
pages** (5,471 ok, 72 blank, 87 low-yield, 174 repetition). Afterwards **no PDF in the corpus is
flagged `text_garbled`**: the count fell 33 → 2, and both survivors are markdown (a two-chunk dbdb.io
stub and a notebook that is mostly embedded JSON) — low on prose, but not damaged, and not OCR
candidates. The recovered documents are substantial: Whitehead's *Science and the Modern World* went
from unsearchable to 653 chunks of readable prose, Ullman's textbook to 1,807.

Per-page cost is not a constant of the model, it tracks output length: B1's scans average 2.7 k
chars/page at 4.9 s, B2's born-digital pages 4.2 k at 8.2 s. Estimate OCR runs in characters, not
pages.

Page outcomes in B1: **689 ok, 18 blank, 40 low-yield, 22 repetition, 0 error** after two retry
passes. Notes worth keeping:

- **The repetition guard earns its place.** 22 pages (2.9%) degenerated into loops, exactly as the
  model class's documentation warns. They are recorded as `repetition` rather than silently indexed.
  A retry is deliberately *not* offered for them: at temperature 0 it would reproduce itself, so the
  fix is a different dpi or backend.
- **Metal GPU timeouts are a capacity problem, not a bug.** Dense pages at `max_tokens=6144` tripped
  `kIOGPUCommandBufferCallbackErrorTimeout`. Lowering to 4096, calling `mlx.core.clear_cache()`
  between pages and retrying once cleared all 28 affected pages.
- **The worker protocol needs request IDs.** The first B1 run silently attributed each document's text
  to the *next* document, because the parent did not drain the `done` sentinel before moving on. Page
  text arriving in the wrong document is the kind of corruption no validation guard would catch, so
  requests and responses now carry a `req_id` and stale messages are discarded.
- **OCR pays for itself in metadata, not just retrieval.** Reading the pages revealed that
  `Ramakrishnan et al. - SRQL - Sorted Relational Query Language.pdf` is not that paper at all — it is
  Sorin et al., *A Customized MVA Model for ILP Multiprocessors* (UW-Madison TR #1369, 1998). The 98
  garbled documents in B2 include many whose heuristic titles were derived *from* the garbage
  (`and hN - 23, 254768.pdf`), so retitling after this run is where much of the value lands.
- **Verify the promotion, not just the run.** B2 reported success while its best-recovered document
  was still garbled *in the index*: `prefer_ocr` declined the substitution because it sampled
  different text than the flagging stage did (§3.2). A recovery pipeline needs an end-to-end check —
  read a chunk back out of `chunks` and look at it — because every intermediate counter can be
  healthy while the artefact never lands. That check is what turned up the third defect class.
- **Selection wants a threshold; substitution wants a comparison.** Sharing one sampling function
  between the two stages was not enough to fix the borderline document, and could not be: the flag is
  computed over *chunks* and the indexer works in *pages*, which are different partitions of the same
  text, so any absolute bar keeps a document that sits on it. `prefer_ocr` now asks the only question
  that actually matters — *which of these two texts is better?* — by scoring both on
  `metadata.readability` (function-word share discounted by glue) and requiring a 15% margin. It has
  no line to fall on, and it made the last stubborn document (0.210 own vs 0.313 OCR) resolve itself.
  Displacing good text is not a risk this opens up: every document with a cached OCR is one that was
  deliberately selected, so the comparison is only ever reached for documents already known to be
  damaged (measured: 0 non-candidates hold cached OCR).
