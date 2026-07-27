# Knowledge Sources

A high-level catalog of **every source** feeding this knowledge base — where the
material comes from, how it is pulled in, and its current status. This is the
provenance companion to `README.md` (which describes the *layout* and *tooling*).

> Counts are approximate file counts as of the last inventory and drift as the
> library grows. Regenerate structure with the Python walk in `README.md`
> (*Agent notes → Listing gitignored trees*).

Legend — **Status**: ✅ in corpus · 🔄 in progress · 🧭 planned · ⛔ gated/unavailable

---

## 0. Seed / origin


| Source                           | What                                                                                                                                                                                                            | Status |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| `Semantic Entities Catalog.xlsx` | The seed catalog that kicked off KB coverage — semantic entities cross-referencing Celonis-internal docs, competitor material, and academic papers. Every gap it named was chased down into the sections below. | ✅      |


---

## 1. Academic papers — author & research-group pages

Scraped for open-access PDFs, then run through the pipeline
(**fetch → content-filter → title-dedup → import → index**; see §7). Duplicates
are rejected by normalized-title match against both the search index and the
on-disk `Literature/` corpus.


| Source                                                                                  | Author / group                                                                                                                                                                                                                                                                                                     | Status                   |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------ |
| `vdaalst.com/publications` + `/slides`                                                  | Wil van der Aalst (RWTH / Celonis)                                                                                                                                                                                                                                                                                 | ✅                        |
| `leemans.ch/publications`                                                               | Sander Leemans                                                                                                                                                                                                                                                                                                     | ✅                        |
| `inf.unibz.it/~montali/publications`                                                    | Marco Montali                                                                                                                                                                                                                                                                                                      | ✅                        |
| `inf.unibz.it/~calvanese/publications`                                                  | Diego Calvanese                                                                                                                                                                                                                                                                                                    | ✅                        |
| `polyvyanyy.com/publications.php`                                                       | Artem Polyvyanyy                                                                                                                                                                                                                                                                                                   | ✅                        |
| `cs.columbia.edu/~ewu`                                                                  | Eugene Wu                                                                                                                                                                                                                                                                                                          | ✅                        |
| `sebastiaanvanzelst.com`, `kodu.ut.ee/~dumas`, arXiv, Springer, VLDB, CEUR, RWTH, QUT … | Ad-hoc paper lists (`imports/paper-urls.txt`)                                                                                                                                                                                                                                                                      | ✅                        |
| `cs.cmu.edu/~pavlo/publications.html`                                                   | Andy Pavlo (CMU DB) — 61 PDFs                                                                                                                                                                                                                                                                                      | 🔄                       |
| `hpi.de/.../publications-of-felix-team`                                                 | HPI — Felix Naumann group — 339 PDFs                                                                                                                                                                                                                                                                               | 🔄                       |
| `db.in.tum.de/research/publications`                                                    | TUM Database Systems — 287 PDFs                                                                                                                                                                                                                                                                                    | 🔄                       |
| `utndatasystems.github.io/publications`                                                 | UTN Data Systems — 14 PDFs                                                                                                                                                                                                                                                                                         | 🔄                       |
| `informatik.tu-darmstadt.de/systems/.../publications`                                   | TU Darmstadt Systems — JS template backed by `tubiblio`; no scrapable PDFs                                                                                                                                                                                                                                         | ⛔                        |
| `ir.cwi.nl` (Database Architectures)                                                    | CWI repository — harvested via the SPA's `search/query` API (`filter=affiliation:Database Architectures`, paged via POST `query.from`); 1040 DA pubs → 547 open-access PDFs (types: article/inProceedings/techReport/dissertation/bookChapter/masterThesis/proceedings). Real PDF filenames resolved per pub page. | 🔄                       |
| `research.tue.nl` Pure — Dirk Fahland                                                   | TU/e research portal                                                                                                                                                                                                                                                                                               | ⛔ 403; PDFs gated        |
| `research.tue.nl` Pure — Boudewijn van Dongen                                           | TU/e research portal                                                                                                                                                                                                                                                                                               | ⛔ 403; PDFs gated        |
| `researchgate.net/profile/Mathias-Weske`                                                | ResearchGate                                                                                                                                                                                                                                                                                                       | ⛔ 403; blocks automation |


---

## 2. Conference proceedings

Harvested into `Literature/Proceedings/<CONF YEAR>/`. Open-access reality varies
sharply by venue.

**Already in corpus** (populated from author-page imports):
BPM 2019, 2020, 2023, 2024, 2025 · CAISE 2020 · ICPM 2024.

**Scope for this pass** — recent ~5 years (2021–2025) of the five requested venues,
plus a curated award-paper set:


| Venue                        | Open access?                                    | Plan                                | Status |
| ---------------------------- | ----------------------------------------------- | ----------------------------------- | ------ |
| **PVLDB** (`vldb.org/pvldb`) | ✅ fully open (`volNN/p*.pdf`)                   | Harvest vols 14–18 (2021–2025)      | 🔄     |
| **SIGMOD**                   | ⛔ ACM DL paywall                                | Author-page + award coverage        | 🧭     |
| **BPM**                      | ⛔ Springer LNCS/LNBIP (workshops open via CEUR) | Extend author-page coverage; awards | 🧭     |
| **ICPM**                     | ⛔ IEEE (workshops open via CEUR)                | Extend author-page coverage; awards | 🧭     |
| **CAiSE**                    | ⛔ Springer LNCS                                 | Author-page + award coverage        | 🧭     |


