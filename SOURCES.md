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
| `cs.stanford.edu/people/jure/pubs/`                                                     | Jure Leskovec (Stanford SNAP) — 328 URLs selected by `scripts/select-jure-pubs.py`, 326 fetched; **308 were already in the library** (content-hash duplicates), so the round netted ~18 documents                                                                                                                    | ✅                        |
| `research.borosolutions.net`                                                             | BORO Solutions / Chris Partridge (4D extensionalist ontology, bCLEARer, 4DSIG & CIH/CPNI papers). The site is **Cloudflare bot-protected (403)**, so `scripts/boro-research.py` harvests the same works through OpenAlex + Unpaywall/arXiv instead, with a topical filter to defeat author homonyms. 128 documents imported, including 57 conference decks (`.ppsx`) | ✅                        |
| `research.tue.nl` Pure — Dirk Fahland                                                   | TU/e research portal                                                                                                                                                                                                                                                                                               | ⛔ 403; PDFs gated        |
| `research.tue.nl` Pure — Boudewijn van Dongen                                           | TU/e research portal                                                                                                                                                                                                                                                                                               | ⛔ 403; PDFs gated        |
| `researchgate.net/profile/Mathias-Weske`                                                | ResearchGate                                                                                                                                                                                                                                                                                                       | ⛔ 403; blocks automation |


---

## 1b. Common OA / preprint lookup backends

Cross-cutting resolvers used by the paper harvesters whenever a venue listing
gives only *metadata* (title / authors / DOI) and no direct PDF. Implemented in
`scripts/paperfetch.py`; registered in `scripts/conference-sources.txt`.

Before spending anything on a paper, a harvester should ask whether the corpus
already holds it: `paperfetch.IndexDedup` loads every indexed title once and
matches on normalised equality, then a 0.93 fuzzy ratio. Where the venue listing
supplies a title up front (DBLP-driven sweeps), the check runs *before* the
download, so a held paper costs nothing; where the title only becomes known by
reading the file, the harvester downloads, checks, then deletes. Skipping this is
expensive and quiet — the SIGMOD 2015–2026 round moved 2.5 GB to add ~54
documents. Its effectiveness depends on the index having real titles, which is
what the LLM enrichment pass supplies.


| Source | URL | Lookup | Used by | Status |
| ------ | --- | ------ | ------- | ------ |
| **arXiv** | https://arxiv.org/ (API `export.arxiv.org/api/query`) | Title search → fuzzy title + author-surname confirm → `arxiv.org/pdf/<id>` | SIGMOD / ICDE harvesters; Luna Dong; rxin/db-readings; ad-hoc `paperfetch.py lookup` | ✅ |
| **Unpaywall** | https://unpaywall.org/ (API `api.unpaywall.org/v2/<doi>`) | DOI → best OA location with `url_for_pdf` (gold / hybrid / bronze / green) | CAIS; ICDE (DOI fallback); Luna Dong; rxin/db-readings; ad-hoc `paperfetch.py lookup` | ✅ |
| **OpenAlex** | https://openalex.org/ (API `api.openalex.org/works`) | Title/author search → `best_oa_location` / `locations[].pdf_url`; also the only backend of these that indexes philosophy and grey literature | temporality-ontology; boro-research; ad-hoc `paperfetch.py lookup` | ✅ |
| **Semantic Scholar** | https://www.semanticscholar.org/product/api (API `api.semanticscholar.org/graph/v1/paper/search`) | Title search → `openAccessPdf`, which often points at an author or repository copy the publisher-centric backends miss | temporality-ontology (last resort) | 🔑 **needs `SEMANTICSCHOLAR_API_KEY`** — the unauthenticated tier 429s every request from this network (measured 2026-08-14: ~150 s of backoff per title, zero results), so the resolver returns `None` immediately when no key is set rather than slowing every harvest down |


Ad-hoc lookup (no harvester run needed):

```bash
scripts/.venv/bin/python scripts/paperfetch.py lookup --title "DeepMapping: Learned Data Mapping"
scripts/.venv/bin/python scripts/paperfetch.py lookup --doi 10.1109/ICDE60146.2024.00008
```

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
| **SIGMOD**                   | ⛔ ACM DL paywall                                | Author-page + award coverage; `sigmod-arxiv.py` covers **2015–2026** (research + industry/demo/tutorial) → arXiv, Unpaywall DOI fallback. Two DBLP layouts: one `conf/sigmod/sigmodYYYY` volume per year to 2022, then PACMMOD research volumes + a `sigmodYYYYc` companion. **Complete and imported:** 2,758 papers → 1,158 open copies, of which **1,001 were already held** by the corpus and only **~54 were new**. Coverage is generational: 87% for 2023 (PACMMOD born OA) vs. 13% for 2015 | ✅     |
| **ICDE**                     | ⛔ IEEE Xplore paywall                           | DBLP (2021–2025) + 2026 HTML → arXiv, Unpaywall DOI fallback (`icde-arxiv.py`) | 🧭     |
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
RelationalAI (docs + templates/guides) · ClickHouse · Gel · Malloy ·
Palantir Foundry (Ontology, Quiver/Insight/Vertex, Automate, Machinery) · Bauplan ·
Snowflake · Databricks (platform docs + **Databricks Labs Ontos**) ·
Apache Flink · Oracle (SQL) · SAP HANA (SQL).