**Award papers** — a curated picking of *best paper* / *test-of-time* winners
across the listed venues, **including ICML & NeurIPS** (learned indexes, MonetDB/X100,
Dynamo, MapReduce/Bigtable/Spanner, node2vec/DeepWalk/XGBoost, BatchNorm, Influence
Functions, Disentangled-Representations, Attention, word2vec, GANs, AlexNet, Random
Features, …), fetched from open versions (arXiv / author / proceedings copies).
List: `imports/award-papers.txt`. 🔄

**Deferred by request** — bulk full proceedings of the large ML venues
(**ICML** via PMLR, **NeurIPS** via papers.nips.cc) are open but enormous
(~50k+ papers); set aside except for their award papers. Likewise the broader
"back to 1995" sweep of SIGMOD/VLDB/KDD/ICDT/ER/Petri Nets.

---

## 3. Tool & competitor documentation

Consolidated one-file-per-source under `Literature/Tool & Competitor Documentation/`
via `scripts/import-docs.py` (SQL dialects & data-platform foundations). ✅

PostgreSQL · GoogleSQL (ZetaSQL) · Apache DataFusion · CedarDB · DuckDB ·
RelationalAI · ClickHouse · Gel · Malloy · Palantir Foundry (Ontology) · Bauplan ·
Snowflake · Databricks · Apache Flink · Oracle (SQL) · SAP HANA (SQL).

> SAP LeanIX docs are a JS SPA and could not be fetched — ⛔.

---

## 4. Company / practitioner blogs

Imported to `Literature/Blogs/<Company>/` via `scripts/import-blogs.py`
(changelogs/release/PR posts dropped). ✅

MotherDuck · DuckDB · RelationalAI · Firebolt · Gel · Malloy · Bauplan ·
Anchor Modeling · CedarDB · Kùzu · TypeDB · **Andy Pavlo (CMU)** 🔄.

---

## 5. Source-system knowledge & specifications


| Collection                  | Sources                                                                    | Status |
| --------------------------- | -------------------------------------------------------------------------- | ------ |
| `Source Systems Knowledge/` | Oracle Fusion interface tables · SAP data-dictionary tables                | ✅      |
| `Specifications/`           | OMG (BPMN/CMMN/DMN) · W3C (RDF/OWL) · OntoUML · BFO · Semantic Arts (gist) | ✅      |


---

## 6. YouTube video transcripts

Fetched via `youtube-transcript-api` + `yt-dlp` into `Transcripts/<Channel>/`
(metadata header + timestamped body), indexed alongside papers. Source list:
`scripts/youtube-sources.txt`; resumable backlog: `imports/youtube-backlog.json`. ✅/🔄

Channels & series harvested include: CMU Database Group · SIGMOD · DSDSD (Dutch
Seminar on Data Systems Design) · Dan Suciu · Ryan O'Donnell · Strange Loop ·
Wil van der Aalst · Sander Leemans · Dirk Fahland · Celonis · plus Stanford
(`PLoROMvodv4r…`) lectures and many title-resolved talks (CIDR, CppCon, JuliaCon,
Process Mining Summer School, …).

---

## 7. Celonis internal & reference


| Source                                   | What                                                                                                                                                                                                                          | Status |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| `Literature/Celonis Internal/`           | Curated internal docs (PIG-SL / PQL / Saola / CCMM / EMS 2.0 slide decks & specs). Routed by the internal-marker detector in `scripts/import-downloads.py`; office files (`.docx/.pptx/.xlsx`) treated as internal by suffix. | ✅      |
| `reference/context-model-documentation/` | Gitignored local checkout of the Celonis Context Model wiki (codename `pig-sl`) — reference only.                                                                                                                             | ✅      |


---

## 8. Books, textbooks & standards specs

`Literature/Books/` and `Literature/Reference and Textbooks/` — curated reference
works; `Specifications/OMG/` also holds the OMG DMN 1.5 spec pulled during the
seed-catalog gap-fill. ✅

---

## Ingestion pipeline (how sources become searchable)

```
scrape page → fetch-papers.py (resumable, rate-limited)
            → content-filter (drop short / no-content PDFs)
            → dedup-inbox.py (normalized-title dedup vs index + Literature)
            → import-downloads.py (Author–Title rename, topic classify, byte-dedup,
                                    internal-flag routing)
            → search.cli index (incremental embed + BM25 + graph)
```

Tooling registry lives in `scripts/` (see `README.md` → *Tooling*):
`import-docs.py` (docs), `import-blogs.py` (blogs), `import-youtube.py`
(transcripts), `fetch-papers.py` (paper PDFs), `dedup-inbox.py` (title dedup),
`import-downloads.py` (Inbox importer).

## Known-gated sources (need manual drop into `Inbox/`)

- **TU/e Pure portals** (Fahland, van Dongen) — HTTP 403, PDFs behind portal.
- **ResearchGate** (Weske) — blocks automated access.
- **ACM DL** (SIGMOD, KDD), **IEEE** (ICPM), **Springer LNCS** (BPM, CAiSE, ER,
Petri Nets) — paywalled; rely on author copies / arXiv / CEUR where they exist.
- **SAP LeanIX** docs — JS single-page app.