> SAP LeanIX docs are a JS SPA and could not be fetched — ⛔.

> **Two discovery traps, both since fixed (2026-08-14).** Palantir publishes
> `sitemap.xml`, `sitemap-1.xml` and `sitemap-2.xml`, each capped at 5,000
> alphabetically ordered URLs; the first is consumed by `/docs/foundry/api/` and
> the `/docs/jp/` locale mirror, so reading it alone stops at "j" and silently
> hides every later section (Insight, Notepad, Quiver's card pages, Vertex).
> Coverage went 17 → 795 pages once all three are read. And RelationalAI's
> `llms-full.txt` renders each template/guide as an unevaluated Astro tag
> (`<TemplateDetail template="defect_root_cause" />`), so 117 pages of modelling
> content existed only in the server-rendered HTML; they are now a second
> collection file (`RelationalAI Templates & Guides.md`). Lesson: an
> `llms-full`/sitemap export can be *present and complete-looking* while omitting
> whole sections — spot-check a known page before trusting absence of a term.

> **A doc site that is built from a repo should be read from the repo.** Both
> Bitol standards and Ontos publish (or generate) their pages from markdown that
> is already in git, so scraping the site would have bought a second, lossier
> copy of files the garden holds exactly. `import-docs.py`'s `git` method now
> reads an existing `reference/` checkout (`clone_dir`) and, given the site's
> sitemap, resolves each repo file to the **hosted page it renders to** — so the
> provenance marker is the URL a reader would open even though nothing was
> scraped. It also picks up what the site never publishes: the normative JSON
> Schema. For `mike`-versioned sites the resolved version (`…/v3.1.0/…`) is
> rewritten back onto the `latest/` alias, which is the URL that still works
> after the next release.

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
| `Specifications/`           | OMG (BPMN/CMMN/DMN) · W3C (RDF/OWL) · OntoUML · BFO · Semantic Arts (gist) · HQDM / MagmaCore · Industrial Ontologies Foundry · **Bitol** (ODCS v3.1.0, ODPS v1.0.0) | ✅      |


---

## 6. YouTube video transcripts

Fetched via `youtube-transcript-api` + `yt-dlp` into `Transcripts/<Channel>/`
(metadata header + timestamped body), indexed alongside papers. Source list:
`scripts/youtube-sources.txt`; resumable backlog: `imports/youtube-backlog.json`. ✅/🔄
**185 of 927 fetched**; the rest is gated by a hard **~20 transcripts/day** cap on
this egress IP (see `README.md` → *Unfinished harvesting*, and the `YOUTUBE_PROXY_HTTP`
/ Webshare options the harvester accepts).

Channels & series harvested include: CMU Database Group · SIGMOD · DSDSD (Dutch
Seminar on Data Systems Design) · Dan Suciu · Ryan O'Donnell · Strange Loop ·
Wil van der Aalst · Sander Leemans · Dirk Fahland · Celonis · plus Stanford
(`PLoROMvodv4r…`) lectures and many title-resolved talks (CIDR, CppCon, JuliaCon,
Process Mining Summer School, …).

---

## 7. Local reference checkouts (gitignored, own `.git`)


| Source                                   | What                                                                                                                                                                                                                          | Status |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| `Literature/Celonis Internal/`           | Curated internal docs (PIG-SL / PQL / Saola / CCMM / EMS 2.0 slide decks & specs). Routed by the internal-marker detector in `scripts/import-downloads.py`; office files (`.docx/.pptx/.xlsx`) treated as internal by suffix. | ✅      |
| `reference/celonis/`                     | Celonis checkouts — Context Model wiki (`pig-sl`), Studio Platform HQ, PM Solutions, PMI LaTeX, OCDM prototyping env. Reference only.                                                                                          | ✅      |
| `reference/bitol/`                       | ODCS + ODPS standards. Also the *source* of the two `Specifications/Bitol/` collections (§5) — the doc sites are mkdocs builds of these repos.                                                                                 | ✅      |
| `reference/databrickslabs/ontos/`        | Ontos (branch `development`). Also the source of the Ontos collection (§3); the repo's internal churn (`docs/notes/`, `.planning/`, testing plans) is excluded from the import.                                               | ✅      |


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
- **Bot-challenged repositories** — some institutional repositories hold a genuinely
  open PDF behind a JS proof-of-work page or CAPTCHA, answering `HTTP 200` with an
  HTML challenge: `hal.science`, `madoc.bib.uni-mannheim.de`, `repository.hkust.edu.hk`.
  `paperfetch.download_pdf` reports these as `bot challenge (JS/CAPTCHA)`; they need
  a real browser, so treat them as manual drops.

