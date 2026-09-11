# Knowledge Repository — a living, gardened knowledge base

This directory (`~/docs`) is a **personal knowledge repository** maintained as a *living garden*: a
continuously tended collection of research literature, project documentation, and working drafts,
paired with the tooling and agent context needed to keep it organized over time.

The intent is that **any agent session rooted here (`~/docs`) has thorough, first-class access** to
the whole collection — the paper library, the Celonis Context Model documentation, and a drop-zone
for new material — rather than being confined to a single project subfolder.

> *"The art of exploration is to preserve order amid change and to preserve change amid order."*

---

## Layout

```
~/docs/                    <- single git project rooted here (git remote: MichaelMartini-Celonis/obsidian-quartz)
├── README.md              <- you are here (repository intent + agent context)
├── SOURCES.md             <- provenance: every source feeding the corpus
├── REFERENCE.md           <- GENERATED search map of the reference/ checkouts (see below)
├── Inbox/                 <- DROP ZONE: put new papers/documents here to be integrated
├── Outbox/                <- authored artifacts / drafts (e.g. thesis proposals)
├── Literature/            <- the curated paper library (classified + consistently named)
├── Transcripts/           <- YouTube (etc.) video transcripts (a first-class search root)
├── notebooks/             <- Jupyter notebooks pulled out of the library (a first-class search root)
├── db_systems/            <- database-system reference pages (dbdb.io mirror), tag-taxonomy'd (a first-class search root)
├── Personal/              <- gitignored; Drive exports. Meet notes use search/meet.duckdb;
│                              Personal/drive is in the main index (internal=TRUE)
├── Internal/              <- gitignored; Celonis-internal working docs (main index, internal=TRUE)
├── scripts/               <- Python tooling (the Inbox importer, etc.) + its .venv
├── imports/               <- import manifests + library backups
└── reference/             <- gitignored; 33 independent checkouts used only as reference
    ├── celonis/           <- 30 Celonis repos, each with its own .git (pulled separately)
    │                         Context Model, engineering-wide docs, SRE/runbooks, team
    │                         wikis, standards, and the Knowledge Lake service itself
    ├── bitol/             <- Bitol (LF AI & Data) data-contract / data-product standards
    │   ├── open-data-contract-standard/   <- ODCS spec + JSON Schema + examples
    │   └── open-data-product-standard/    <- ODPS spec + JSON Schema + examples
    └── databrickslabs/
        └── ontos/         <- Business Catalog for Unity Catalog (ODCS/ODPS implementation)
```

`Literature/`, `Transcripts/`, `notebooks/`, `db_systems/`, `Internal/`, `Personal/`, the contents of `Inbox/`, `imports/`,
`reference/`, the DuckDB search indexes (`search/*.duckdb`), and `scripts/.venv/` are gitignored (large binaries and
independently-managed checkouts); everything else in `~/docs` is tracked by this project. The gitignored **search index +
`Literature/` corpus** are versioned separately in a companion **Git LFS** repo at `~/docs-data`
(see *Companion data repo* under Tooling).

### `Internal/` and `Personal/` — private material, one main index

Celonis-internal working docs live in `Internal/` (moved out of `Literature/`). My Drive
working files sync into `Personal/drive/`. Both are **gitignored** and both are indexed in
`search/index.duckdb` with `internal=TRUE`. Filter with `--internal-only` / `--external-only`.

Google Meet / Gemini notes stay in `Personal/meet/` and in a **separate** DuckDB
(`search/meet.duckdb`) so recaps do not mix with papers:

```bash
cd ~/docs && scripts/.venv/bin/python scripts/garden-sync.py pull-personal --index
cd ~/docs && scripts/.venv/bin/python scripts/garden-sync.py pull-meet --index
cd ~/docs && scripts/.venv/bin/python -m search.cli search "event handling" --internal-only
cd ~/docs && scripts/.venv/bin/python -m search.cli --db meet search "event handling"
```

Default `search.cli search` returns both internal and external hits. `--external-only` hides
`Internal/` and `Personal/`.

### `Inbox/` — the drop zone
Drop any `.pdf`, `.docx`, `.pptx`, `.epub`, `.md`, `.txt`, `.xlsx`, `.ipynb`, `.bpmn` here
(subfolders are fine). Then run the importer, which infers an `Author - Title` filename, classifies
the file into the right `Literature/` subfolder, and de-duplicates against the existing library:

```bash
cd ~/docs && scripts/.venv/bin/python scripts/import-downloads.py
cd ~/docs && scripts/.venv/bin/python scripts/import-downloads.py --only panikzettel
```

The second form imports **one Inbox subfolder** and leaves the rest of the drop zone alone, which is
what a harvester run wants: it writes into `Inbox/<source>/`, and filing its output should not also
sweep in whatever else is sitting in the Inbox waiting to be looked at.

This Inbox exists specifically so material never has to be pulled from `~/Downloads` (which is
subject to path-access restrictions — see *Agent notes* below).

### `Outbox/` — authored artifacts
Original work produced in this repository (as opposed to imported source material). Currently holds
`Outbox/thesis/` — the agent-in-the-loop thesis proposals and drafts.

### `notebooks/` — Jupyter notebooks
Standalone `.ipynb` notebooks collected out of the library into their own top-level folder (mirroring
`Transcripts/`). It is a **first-class search root**: notebooks are indexed under their own
`Notebooks` topic (not as library "Books"). Re-index with
`scripts/.venv/bin/python -m search.cli index --roots notebooks`. (Authored notebooks that are part
of an `Outbox/` artifact bundle stay with their bundle and are indexed via the `outbox` root.)

### `db_systems/` — database-system reference pages (dbdb.io)
A mirror of the CMU [Database of Databases (dbdb.io)](https://dbdb.io) — one markdown page per
system under `db_systems/dbdb/<slug>.md`, generated by `scripts/dbdb-systems.py`. Each page carries
**YAML front-matter of tags** (data model, storage model, concurrency control, query interface, …
plus project type, license, OS, written-in, country and derived-from relationships), a readable
**categorization table**, and the system's prose (history + every feature section). It is a
**first-class search root** (indexed under the `DB Systems/dbdb` topic), so the ~1,200 systems and
their tags are queryable alongside the papers. Re-index with
`scripts/.venv/bin/python -m search.cli index --roots db_systems`.

#### Database-systems tag taxonomy (dbdb.io-aligned)
The tags above come from a **controlled vocabulary aligned to the dbdb.io categorization**, derived
from its Django fixtures ([`cmu-db/dbdb.io/data/fixtures`](https://github.com/cmu-db/dbdb.io/tree/master/data/fixtures)):
**24 technical features** in four categories (Data & Storage, Query Processing, Transactions &
Recovery, Distributed Architecture) and **7 metadata attributes** (Project Type, License, Operating
System, Programming Language, Governing Foundation, …), each drawing from fixed option lists. This
taxonomy is the vocabulary used to tag/organize **database systems and database papers** consistently.
It lives in two forms, both regenerated by `scripts/dbdb-systems.py taxonomy`:

- `scripts/dbdb-taxonomy.json` — machine-readable controlled vocabulary (features by category with
  their option slugs/values, and attributes with their options).
- `db_systems/dbdb/_taxonomy.md` — the same taxonomy as human-readable, indexed reference.

### `Literature/` — the curated library
The main research collection, organized into topic folders. Key top-level areas:
`Process Mining/` (with subfolders like `Object-centric/`, `Discovery/`, `Conformance Checking/`,
`Event Log extraction/`, `Architecture/`, `AI/` …), `Process Modeling/`, `Process Querying/`,
`Proceedings/`, `Engineering/`, `Time Series/` (the time-series data-mining literature —
representation and indexing, motifs and discords, anomaly detection, forecasting, imputation and
counterfactual estimation), and `Inbox/` (unclassified fallback inside the library).

Naming convention: `Author et al. - Title.pdf`.

Beyond the research corpus, the library also holds **non-research tooling** material —
company/tool blog posts under `Blogs/<Company>/`, third-party product documentation under
`Tool & Competitor Documentation/<Company>/` (SQL dialects and data-platform foundations),
**source-system knowledge** under `Source Systems Knowledge/<Company>/` (ERP/source-system table
and schema references — SAP data-dictionary tables, Oracle Fusion interface tables, and the
**Jira Data Center** database schema, data model and data-pipeline export schema),
**specifications** under `Specifications/<Org>/` (standards & ontologies — e.g. OMG BPMN/CMMN/DMN,
W3C RDF & OWL, OntoUML, BFO, gist, IDSA, **Apache Ossie**, **OKF**), the **systems papers** behind the
open data stack under `Data Platforms/Apache/`, and **analyst reports** under `Analyst Reports/<Firm>/`
(industry-analyst market assessments — Gartner Magic Quadrants, Critical Capabilities and Market
Guides; Everest Group PEAK Matrix; and the Forrester/IDC/HFS/ISG/NelsonHall equivalents the
importer also recognises). These are grouped by company/org so the search engine's
knowledge graph can attach a `Company` node (`search graph --company` lists them) — a vendor's
blogs, dialect docs, source-system tables and specifications collapse onto the same node.
See `scripts/import-blogs.py` and `scripts/import-docs.py`.

#### `Analyst Reports/<Firm>/` — industry-analyst market assessments
Analyst reports are filed by **publisher, not by subject**, and this is the one collection where
that is a deliberate departure from how the rest of `Literature/` works. A *Magic Quadrant for
Process Mining Platforms* covers discovery, conformance checking and architecture in equal measure,
so subject-matter classification matches it on whichever vocabulary appears first on page 1 and
scatters a single firm's output across the library — which is exactly what had happened before this
folder existed. Grouping by firm also gives the knowledge graph a `Company` node per analyst house,
so Gartner's coverage is a single queryable entity.

Naming keeps the library's `Author et al. - Title` prefix (the analysts *are* the authors, and the
graph builds `Author` nodes from it) and appends the year and the firm's document ID:

```
Analyst Reports/Gartner/Srivastava et al. - Magic Quadrant for Process Mining Platforms (2025, G00816659).pdf
Analyst Reports/Everest Group/Everest Group - Process Mining Products PEAK Matrix Assessment 2023 - Focus on Celonis (2023).pdf
```

The year and ID matter because these are **dated market snapshots** — there is a new Magic Quadrant
for the same market most years, and the document ID (`G00…`) is how Gartner itself cites an edition.
Where the same report is held in two renditions (the full PDF export and the shorter "Gartner
Reprint" web version), the second carries a `, reprint` suffix rather than being silently dropped —
the page counts differ, so they are not byte-equivalent duplicates.

New reports route themselves: `CLASSIFICATION_RULES` in `scripts/import-downloads.py` puts the
analyst-firm rules **first**, keyed on publisher fingerprints (imprint lines like `Gartner, Inc.`,
reprint boilerplate, the `- ID G00…` format) rather than topic words, so they cannot capture a
research paper that merely discusses the analyst market.

#### `Specifications/IDSA/` — data spaces (position papers + the normative model)
The [International Data Spaces Association](https://internationaldataspaces.org/publications/papers/)
corpus is the second collection filed by **publisher rather than subject**, and for the same reason:
a position paper on *Semantic Interoperability in Data Spaces* argues ontologies, data models,
governance and usage control at once, so the topic rules would split one standards body across four
folders. It is held in two halves that answer to each other — 19 position/white papers
(`scripts/idsa-papers.py`) and the normative artifacts they resolve to, IDS-RAM 4.0 and the
Dataspace Protocol, which are GitBook sites generated from git and so come in through
`scripts/import-docs.py` (keys `ids-ram`, `dataspace-protocol`) as consolidated markdown.

Filenames carry the **edition**, because the version is the only thing distinguishing several of
them:

```
Specifications/IDSA/IDSA - Semantic Interoperability in Data Spaces (v1.1, 2025-11).pdf
Specifications/IDSA/IDSA - Semantic Interoperability in Data Spaces (2024-04).pdf
Specifications/IDSA/IDSA - Usage Control in the International Data Spaces (v3.0, 2021).pdf
```

That version and date live only in the *listing*, never in the PDF's front matter, which is why the
harvester parses the page rather than the documents — and why it does not use the usual
`paperfetch.IndexDedup` title check to decide what to skip: two editions share a title, so a title
match silently drops the newer one. It compares the exact versioned filename against what is
already held instead.

Why this material is here: it is the standards-body treatment of the problem **Celonis Networks**
addresses — letting independent companies share process outcomes across an organisational boundary
without either side losing control of the data. `Usage Control`, `Governance for Data Space
Instances` and the Dataspace Protocol's contract negotiation are the prior art for Networks'
sharing model, and `Semantic Interoperability` for its common-taxonomy principle. The Networks
design documents themselves are in `Internal/`.

#### `Course Notes/RWTH Aachen Panikzettel/` — student course cheat sheets
The [Panikzettel](https://htwr-aachen.de/panikzettel) ("panic sheets") are student-written
distillations of RWTH Aachen computer-science lectures — a whole course in two to six dense pages,
CC-BY-SA. They are held as a third collection filed by **publisher rather than subject**, for the
now-familiar reason: 36 sheets covering automata, complexity, databases, logic, stochastics,
software engineering and machine learning would scatter across half the library, and two pages of
exam notes classified on their vocabulary alone read as a very thin research paper.

What earns them a place is density. *Berechenbarkeit und Komplexität*, *Formale Systeme, Automaten
und Prozesse*, *Datenbanken und Informationssysteme* and *Mathematische Logik* state the
definitions and theorems the process-mining and database literature here assumes without
restating — and they are short enough to retrieve whole rather than as a chunk.

```
Course Notes/RWTH Aachen Panikzettel/Panikzettel - Datenbanken und Informationssysteme (2020-07-19).pdf
Course Notes/RWTH Aachen Panikzettel/Panikzettel - Elements of Machine Learning and Data Science (EN) (2024-08-01).pdf
```

The filename carries the **revision date** for the same reason the analyst reports carry their
year: these are living documents re-cut as a course changes, and the machine-learning sheet exists
in a German and an English edition that a title alone cannot tell apart. That date comes from the
API rather than from the document, because seven of the sheets are typeset with `\today` and so
print the site's last *build* date (30 July 2026) instead of their own — silently, and precisely on
the sheets that have not been revised in years. Titles are transliterated
(`ä`→`ae`, `ß`→`ss`) before being written, because the importer's slugifier folds by decomposition
and would otherwise turn *Einführung* into *Einfuhrung* — leaving the harvester unable to recognise
its own output on the next run.

#### `Data Platforms/Apache/` — the systems papers behind the open data stack
87 papers across 52 Apache projects, harvested by `scripts/apache-papers.py`. The companion to the
77 Apache doc collections under `Tool & Competitor Documentation/`: a project's manual says how to
use it, its paper says what problem it claims to solve and what it gave up — log-structured storage,
snapshot isolation over object stores, watermarks over out-of-order streams, columnar layout
trade-offs. That is the prior art the Context Model's own storage and event semantics are argued
against, and it is exactly what the manuals leave out. Some entries are **ancestors** rather than
Apache papers (Bigtable behind HBase, Dremel behind Parquet, Pregel behind Giraph, Dapper behind
SkyWalking), because a project's design is unreadable without them and its documentation never
cites them.

This is the fourth collection filed by **provenance rather than subject**, and the first where the
provenance could not be read off the documents. Analyst reports, IDSA papers and the Panikzettel
each print a recognisable cover-page fingerprint; thirty years of VLDB and SIGMOD papers share
none. Classified on vocabulary, all 54 new papers scattered across six process-mining folders on
incidental words — HDFS to `Stochastic Process Mining` because it says "probability", Spark to
`Process Mining/AI` for "machine learning", Druid to `Visual Analytics` for "visualization", Hive
to `Process Querying` for "SQL". Every match is defensible on its own and the result cannot be read
as a body of work. So `COHORT_FOLDERS` in `import-downloads.py` routes on **the `Inbox/` subfolder
the harvester wrote to**, which is the reusable form of what the three publisher rules do by hand:
a harvester that drops its output in its own folder has already answered the question the keyword
rules are guessing at.

#### `Blogs/<Company>/` — vendor and practitioner blogs
Harvested by `scripts/import-blogs.py` from a registry of sources, one markdown file per post.
The shared filter drops the posts a knowledge base gains nothing from — changelogs, release notes,
roadmaps, funding and hiring announcements — which is enough for a focused engineering blog like
CedarDB's or DuckDB's, where nearly every post is substantive.

**Databricks is the case that broke that assumption**, and the fix is worth recording because it
generalises. Its blog is ~3,340 posts (the current site plus a 2013–2023 legacy archive, which is why
a source may now list **several sitemaps**), and only about half is engineering writing; the rest is
customer stories, partner PR, CxO essays and SEO glossary pages like *What is a DNA Sequence?*. Those
cannot be separated by title words: *Diving Into Delta Lake: Unpacking The Transaction Log* and
*Exciting Keynotes at Spark + AI Summit Europe 2019* are indistinguishable to any regex short of one
that also throws away the good posts. But every post **names its own section in a breadcrumb**, which is
the site's own judgement about what the post is, so `BlogSource` grew `category_xpath` /
`drop_category_re` and the source keeps `engineering`, `platform` and `databricks-ai` while dropping
`industries`, `company`, `data-strategy` and `data-ai-foundations`. That one structural test removes
**1,248 of 3,342** posts; a title regex is then only needed for the residue *inside* the kept
sections — conference and certification posts, analyst/partner announcements, and recurring
non-technical series (*Application Spotlight*, the bi-weekly link digest, eBook launches) — taking the
import to **~1,870 posts**. The lesson is the same one the `Analyst Reports/` folder teaches from the
other direction: when a publisher already classifies its own output, use that classification instead
of inferring one from the text.

A source can also outlive its domain. **Kùzu**'s `kuzudb.com` stopped resolving after Kuzu Inc. wound
down, so the registry points at the GitHub Pages mirror
([`kuzudb.github.io/blog`](https://kuzudb.github.io/blog/)) — the posts already in `Literature/` were
for a while the only copy, and an unregistered source is one nobody can re-run or cite.

Two failure modes found while adding these are worth knowing about, because both produce results that
*look* correct:

- **A removed post can soft-404 onto the blog index.** Databricks answers a dead legacy URL with a
  redirect to `/blog`, which parses cleanly and takes its `<h1>` from whichever post is featured that
  day — so the post is silently replaced by a copy of the listing page, filed under someone else's
  title. The importer now refuses a redirect that lands on an **ancestor** path, which is what
  distinguishes this from the routine redirects that must still be followed (adding a trailing slash,
  dropping `.html`, renaming a slug).
- **Typography decides filenames.** `slugify` keeps an ASCII `'` but drops a typographic `’`, so a
  site that changes its quote style re-imports the same post under a second name. The skip-if-held
  check therefore compares on letters and digits only (`dedup_key`), which caught 5 such re-imports
  and does not require renaming the 128 files already spelled either way.

### `reference/` — independent checkouts, and the map that makes them findable
Independent local checkouts of Celonis and upstream repositories under the gitignored
`reference/` folder. Each has its own `.git`, is pulled/updated separately, and is **not** part of
this project or the Quartz site — they only serve as reference context.

The set is **declared in `scripts/reference-repos.json`** and maintained by
`scripts/reference-repos.py`, so adding a repository is a one-line change rather than a remembered
`git clone`:

```bash
scripts/.venv/bin/python scripts/reference-repos.py sync     # clone missing, pull all, regenerate REFERENCE.md
scripts/.venv/bin/python scripts/reference-repos.py status   # branch / commit / dirty state per checkout
```

Clones are made with `--filter=blob:none`, which keeps the full commit graph (so `git log` and
`git pull --ff-only` behave normally) while fetching historical file contents only on demand — on
this set that is ~2 GB instead of ~5 GB. A single checkout still updates with
`git -C ~/docs/reference/<org>/<repo> pull --ff-only`.

**`REFERENCE.md` (repository root) is the generated index.** Because `reference/` is gitignored,
`Glob` and `Grep` return nothing for it and the DuckDB index does not cover it, so an agent has no
way to discover what is on disk. `REFERENCE.md` is the map: every checkout grouped by purpose, what
each one answers, the terms worth grepping for, its top-level directories, and a suggested read
order. Regenerate it with `reference-repos.py index` (it is derived — do not hand-edit).

The groups, and what each is for:

| Group | Checkouts | Reach for it when |
|---|---|---|
| Context Model & semantic layer | `context-model-documentation`, `pm-solutions`, `pmi-latex-collection`, `pm-prototyping-env` | Context Model / `pig-sl`, PI Graph, Perspectives, Object Types, Functions, OCDM prototypes. |
| Engineering-wide documentation | `documentation-engineering-central` (**Engineering Central**), `architecture`, `engineering.celonis.com`, `agentic-sdlc-documentation`, `backstage-resources`, `repo-depot` | SDLC, change management, platform freezes, ADRs, the Roadie/Backstage service catalog, golden-path CI. |
| Operations, SRE & runbooks | `sre-documentation`, `runbooks`, `data-pipeline-runbooks`, `platform-docs` | On-call, incidents, alert remediation, realms/clusters/gateways. |
| Team & stream wikis | `studio-platform-hq`, `studio-platform-documentation`, `saola-wiki`, `celostar-wiki`, `celoai-documentation`, `metadata-platform-docs`, `cpm-engineering-documentation`, `cpm-migration-project` | A question owned by one team — Studio asset locking, the query engine, Celostar, the AI Gateway. |
| Standards & guidelines | `restful-api-guidelines`, `kubernetes-best-practices`, `landing-zone-adrs`, `pne-website` | The normative rule rather than the practice. |
| Knowledge & AI infrastructure | `cloud-knowledge-lake`, `business-knowledge-context`, `quantum-brain`, `wiki-hq` | How Celonis internal knowledge is ingested and served (see *Knowledge Lake* below). |
| Upstream open-source standards | `bitol/open-data-contract-standard`, `bitol/open-data-product-standard`, `databrickslabs/ontos` | ODCS/ODPS and an implementation of them. |

The upstream checkouts in the last row are projects whose documentation is *also* imported into
`Literature/`. They are kept on disk because the markdown-only import drops what a reader of a
standard eventually wants: the JSON Schema history, the validation scripts, the mkdocs build, and
the git history behind a normative change. The Bitol doc sites are `mkdocs` builds of these
checkouts, so `import-docs.py` reads the files directly and cites the hosted page each one renders
to.

### Celonis Knowledge Lake, CeloAssist and DeveloperAssist
The checkouts above are the part of Celonis knowledge that fits on a laptop. Everything else —
Confluence, Jira, Slack, Google Drive, Cortex, `docs.celonis.com`, the Roadie service catalog and
several hundred further GitHub repositories — is indexed by the **Knowledge Lake**
(`celonis/cloud-knowledge-lake`), a Milvus-backed RAG service with hybrid dense + BM25 collections.
Its engineering-facing profile is **DeveloperAssist**.

Four ways in, in decreasing order of usefulness to an agent session rooted here:

| Surface | Where | Use it for |
|---|---|---|
| **Knowledge Lake MCP** | `https://knowledge-lake-develop.mf.celonis.cloud/knowledge-lake/api/knowledge-retrieval/mcp/` | Tools `list_topics`, `search_knowledge`, `chat_completion`, `submit_feedback`, `metamodel_search`. This is the one to wire up. |
| **DeveloperAssist** | Slack `#ask-developer-assist` | A one-off engineering question, no setup. |
| **CeloAssist** | Slack, company-wide | A one-off general internal question. |
| `search_knowledge_lake` | the `studio-mcp` MCP server, already configured here | **Public** Celonis product documentation only — *not* internal knowledge. |

Connecting the MCP server needs a token from
`https://knowledge-lake-develop.mf.celonis.cloud/knowledge-lake/api/auth/login` (Microsoft SSO,
membership of `All_Celonis_Employees`, **24-hour lifetime**), sent as `Authorization: Bearer …`:

```json
{ "mcpServers": { "knowledge-lake": {
    "type": "http",
    "url": "https://knowledge-lake-develop.mf.celonis.cloud/knowledge-lake/api/knowledge-retrieval/mcp/",
    "headers": { "Authorization": "Bearer ${KNOWLEDGE_LAKE_TOKEN}" } } } }
```

Both endpoints answer from this machine without VPN (the login path redirects to SSO; the MCP path
returns `403` until a token is supplied). The token expires daily and is personal, so it belongs in
the client's own secret store — **not** in a file in this repository. Full instructions, the topic
list and the internal/external sharing rules are in the checkout at
`reference/celonis/cloud-knowledge-lake/docs/knowledge-lake-mcp-quick-start.md`; support is
`#knowledge-lake-support`.

Note what this is *not*: the Knowledge Lake serves **chat and retrieval, not embeddings**, the same
limitation the AI Gateway has (`search/llm.py`). It cannot be used to build `search/index.duckdb`;
it is a second corpus to *ask*, alongside the local one.

The traffic runs the other way too.
`reference/celonis/cloud-knowledge-lake/data_pipeline/config/sources/github-markdown/` registers a
documentation repository as an ingestion source in about a dozen lines of YAML —
`context-model-documentation` is already registered that way — so anything worth reading here is
also a candidate for being answerable through DeveloperAssist.

### `scripts/` and `imports/`
`scripts/` holds the Python tooling that maintains this repository (Inbox importer and a few
historical migration helpers), with its virtualenv at `scripts/.venv/`. `imports/` holds import
manifests and library backups (e.g. `Literature-backup-*.zip`).

---

## Tooling (run from `~/docs`)

Python tooling lives in `scripts/` (virtualenv at `scripts/.venv/`):

| Command | Purpose |
|---|---|
| `scripts/.venv/bin/python scripts/import-downloads.py` | Import + classify + rename files dropped in `Inbox/` into `Literature/` (de-duplicates against the library). |
| `scripts/.venv/bin/python scripts/rename-from-metadata.py --folder "<subfolder>" [--apply]` | Rename library files from the **enriched** title and author list in the index, i.e. from what the PDF's own front matter says rather than from the citation the harvester was given. Dry run unless `--apply`; skips a file whose enriched metadata is unusable (no plausible surname, or a title that is still cover-page furniture like `arXiv:2504.01702v1 [econ.EM]` — the signature of a document that has not been enriched yet), reports collisions instead of overwriting, and builds names with `paperfetch.safe_stem` so the result follows the same convention as every import path. Writes `imports/rename-from-metadata.csv`; re-index afterwards to refresh the moved paths. Introduced for the time-series round, where a hand-maintained publication page attributed **97 of 192** files to a venue token and pointed four of its own hyperlinks at a different paper than the title above them. |
| `scripts/.venv/bin/python scripts/import-web-book.py` | Import free online HTML books (e.g. the Google SRE books) into `Literature/` as markdown (`--list` / `--only KEY`). |
| `scripts/.venv/bin/python scripts/import-blogs.py` | Import competitor/tool **blog** posts into `Literature/Blogs/<Company>/` (drops changelogs/release/PR posts; can recurse through sitemap indexes, paginate listing pages, drop by the post's own site section, and read several sitemaps per source). Registry of sources; `--list` / `--only KEY` / `--dry-run`. Includes Google Research, Anthropic, OpenAI, Microsoft Engineering, BAIR, Hugging Face, Meta Engineering, Zalando, Chip Huyen, METR, Martin Fowler, Ole Olesen-Bagneux's Substack, OneWill, and **Michael Stonebraker (CACM)** (`stonebraker-cacm`: real-world Text-to-SQL critique + database decay). |
| `scripts/.venv/bin/python scripts/slack-llm-sources.py all` | Reproduce the primary-source sweep of Slack `#llm-paper-sharing` (June 2023–July 2026): batch-resolve/download 74 distinct papers to `Inbox/slack-llm-papers/` and extract the 38 named technical posts to `Blogs/<Publisher>/`; excludes news, social-only links, videos, product landing pages, and magazine pieces. Subcommands: `papers`, `blogs`, `all`; `--limit` / `--offset` / blog `--dry-run`. |
| `scripts/.venv/bin/python scripts/import-docs.py` | Build curated third-party doc collections (**Tool & Competitor Documentation** for SQL dialects; **Source Systems Knowledge** for ERP/source-system table references — SAP, Oracle Fusion, Jira Data Center; **Specifications** for standards & ontologies) as one consolidated markdown file per source. Discovery via `llms_full` / `sitemap` / `crawl` / `toc` / `pages` / `git` (which can read an existing `reference/` checkout and, given the site's sitemap, cite the hosted page each repo file renders to; where the site publishes no sitemap it derives that URL from the repo path instead, and it can **sparse-clone a single section of a docs monorepo** — `--filter=blob:none` plus non-cone patterns take 2 MB of Microsoft Fabric IQ markdown out of a 3.3 GB repository). Also holds the **77 Apache data-platform collections**, built through the `_asf()` factory that fills in the shared ASF license, host and locale-filter defaults so an entry states only what deviates. `--list` / `--only KEY` / `--dry-run` / `--force`. |
| `scripts/.venv/bin/python scripts/apache-projects.py select\|probe\|roots` | Enumerate the ASF's own project metadata (`projects.apache.org/json/foundation/{projects,podlings}.json`) and probe each candidate's doc site for a sitemap, an `llms.txt` export, `.md` suffix support and a crawlable root — the evidence behind each Apache entry's `method` in `import-docs.py`. Writes `imports/apache-{projects-selected,doc-probe,doc-roots}.csv`. |
| `scripts/.venv/bin/python scripts/dbdb-systems.py all` | Mirror the CMU [dbdb.io](https://dbdb.io) "Database of Databases" into `db_systems/dbdb/*.md` (tag front-matter + prose) **and** derive the dbdb-aligned tag taxonomy (`taxonomy` / `gather` / `scrape`). |
| `scripts/.venv/bin/python scripts/garden-sync.py pull-meet --index` | Export corp Google Meet / Gemini notes + chat transcripts into gitignored `Personal/meet/` (skips recordings). Uses rclone remote `garden-meet`. Indexes `search/meet.duckdb`. |
| `scripts/.venv/bin/python scripts/garden-sync.py pull-personal --index` | Copy My Drive working files (excluding the garden backup, Meet, Colab) into `Personal/drive/` and index them in the main DuckDB as `internal`. Copy/update only — no deletes. |
| `scripts/.venv/bin/python scripts/garden-sync.py {push-outbox,push-notebooks,pull-colab,run-all,link,audit-shared,install-agent}` | Remaining Drive routing: push Outbox/notebooks without `--delete`; pull Colab `.ipynb`; 15-minute LaunchAgent; authenticated Drive URLs (never `rclone link`); metadata-only Shared-with-me audit. |
| `scripts/.venv/bin/python scripts/sync-gdrive.py` | One-way copy of Literature/Internal/Outbox/Inbox/Transcripts/notebooks/db_systems into private My Drive `m.martini/knowledge-garden`. Does **not** copy `Personal/` (avoids a Drive loop). Deletion on Drive is opt-in (`--delete`). |
| `scripts/.venv/bin/python scripts/reference-repos.py sync` | Maintain the gitignored `reference/` checkouts from `scripts/reference-repos.json` and regenerate `REFERENCE.md`, the search map over them (`list` / `clone` / `pull` / `status` / `index` / `sync`; `--only REPO`). |

### Paper harvesters (`scripts/*.py` → `Inbox/`)

A family of source-specific scrapers pull accepted-paper / publication-list PDFs
straight into `Inbox/<source>/` (from where `import-downloads.py` files them into
`Literature/` and the indexer picks them up). They share `scripts/paperfetch.py`
(a resilient PDF downloader, an `IndexDedup` check against `search/index.duckdb`
so already-indexed papers are skipped, and DBLP/Unpaywall/arXiv *metadata→PDF*
resolvers). Each is resumable via a JSON checkpoint and writes a CSV report. The
registry of sources lives in `scripts/conference-sources.txt`.

**Common lookup backends** (not venues — used whenever a listing has no direct PDF):

| Backend | URL | How |
|---|---|---|
| [arXiv](https://arxiv.org/) | title → preprint PDF | `paperfetch.arxiv_pdf` / SIGMOD & ICDE matchers |
| [Unpaywall](https://unpaywall.org/) | DOI → best OA PDF | `paperfetch.unpaywall_pdf` / CAIS & ICDE fallback |

```bash
scripts/.venv/bin/python scripts/paperfetch.py lookup --title "…"
scripts/.venv/bin/python scripts/paperfetch.py lookup --doi 10.…
```

| Command | Source |
|---|---|
| `scripts/.venv/bin/python scripts/cmu-db-group.py all` | CMU Database Group publications (`db.cs.cmu.edu/publications`) — direct self-hosted PDFs. |
| `scripts/.venv/bin/python scripts/cmu-course-papers.py all` | CMU course "papers/" **open Apache autoindex** dirs (e.g. Ailamaki's `~natassa/courses/15-721/papers/`) — classic DB literature; `--url` to add more. |
| `scripts/.venv/bin/python scripts/lunadong-reading-list.py all` | Luna Dong's classic DB reading list (citations only) — best-effort PDF resolution via the CMU page-numbered catalog (`p<page>-<name>.pdf`), DBLP, Unpaywall and arXiv. |
| `scripts/.venv/bin/python scripts/idsa-papers.py all` | [IDSA](https://internationaldataspaces.org/publications/papers/) position & white papers (data spaces, data sovereignty, usage control) — direct PDFs, named by edition, filed under `Specifications/IDSA/`. |
| `scripts/.venv/bin/python scripts/apache-papers.py all` | The **Apache citation cohort** — 87 canonical papers across 52 projects (plus the pre-Apache ancestors their designs assume), resolved arXiv → OpenAlex → Semantic Scholar → Unpaywall and finally through a `MIRRORS` map of *verified* open locations, because OpenAlex reports much of the SIGMOD/SoCC half of this literature as `closed` while a free PDF sits on the author's page. Filed under `Data Platforms/Apache/`; resumable via `Inbox/apache-papers/_apache-papers.json`. |
| `scripts/.venv/bin/python scripts/bauplan-papers.py` | Recent **Bauplan Labs** papers (2025–2026 arXiv: data contracts, GitLake, agent skills, correct-by-design lakehouse, Eudoxia, Zerrow). Filed under `Data Platforms/Bauplan/` via `COHORT_FOLDERS`. **Shelf:** safe agent execution (branch/verify/merge) — not Text-to-SQL accuracy; pair with `gap-agentic-sql.py`. |
| `scripts/.venv/bin/python scripts/slack-llm-sources.py papers` | Primary papers shared in `#llm-paper-sharing` (74 distinct arXiv/OpenReview/NeurIPS/PMLR/ACL/PVLDB items, including canonical paper substitutes for two retired announcement URLs). Fetches arXiv metadata in batches, checks titles against the live index before transfer, follows publisher citation-PDF metadata, and writes a CSV report. |
| `scripts/.venv/bin/python scripts/scholar-authors.py all` | **Matei Zaharia** and **Reynold Xin** (Scholar profiles) plus Snowflake founding technical staff (Dageville, Cruanes, Żukowski via OpenAlex). Patents dropped. Filed under `Data Platforms/{Matei Zaharia,Reynold Xin,Snowflake}/`. |
| `scripts/.venv/bin/python scripts/atlassian-schema.py all` | Atlassian's **per-version Jira database-schema documents** (7, Jira 5.12 → 9.0), read off the attachment links on `developer.atlassian.com/server/jira/platform/database-schema/`. Six are SchemaCrawler text listing all 176 tables with their columns; the newest (9.0) is a 76×81-inch image with no text layer, so each download is probed and its `text_chars` recorded. Filed under `Source Systems Knowledge/Atlassian/` via `COHORT_FOLDERS`. |
| `scripts/.venv/bin/python scripts/panikzettel.py all` | [RWTH Aachen Panikzettel](https://htwr-aachen.de/panikzettel) — 36 student-written course cheat sheets (automata, complexity, databases, logic, stochastics, ML …). The listing renders client-side, so metadata comes from its JSON API (`api.htwr-aachen.de/api/panikzettel/`), which is also the only place the revision date exists. Filed under `Course Notes/RWTH Aachen Panikzettel/`. |
| `scripts/.venv/bin/python scripts/tuberlin-dima.py all` | TU Berlin DIMA group publications (Volker Markl) — paginated TYPO3 list (~15 pages), direct self-hosted PDFs. |
| `scripts/.venv/bin/python scripts/rxin-db-readings.py all` | Reynold Xin's `rxin/db-readings` — in-repo classic-DB PDFs **plus** a best-effort crawl of the linked "External Reading Lists" (Berkeley/Brown/Stanford/MIT/Wisconsin/CMU — a list of lists). |
| `scripts/.venv/bin/python scripts/pvldb-papers.py gather\|download\|all` | **PVLDB** proceedings on [`vldb.org/pvldb/volumes/N`](https://www.vldb.org/pvldb/volumes/19/) (default **vol 19 = VLDB 2026**). Fully open PDFs from the volume page's `__NEXT_DATA__` JSON; front matter skipped. `gather` is the backlog (`Inbox/pvldb-papers/_pvldb-papers.json`). Filed under `Proceedings/PVLDB/` via `COHORT_FOLDERS`. |
| `scripts/.venv/bin/python scripts/cidr-papers.py gather\|download\|all` | **CIDR** proceedings on [`vldb.org/cidrdb`](https://vldb.org/cidrdb/) (2019–2026). Fully open PDFs from each year's `paper-card` listing; seed page is CIDR 2025 *Trampoline-Style Queries for SQL*. `gather` is the backlog (`Inbox/cidr-papers/_cidr-papers.json`). Filed under `Proceedings/CIDR/` via `COHORT_FOLDERS`. |
| `scripts/.venv/bin/python scripts/gap-recursive-sql.py` | Lineage around that CIDR 2025 paper: trampoline/WITH ITERATIVE SQL, semi-naive and magic-sets evaluation, and the **Halloween Problem** (Tandem NonStop SQL, Chamberlin oral history). Filed under `Process Querying/` via `COHORT_FOLDERS`. |
| `scripts/.venv/bin/python scripts/gap-agentic-sql.py` | **Agentic SQL / PQL reliability** cohort — RUBICON (Wenz/Stonebraker), Spider 2.0, DIN/MAC/CHASE/CHESS, schema linking, abstention, SQL HCI classics (Reisner/Smelcer/Taipalus/Miedema). Synthesis in `Outbox/agentic-sql-reliability/`; gap topic `agentic-sql-reliability`. Filed under `Process Mining/AI/` via `COHORT_FOLDERS`. Pair with `import-blogs.py --only stonebraker-cacm` and `bauplan-papers.py` (safe execution shelf). |
| `scripts/.venv/bin/python scripts/sigmod-arxiv.py all` / `icde-arxiv.py` / `cais-acm.py` / `tum-bpm.py` | SIGMOD (arXiv), ICDE 2021–2026 (arXiv + Unpaywall DOI fallback), ACM CAIS (Unpaywall OA), TUM BPM chair (author-version PDFs). |
| `scripts/.venv/bin/python scripts/gap-audit.py <topic>` | Audit the corpus against a topic map (`scripts/gap-topics.json`) and write `imports/gap-audit-<topic>.{md,csv}`. Scores each concept on four axes — how often its probe terms are *mentioned*, how many documents treat it *substantively* (≥8 hits) or are *focused* on it (≥25), and how many holdings name it in their path — and prints the closest thing the library already has, so a "MISSING" verdict is checkable rather than asserted. |
| `scripts/.venv/bin/python scripts/gap-artifact-centric.py [all\|<cohort>]` | The **artifact-centric / declarative** cohort — 80 works in six cohorts (foundations, verification, enactment, declarative-simulation, paradigm-comparison, object-centric-bps) closing the `artifact-centric-simulation` audit. Unlike its siblings it collects **every** open location for a work before giving up (`candidates()` returns a list, not the first hit): OpenAlex and Unpaywall confidently returned `dl.acm.org` 403s for three Hull/Su papers that were sitting as plain PDFs on Su's own page. Beyond the shared resolvers it indexes four self-hosting pages (Reijers, Jianwen Su, van der Aalst, **De Masellis** — the only open copy of a GSM meta-model paper), eight CEUR volumes, and Ulm's DBIS EPrints by search. Filed flat into `Process Modeling/` via `COHORT_FOLDERS`; resumable via `Inbox/gap-artifact-centric/_gap-artifact-centric.json`. |
| `scripts/.venv/bin/python scripts/gap-timeseries.py [keogh\|shah\|gaps\|scholar\|all]` | The **time-series data-mining** cohort — 250 works closing the `timeseries-process-mining` audit, in three passes that are deliberately different in kind. `keogh` scrapes **Eamonn Keogh's six self-hosted pages** (~111 PDFs: DTW and its lower bounds, SAX/iSAX, PAA/APCA, shapelets, the Matrix Profile series I–XXIII) with **no** topical filter, because his petroglyph and manuscript papers convert images *to* time series and mine them with the same primitives. `shah` enumerates **Devavrat Shah's** profile from Scholar rather than his page — which stops at 2018 and so omits mSSA, tspDB and synthetic interventions — filters 443 works to the 67-work time-series subset on title keywords *and* a venue drop-list (patents, haematology journals), and consults his page only as a resolver. `gaps` fetches the curated cohort: the anomaly-benchmark critique, change-point detection, foundation forecasting models, forecast reconciliation, synthetic control and causal panels, the data-series index line, the storage engines, and the **performance spectrum**. `scholar` fetches nothing — it reports, per work on each profile, whether the corpus holds it. Profiles are cached to `imports/scholar-<user>.json` so a blocked run degrades to the last good enumeration. Filed into `Time Series/` via `COHORT_FOLDERS`; resumable via `Inbox/gap-timeseries/_gap-timeseries.json`. |
| `scripts/.venv/bin/python scripts/gap-cohorts.py` / `gap-simulation.py [slides\|gaps\|own]` | One-off harvests that close what an audit found. `gap-simulation.py` covers process simulation: `slides` resolves a reference list, `gaps` a curated cohort of foundational works, `own` scans `vdaalst.com/publications` by keyword instead of by enumerated title. Beyond the shared OA resolvers it indexes three self-hosting archives — his publications page, the **Winter Simulation Conference** proceedings (`informs-sim.org`, 10,477 papers) and **Ward Whitt's** page (452 PDFs) — which is where the DES-methodology and queueing-theory literature actually is. Resumable via `Inbox/gap-simulation/_gap-simulation.json`. |

> ### ⚠️ Unfinished harvesting & indexing (as of 2026-08-31)
>
> **Latest round (2026-08-31) — time-series data mining, and a corpus holding
> both banks of the river with no bridge.** Started from two Google Scholar
> profiles (Eamonn Keogh, Devavrat Shah) and aimed at the Supply Chain /
> Ontology / AI summit's six time-series requirements for the PIG — time series
> as a first-class object type, a `ReferenceStream`, time-bound attributes, one
> query interface over `Inventory(now|yesterday|future)`, distributions as the
> base for simulation, and an `InfluenceLink` carrying `Occurrence_Probability`
> and `Impact_Distribution` (`SOURCES.md` §3e).
>
> The audit (`gap-topics.json` → `timeseries-process-mining`, 46 concepts across
> eight themes) returned **0 MISSING, 12 mention-only, 3 thin, 31 covered** —
> and the shape of that result is the finding. Both halves were strong
> independently: 713 documents mention data-series similarity search, 181
> sketching, 111 the storage engines; 237 concept drift, 161 predictive process
> monitoring, 122 decision mining. What was absent was anything joining them —
> **`event log to time series` matched one document out of 13,050**,
> `synthetic control` one, `latent source model` one, `singular spectrum
> analysis` three. The library could store a numeric series and discover a
> process model and had nothing that turns one into the other.
>
> **197 of 250 works obtained, 7 already held**, 192 filed into
> `Literature/Time Series/` after byte-dedup. Corpus **13,626 documents /
> 945,849 chunks**.
>
> **Re-audited after the round, the verdicts go to 0 / 3 / 4 / 39** — eleven
> concepts move up, `synthetic control` from 1 mention and no holdings to **26
> mentions and 3 holdings**, latent-source models from 1 to 12, DTW from 74 to
> 151 with 16 holdings, the Matrix Profile to 76 with 21. **Three do not move,
> and they are the three the paywalls hold**: `event log to time series` is
> unchanged at **one mention and zero holdings**, bullwhip at five (all four
> canonical works are in *Management Science*), and the benchmark critique gained
> the paper itself but stays `mention-only`, which is the audit working correctly
> — one holding is not a discussion. The gap is real, now precisely located, and
> **not closable by open access**.
>
> Against the profiles themselves the corpus now holds **110 of Keogh's 413
> works (36 of his 50 most-cited)** and **41 of Shah's 443 (6 of his 50
> most-cited)** — the expected shape, since Shah's most-cited work is networking
> and out of scope while Keogh's most-cited work *is* this subject. Running that
> report twice produced the round's sharpest process lesson: **before enrichment
> it claimed 36/413 for Keogh**, a third of the truth, because it matches on the
> `title` column and a freshly indexed PDF's title is whatever the first text
> block happens to be (`NBER TECHNICAL WORKING PAPER SERIES`). A coverage report
> over unenriched titles measures **extraction quality, not holdings** — and it
> errs in the flattering direction, under-reporting what you already have so the
> next run re-fetches it. Index, enrich, *then* measure.
>
> Three method notes, each a variant of a trap this repository has hit before:
>
> - **A publication page and a profile answer different questions.** Keogh
>   self-hosts ~111 PDFs, so his page *is* his bibliography. Shah's page carries
>   year headings to **2018 and stops** — so mSSA, tspDB, synthetic interventions
>   and causal matrix completion, the exact line this round wanted, are invisible
>   there. Enumeration comes from Scholar and the page is demoted to a resolver.
> - **Titles cannot separate a method paper from an application of it; venues
>   can.** *Forecasting optimal treatments in relapsed/refractory mature T-cell
>   lymphoma* is a forecasting paper by every word in its title. A drop-list on
>   the **venue** (`US Patent`, `Blood`, `British journal of haematology`,
>   `medRxiv`, …) removes 14 of Shah's 443 works cleanly and leaves the 67-work
>   time-series subset — the same conclusion the Databricks breadcrumb filter and
>   the `Analyst Reports/` routing reached, that a publisher's own
>   classification beats one inferred from text.
> - **The §3d duplicate-title trap, arriving from the other direction.** Scholar
>   merges records, so the same work appears as *tspdb: Time series predict db*
>   and *Time Series Predict DB.* Fuzzy-matching those away is what produced a
>   wrong file last round, so nothing is dropped on title similarity here — both
>   are fetched and byte-dedup collapses them. It caught exactly **5**, all of
>   them such pairs.
>
> **The round's most transferable finding is about naming, and it is the §3d
> defect caught one layer later.** A hand-maintained publication page has no
> markup separating a title from the authors and venue around it, so the
> heuristic that reads Keogh's six pages attributed **97 of 192 files to a venue
> token** — `Icdm - …`, `Discovery et al - …`, `Databases - …`. Worse, **four of
> his own hyperlinks point at a different paper than the title above them**:
> `Matrix Profile XIV` links `consensus_Motif_ICDM_Long_version.pdf`, which is
> XV; `Matrix Profile XVII` links `LAMP_Camera_Ready2.pdf`, which is XVIII;
> `Matrix Profile XXVIII` links the DMKD journal version of Matrix Profile I;
> and *Accelerating Time Series Searching with Large Uniform Scaling* links the
> poultry-welfare paper. Eight more entries name a conference version and link
> the journal one, retitled.
>
> Nothing that trusts the citation can see any of this — the download succeeds
> and the filename comes from the *requested* title, which is exactly how §3d
> filed a paper under a title it did not have. What sees it is **enrichment**,
> because it reads the PDF's own front matter and disagrees. So the new
> `rename-from-metadata.py` makes that disagreement actionable, with the rule
> that **the PDF outranks the page it was linked from**: 91 files renamed, 79 on
> the author prefix and 12 where the title was another paper's. The corollary is
> that four *intended* works are not in fact held, and four unintended (but
> in-scope) ones are.
>
> **What is gated is the bridge itself.** 39 works have no open copy and 7 more
> resolve to a URL that refuses the fetch, and the worst-hit cluster is the
> **performance spectrum** — the existing process-mining answer to "turn an event
> log into a signal". Denisov/Fahland's BPM 2018 paper is a `403` at
> `research.tue.nl`; the ICPM 2019 predictive-monitoring paper, Klijn & Fahland
> on batch processing and Maaradji's drift detection have no open copy at all.
> The gap the round set out to close is the one the paywalls defend best.
>
> **Latest round (2026-08-27) — artifact-centric & declarative process models,
> and a gap that turns out to be in the literature rather than the library.**
> The question was whether anyone has simulated a Hull-style artifact-centric or
> Guard-Stage-Milestone model the way BPMN models are simulated. The audit
> (`gap-topics.json` → `artifact-centric-simulation`, 32 concepts across seven
> themes) found the library holding the *citing* literature and almost none of
> the primary sources: `artifact-centric` read covered on 196 documents while
> the GSM meta-model papers themselves were absent, because the idea had been
> absorbed through the verification and process-mining papers that cite it.
> **47 of 80 works obtained, 15 already held**, filed flat into
> `Process Modeling/` (`SOURCES.md` §3d). Corpus **13,434 documents / 929,539
> chunks**.
>
> **The finding is a negative one, and it survived the acquisition.** After the
> round, `simulation of artifact-centric`, `artifact-centric simulation`,
> `simulating GSM` and `GSM simulation` still match **zero documents out of
> 13,434**. That is no longer a statement about the library:
>
> - The artifact-centric community answered "what will this model do" with
>   **model checking**, not simulation — exhaustive rather than sampled,
>   qualitative rather than quantitative, undecidable without restrictions. That
>   half is now strong (Belardinelli/Lomuscio/Patrizi on GSM, Solomakhin et al.
>   on GSM-as-DCDS, Hariri et al. on relational artifacts).
> - What the declarative side calls "simulation" is **constraint-based log
>   generation** — sampling traces that satisfy the constraints, via automata
>   (Di Ciccio et al.), Alloy (MuDePS) or SAT/ASP (Chiariello et al.). It
>   produces behaviour, not performance: no distributions, no resources, no
>   queues.
> - The **comparison literature compared the paradigms on humans**, not on
>   engines — understandability, maintainability, hierarchy, testcases. Nobody
>   compared them on analysability.
> - The quantitative question was answered by **changing the formalism**:
>   object-centric Petri nets and data-aware BPMN keep the token game and add
>   objects, so the discrete-event machinery still applies. That is the route
>   *around* declarativeness rather than through it.
>
> The two closest things anyone has done were already held and are worth naming,
> since both stop short of simulation: van Eck's *Guided Interaction Exploration
> and Performance Analysis in Artifact-Centric Process Models* (performance
> measured from a log, not predicted from a model) and Voorberg et al.'s
> *Decision Support for Declarative Artifact-Centric Process Models* (a GSM
> schema mapped to an MDP, which is optimisation rather than what-if).
>
> **A resolver defect this round is worth recording, because it produced a wrong
> file rather than no file.** Fahland et al. published *Declarative versus
> Imperative Process Modeling Languages: The Issue of Understandability* and,
> a year later, *… The Issue of Maintainability*. The titles share a
> 47-character prefix, so they sit at fuzzy ratio 0.91 — over any cutoff loose
> enough to absorb ordinary punctuation drift — and Reijers' publications page,
> which hosts only the first, answered for **both**. Nothing downstream could
> catch it: the download succeeded, and the filename comes from the *requested*
> title, so the library would have gained a paper filed under a title it does
> not have. It surfaced only because both were fetched and `import-downloads.py`
> noticed the two files were byte-identical. `index_match` now requires a
> pure-ratio match to additionally agree on **every word of six characters or
> more**; the exact and containment paths stay exempt, because a page that
> truncates a subtitle legitimately drops words the citation has. The general
> lesson is that a character ratio measures how similar two strings look, and
> academic titles in the same series are engineered to look similar — the
> distinguishing word is one token, and one token is invisible at that scale.
>
> Sixteen works have **no open copy anywhere the resolvers reach**, and they are
> concentrated in exactly the wrong place: Hull's ODBASE 2008 survey, the WS-FM
> 2010 GSM paper, the Damaggio/Hull/Vaculín equivalence result, Bhattacharya et
> al.'s BPM 2007 formal analysis, Barcelona, and the Marin/Hull/Vaculín CMMN
> survey. Three partial substitutes carried the round: **bitsavers** mirrors the
> IBM Systems Journal by volume, which is the only free Nigam & Caswell;
> **IEEE Data Engineering Bulletin** has been free since 1977 but names each
> file after the first author's *given* name (`david.pdf` for Cohn & Hull); and
> the 2011 **IBM technical report** on GSM operational semantics is the
> authoritative statement the paywalled papers refer to for their full rule
> system. De Masellis' page closed the largest single hole — he is a co-author
> on the DEBS 2011 GSM paper and self-hosts it — so the meta-model is now held
> in primary form even though two of its three papers are not.
>
> **Latest round (2026-08-27) — the Jira Data Center database, and three silent
> extraction defects it exposed.** Jira is the source system behind most ticket
> and ITSM process mining, and Atlassian documents its own tables, so the
> `database-*` family, the data-pipeline export schema and the seven per-version
> schema documents are now held under `Source Systems Knowledge/Atlassian/`
> (`SOURCES.md` §5c). Nine documents, **+312 chunks**, corpus **13,386
> documents / 926,491 chunks**, all enriched, and the `Atlassian` company node
> carries all nine. The material earns its place on the change history:
> `changegroup`/`changeitem` and the pipeline's `issue_history.csv` are a Jira
> event log under another name, and the join keys are the part the REST API
> describes only indirectly.
>
> Reading it needed three fixes, and each had been costing content *silently*
> for as long as the corresponding site was in the registry:
>
> - **A page whose wrappers are all build-generated hashes has no content node
>   to find.** Atlassian's developer docs are server-rendered React —
>   `sc-dfRKBO hSAwOa`, `css-1xjox7o`, no `<article>`, no `<main>`, no id — so
>   the class-hinted picker in `_pick_content` matched nothing and fell through
>   to `<body>`, attaching the site header, the whole documentation tree and the
>   footer to every page. `_densest` now descends from `<body>` while the
>   paragraph-character count is unchanged, which finds the wrapper the prose
>   sits in without naming a class the next deploy renames. It fires *only*
>   where the old code took `<body>` wholesale; re-extracting eight pages from
>   PostgreSQL, CouchDB, ClickHouse, DuckDB, Iceberg, Pinot, gist and Oracle
>   changed nothing, byte for byte.
> - **CSS-in-JS puts a stylesheet inside the heading.** Emotion emits a
>   `<style>` next to the component it styles rather than in the head, and while
>   `_emit` skipped those tags, every string this converter reads comes from
>   `text_content()`, which walks *into* them — so the title arrived as
>   `Database schema.css-1afrefi{display:inline-block;…}` and the same rubbish
>   was glued to table cells and paragraphs. `strip_noise` deletes
>   `script`/`style`/`noscript` from the tree up front, which is also the only
>   place that fixes the *title*, read before the body is converted.
> - **`<article class="content-with-sidebars">` was discarded as navigation.**
>   Atlassian's product docs wrap the page body in exactly that, and the chrome
>   filter matched "sidebars" as a substring — so a 15 KB reference page
>   extracted to **16 characters**, its heading and nothing else. This is the
>   third instance of a pattern already documented twice (Sphinx's
>   `wy-nav-content`, Pinot's Tailwind variant tokens), arriving this time
>   through an ordinary semantic class name, so the rule is now structural:
>   `<article>`, `<main>` and `role="main"` are never chrome, because an element
>   cannot be both the article and the furniture around it. A page is also given
>   its title back when its content starts at `##` (Confluence keeps
>   `h1.page-title` outside the `<article>`), which it previously lost.
>
> One thing is *not* fixed and cannot be: **the newest schema document has no
> text layer.** `jira_9.0_database_schema.pdf` is 3 MB of two embedded images
> with zero extractable characters while every older edition is ~80 KB of text,
> and it is the version a reader would reach for. OCR is no help — the page is
> 5449×5858 pt (**76×81 inches**), so rendering it to the OCR stage's 2200 px
> maximum edge puts 8 pt table labels at about 3 px. Jira **8.20** is the newest
> edition whose 176 tables can actually be queried, and `atlassian-schema.py`
> now probes and reports each file's text layer so this is visible at fetch time
> rather than after indexing reports `[empty]`.
>
> **Latest round (2026-08-25) — process simulation: the foundations under the
> process-mining papers.** Started from van der Aalst's 31-10-2025 *Simulation*
> deck and its 26-item reference list, and turned into a gap-closing round on the
> literature that deck argues *against*. The reference list itself was nearly free:
> **10 of the 26** were already held, **11** were fetched, and the **5** that
> resist are recorded in `SOURCES.md` → *Known-gated sources* — three are his
> ExSpect-era work of 1988-91, which predates the PDF archive on his own
> publications page (it begins at the 1992 thesis, `p7.pdf`).
>
> The interesting part was the audit (`gap-audit.py`, topic `process-simulation`).
> The collection held the process-mining side of simulation well and almost none
> of what it rests on: **conceptual modelling was absent outright**, the
> **infinite-server / M/G/∞ model** — the thing the deck's recommendation 6
> actually proposes using — returned zero documents, and Little's law, Kingman's
> heavy-traffic approximation, Lindley's recursion, simulation output analysis,
> V&V and random-variate generation were each a passing mention inside a paper
> about something else. A deck claiming the M/M/1 sojourn-time formula is the
> wrong model for a business process is not checkable against a library that holds
> only the papers citing it.
>
> Closing it needed sources this repository had not used, because the works are
> old, and old means either paywalled or self-hosted. Three archives carried the
> round: the **Winter Simulation Conference** proceedings (`informs-sim.org`, open
> since 1968 — a 10,477-paper title index, and for methodology the WSC paper is
> usually the canonical statement while the journal version is the paywalled one),
> **Ward Whitt's** publication page (452 PDFs, the whole of modern queueing
> theory), and a keyword scan of van der Aalst's own page rather than an
> enumerated title list, which is what turned up his 1995 *Handboek simulatie* —
> the largest single omission, and the text behind everything the deck asserts
> about abstraction level and steady state. Of **100** cohort targets **77** were
> fetched; **107 documents** were imported in total and the index went
> **13,137 → 13,245 documents / 823,239 chunks**. Re-audited at the same
> thresholds, the 40 concepts moved from **2 MISSING / 15 mention-only / 9 thin /
> 14 covered** to **0 / 6 / 7 / 27**.
>
> What is still weak is worth naming, because most of it is not a fetching
> problem. **Simulation *tooling*** — Simul8, AnyLogic, FlexSim, Vensim — has no
> literature to hold: vendors publish manuals, not papers, and the WSC vendor
> track is advertising. **Short-term simulation** and **hybrid DES+SD+ABS** are
> each a section inside works the library now holds rather than a subject anyone
> wrote a paper about, which is arguably the deck's own point about short-term
> simulation. **Resource calendars / multitasking** is the one real acquisition
> gap left (López-Pintado & Dumas, *DKE* 2021, closed). And **Pollaczek–Khinchine,
> PASTA and Lindley's recursion** are textbook material — they are in Kleinrock
> and Wolff, not in any paper an OA resolver can reach.
>
> One methodological caveat, since it changed the answer: the audit measures the
> *words* a concept is named by, and queueing theory does not name itself the way
> a topic map does. Whitt's review of Little's law is titled *A Review of L = W
> and Extensions* and writes the result as `L = λW` throughout, never as "Little's
> law"; Robinson writes "conceptual modeling" where the map said "modelling"; the
> infinite-server probes were unhyphenated while every holding hyphenates. Three
> concepts read *mention only* against holdings that were sitting right there. The
> probe terms in `gap-topics.json` are fixed, but the lesson generalises — a
> MISSING verdict is a hypothesis about the corpus *and* about the vocabulary, and
> the `closest holding` column is what makes the difference visible.
>
> Three things worth recording. **The classics are genuinely walled**: Little
> (1961, 2011), Kingman (1961), Lindley (1952) and Jackson (1963) have no open
> copy anywhere the resolvers reach, and the author mirrors that used to serve
> them are gone; Whitt's own reviews restate each result and are held instead, so
> the concept is covered even though the paper is not. **The importer was filing
> this material badly** and it took the round to notice: Whitt's papers say
> "queues", never "queueing theory" or "stochastic", so ten of them fell through
> every `CLASSIFICATION_RULES` entry into `Literature/Inbox/`, while Robinson's
> conceptual-modelling tutorials were captured by the ontology rule. Two
> rules now sit ahead of the topic rules — queueing theory next to queue mining,
> DES methodology next to the BPS papers that inherit it — deliberately narrow,
> since a marker as broad as "discrete-event simulation" would pull ordinary
> process-mining papers out of their own folders; 29 files were relocated. And
> **six of the fetched PDFs are image-only scans** (295 pages: Nance's history of
> DES programming languages, Whitt's *L = W* review and heavy-traffic survey,
> Massey & Whitt on infinite-server networks), which is why those concepts stayed
> weak until the local OCR stage ran over them.
>
> **Latest round (2026-08-25) — the Databricks blog, indexed.** `import-blogs.py`
> gained the **Databricks** source (**1,863** posts of its ~3,340, filtered by the
> section each post declares — see *`Blogs/<Company>/`*), the **Kùzu** GitHub Pages
> mirror now that `kuzudb.com` is gone, and the **CedarDB / TypeDB** entries that
> `SOURCES.md` documented but the registry had lost (**+16** posts). With
> MotherDuck (+9) and Bauplan (+1) the corpus is **13,137 documents / 814,790
> chunks**, and `Databricks` is the largest `Company` node at **1,865** documents.
> Two importer defects were fixed on the way — a soft-404 that silently
> substitutes the blog index for a removed post, and filenames that depend on
> which apostrophe a site serves; both are described under *`Blogs/<Company>/`*.
>
> Enrichment of the round is **done** — `scripts/enrich-loop.sh` took **1,961**
> documents (the 1,889 new posts plus the IDSA/Networks/Panikzettel leftovers)
> with **0 failures** in ~87 min, and a second pass cleared the **110** that a
> concurrent `gap-audit` run added meanwhile. The enrichment backlog is now
> **empty** and `needs_review` is **0**: every document in the corpus carries LLM
> `title`/`authors`/`keywords`.
>
> **`search/index.duckdb` was 86% empty space — now compacted, 38.5 → 5.9 GiB.**
> The file had grown to **38.4 GiB** against the ~1.7 GB recorded further up this
> page, which is far more than 1,891 markdown files can explain, and the first
> useful step was establishing *what kind* of growth it was. `PRAGMA
> database_size` answers that directly: of **157,576** blocks (256 KiB each) only
> **22,676 were used** — **5.5 GiB of data against 32.9 GiB of free blocks** — and
> `chunks` had **zero** rows orphaned from `documents`. So it was neither runaway
> data nor a leak of dead rows, but a file that never shrank; `CHECKPOINT` cannot
> help, because the WAL was already `0 bytes`.
>
> **Why it grew is worth knowing, because it will happen again.**
> `db.create_search_indexes` **drops and recreates** the HNSW and BM25 indexes on
> every `index` run, and each rebuild writes fresh blocks while freeing the old
> ones. Measured right after compaction, a pass that indexed **2 documents** took
> the file from 5.90 to 7.20 GiB and left **5,114 free blocks** — so the cost is
> roughly **1.2 GiB of permanent high-water mark per index pass**, regardless of
> how little was ingested. Dozens of passes (plus the OCR re-reads, the `.docx`
> table re-index and `retitle`) is exactly how 5.5 GiB of data came to occupy
> 38 GiB.
>
> The remedy is to rewrite the database into a fresh file, which is safe but needs
> **exclusive** access — do not attempt it while another session holds the write
> lock, and verify before swapping:
>
> ```sql
> ATTACH 'search/index.compact.duckdb' AS compact;
> COPY FROM DATABASE index TO compact;   -- ~4 min for this corpus
> ```
>
> Load `vss`/`fts` on the connection first (`search.db.connect` does). The copy
> **preserves the `hnsw_chunks` index and the `fts_main_chunks` schema**, so no
> reindex is needed — but check both, compare every table's row count against the
> original, and run a real `search`, a `graph --company` and a `graph --author`
> query against the new file (via `SEARCH_DB=…`) before swapping. Keep the old
> file until all of that passes. Doing this before the next `package-data.py pack`
> avoids pushing ~33 GiB of nothing into the LFS repo.
>
> **Round of 2026-08-25 — RWTH Panikzettel, complete and indexed.**
> All **36 sheets** of the [Panikzettel](https://htwr-aachen.de/panikzettel)
> collection are fetched, filed under `Course Notes/RWTH Aachen Panikzettel/` and
> indexed (`scripts/panikzettel.py`, `SOURCES.md` §8b) — nothing outstanding. The
> same index pass also cleared the leftover backlog noted below: **103 documents**
> were indexed and 9,727 skipped as unchanged, which finally took in the IDSA
> papers and the Celonis Networks `.docx` set and brings the corpus to
> **11,248 documents / 791,340 chunks**. Their **LLM enrichment** is still
> pending (heuristic titles only; see *Metadata enrichment backlog*), and the
> Panikzettel now join that queue — the index titles them from their own cover
> lines (*"FoSAP-Panikzettel"*, *"DBIS Panikzettel"*), which is accurate but
> terser than the course name in the filename.
>
> **Latest round (2026-08-22) — IDSA data spaces + Celonis Networks, indexed.**
> The IDSA corpus (`SOURCES.md` §5b — 19 position/white papers, IDS-RAM 4.0 and
> the Dataspace Protocol under `Specifications/IDSA/`) and the 7 Networks design
> documents under `Internal/` are imported **and indexed**: the corpus is
> now **11,212 documents / 789,874 chunks**, and the `IDSA` company node carries
> all 21 files.
>
> Indexing them exposed a defect class worth recording, because it had been
> silently costing the collection this repository cares most about. The `.docx`
> reader in `search/extract.py` read `Document.paragraphs`, which by design
> **skips everything inside a `<w:tbl>`** — so every table in every Word document
> was invisible to search. That is not a rounding error here: **65 of 83** `.docx`
> files in `Literature/` contain tables and **~900,000 characters** were being
> dropped, concentrated exactly where internal design documents put their
> substance. `PMI Team Ideas.docx` is a single table and was indexed as its
> 20-character heading; `Networks on PnE Infrastructure - Responsibilities.docx`
> is a 15×4 ownership matrix indexed as its 300-character intro; `Business Rule
> Concept`, `Hierarchical Event Logs in PQL` and `Relayering Master Document`
> each lost ~60%. Like the garbled-text and glued-text classes below, it passed
> every existing check: the documents *were* indexed, with plausible-looking
> prose, and nothing short of asking a question only the table could answer would
> reveal the gap.
>
> The fix walks the body in document order (`_iter_docx_blocks`) so tables land
> where they belong, and renders each row as `header: value` pairs rather than a
> grid — a bare list of cells loses which column a value came from, and "who owns
> the NAT gateway allowlist" is only answerable if `Networks` stays attached to
> `Responsible team`. Two details earned their keep: horizontally merged cells
> repeat once per grid column in python-docx and are collapsed by element
> identity, and **two-column tables are not header+rows** but key/value lists, so
> pairing them produces nonsense (`Author: Collaborators; Jonas Weich: …`) and
> they are emitted as plain rows instead. Since the files themselves never
> changed, the content-hash fast-skip had to be defeated to re-read them —
> `index.reindex_paths` does that, the same remedy `reindex_ocr_documents` uses
> for OCR ("the file did not change, its *extraction* did"). All 65 were
> re-indexed and verified to carry their table text.
>

> **Latest round** — the widened **SIGMOD 2015–2026** harvest ran to completion:
> of its 2,758 papers **1,398 have an open copy** and **1,167 are in hand**
> (the 231 that matched but would not download are almost all `dl.acm.org`
> returning 403). Those, plus the transcripts fetched between IP blocks, took the
> index to **11,090 documents / 760,994 chunks**, and the container-metadata stage
> now covers the whole corpus (**6,851 abstracts**, 61.8%).
>
> **Completed the round before** — index went **9,104 → 9,931 documents / 650,997 chunks**:
> the loose `Inbox/` backlog (**33 files** filed into `Literature/`); the **ICDE
> arXiv harvest** (`icde-arxiv.py`), whose *match* stage had never run against the
> 2,245 gathered papers and now resolves **670 with an open copy** (**623** arXiv +
> **47** Unpaywall-via-DOI, a **30%** hit rate), of which **645 downloaded**,
> imported and indexed; the **PVLDB vols 14–18** sweep — all 1,962 open PDFs
> fetched, but **1,904 were byte-identical to files already in `Literature/`** (they
> had arrived via the earlier bulk URL list, so the stalled
> `imports/pvldb-fetch.log` was a false gap), only **56** were new; and the
> **transcripts** obtainable before the IP ban (**+22**).
> Also **re-imported the two competitor doc collections** (`import-docs.py`):
> Palantir Foundry went **17 → 795 pages** (121 KB → 3.3 MB) once all three of
> its 5,000-URL-capped sitemaps are read rather than only `sitemap.xml`, which is
> exhausted by `/docs/foundry/api/` plus the `/docs/jp/` mirror and so hid the
> Insight, Notepad, Vertex and Quiver card sections entirely; and RelationalAI
> gained a second file (**117** template/guide pages, 2.1 MB) because its
> `llms-full.txt` emits each one as an unrendered `<TemplateDetail …/>` tag. Both
> indexed (10,140 documents / 686,581 chunks). See `SOURCES.md` §3.
> Also completed a **topical gap-closing round on partial
> orders vs. total order** (process mining ↔ databases): the garden already held
> the process-mining side (Leemans/van Zelst/Lu's partial-order survey, Cortado's
> interval-order variants, Mannila's episodes) but almost nothing on the
> database side, so **66 documents** were pulled in across ordered/sequence data
> models (Maier & Vance's *A Call to Order*, SEQ, SRQL, AQuery, SQL-TS, order
> optimization), temporal/interval databases (Allen, temporal alignment, interval
> joins, Timeline Index), stream order semantics (punctuation, out-of-order
> processing, the Dataflow model, SASE+, Cayuga, CER survey), episode mining with
> general partial orders (Tatti/Cule, Achar, Pei's closed partial orders) and its
> total-order baseline (Agrawal & Srikant, SPADE, PrefixSpan),
> distributed-systems classics (Lamport, Mattern) and transaction theory
> (Papadimitriou, Bernstein et al.'s book, ANSI isolation levels, CRDTs). All are
> imported, indexed and LLM-enriched. The **SRQL** tech-report scan had no
> extractable text; it is now OCR'd locally (see `search/README.md` → *OCR for
> scans*) and searchable — which also revealed that the file is **mis-titled**:
> its pages are Sorin et al., *A Customized MVA Model for ILP Multiprocessors*
> (UW-Madison TR #1369, 1998), not Ramakrishnan's SRQL. Casas-Garriga's
> *Summarizing Sequential Data with Closed Partial Orders* (SDM 2005) has no open
> copy; Pei et al.'s closed-partial-order papers cover the same ground.
> Earlier rounds completed **TU Berlin DIMA**,
> **rxin/db-readings**, the **dbdb.io mirror** and the **Luna Dong reading list**
> pass (of 340 citations: 64 downloaded, 262 unresolved).
>
> **A local OCR stage now exists** (`search/ocr.py`, PaddleOCR-VL on MLX — see
> `search/README.md`), and running it exposed a defect class the index had been
> carrying silently: **98 documents whose text layer is dense but not text** —
> glyph names (`/BW/CT/DA`), control codes, or prose with every space dropped,
> from PDFs whose fonts have no usable `ToUnicode` map. They passed every
> length-based quality check while being unfindable by any query, and their
> heuristic titles were derived *from* the garbage (hence entries like
> `and hN - 23, 254768.pdf`). Detection is now a materialized column
> (`text_garbled`); 2,736 pages were re-read locally in ~3.7 h. Retitling these is
> the point of the enrichment pass that follows.
>
> Verifying that this text actually reached the index turned up **two bugs and a
> third defect class**, all now fixed. The bugs came as a pair: the metadata stage
> judged a document by its **first 12 chunks** while the indexer judged the same
> document by its **first 12 pages**, so a file could be flagged as garbled in one
> place and silently declined in the other — which is what happened to Whitehead's
> *Science and the Modern World*, whose opening scored 0.031 against a 0.03 bar and
> so kept its unreadable layer in the index despite 193 OCR'd pages sitting in the
> cache. Both stages now read the same evenly-spread sample (`metadata.spread_sample`).
> The defect class the fix exposed is **whitespace loss**: an extractor that
> recovers every glyph but no word boundaries, so a page arrives as
> `Thesearethewordsusedbyanoutstandingcritic`. It defeats both existing tests —
> enough short words survive to clear the function-word bar, and every character is
> perfectly mappable — yet no phrase query can ever match it. It is measurable as
> the share of letters stranded in runs of ≥20 characters (`metadata.glued_ratio`):
> healthy documents in this corpus sit at **0.003** (p90) and **0.10** (p99), the
> damaged ones at **0.26–0.92**, with no overlap and no front-matter false
> positives (the glue is a whole-document property). At a 0.25 bar this caught
> **28 further documents / 2,276 pages** (6.56 M characters, 159 min), among them
> Ullman's *Principles of Database and Knowledge-base Systems* (654 pp), Beer's
> *Brain of the Firm* and Naumann's *Informationsintegration* — all previously
> indexed as unsearchable mush.
>
> Fixing the substitution properly took one more step, and it is the more useful
> lesson: sharing a sampling function between the flagging stage and the indexer
> still left a document stranded on the threshold, because the flag is computed
> over *chunks* while the indexer works in *pages*. Selection needs a threshold
> ("is this bad enough to OCR?"); **substitution needs a comparison** ("which of
> these two texts is better?"). `prefer_ocr` now scores both candidates on
> `metadata.readability` — function-word share discounted by glue — and takes the
> fresh reading only when it wins by 15%. Cumulatively OCR has recovered
> **146 documents / 5,804 pages / 15.7 M characters** in ~7.3 h of local inference
> with zero errors, and **no PDF in the corpus is flagged garbled any more**.
> Whitehead went from unsearchable to 653 chunks of readable prose, Ullman's
> textbook to 1,807. The last two stragglers were the flag itself being asked the
> wrong question: a dbdb fact sheet and a Malloy post that is mostly a data blob
> scored as unreadable because they *are* mostly not prose. `text_garbled` means
> "re-read the pages", which only a PDF can do, so it is now set for PDFs only —
> the score is still computed everywhere, but markdown cannot be re-read and a low
> score there is a fact about the content, not a defect.
>
> The **SIGMOD arXiv harvester** was widened from 2024–2026 to **2015–2026**
> (2,758 papers, up from 915) by handling the two DBLP proceedings layouts, and
> given the same Unpaywall DOI fallback ICDE has. One lesson is already banked:
> "open access" and "downloadable" are different properties — PACMMOD is gold OA,
> but its PDFs live on `dl.acm.org`, which refuses every automated client
> regardless of user agent. `paperfetch.unpaywall_locations` therefore returns
> *all* OA locations ranked with the known bot-walled publisher hosts last, so a
> repository mirror (`dspace.mit.edu`, `pure.uva.nl`, …) is tried first. Still outstanding:
>
> The SIGMOD round is now **fetched and imported**, and its most useful result is
> not the papers: of the **1,158 open copies** located, **1,001 were already in the
> corpus**, and of the 157 the harvester could not recognise only **4** were new.
> A 2,758-paper sweep across twelve years netted roughly **54 documents**. The rest
> was 2.5 GB of re-downloading, because `sigmod-arxiv.py` and `icde-arxiv.py` were
> the only harvesters that never consulted the index — the seven others build a
> `paperfetch.IndexDedup` and skip what is held. Both now do too, and they do it
> *better* than the siblings: those download first and delete afterwards, whereas a
> DBLP title is known before any transfer, so a held paper now costs nothing at all.
> Note what the residual 153 misses were caused by: the index still holds
> **heuristic junk titles** for those documents, so title matching could not see
> them. Enrichment is what repairs that, which makes the two tasks below
> sequential rather than independent — dedup gets sharper once titles are clean.
>
> - **SIGMOD leftovers** — of the 2,758 papers **1,360 have no open copy** at all
>   and **231 matched but would not download**. Probing them settled what kind of
>   failure they are: **94** are `dl.acm.org` 403s (gold-OA PACMMOD papers with no
>   repository mirror), and most of the rest are repositories that answer a PDF
>   request with **HTTP 200 and a bot challenge** — a JS proof-of-work page
>   (hal.science, madoc.bib.uni-mannheim.de) or a CAPTCHA (repository.hkust.edu.hk).
>   These need a browser, not a smarter hop, so `paperfetch.download_pdf` now names
>   them `bot challenge (JS/CAPTCHA)` instead of the misleading `not a PDF (text/html)`.
>   Coverage is strongly generational — 2023 resolves at **87%** (PACMMOD is born OA)
>   against **13%** for 2015 — so re-running `match` mainly helps as older work is
>   deposited.
> - **ICDE leftovers** — of the 2,245 gathered papers, **1,575 have no open copy**
>   at all (IEEE-only; no arXiv preprint and no OA location via DOI) and **25
>   matched but failed to download** (institutional repositories returning
>   403/504/HTML — HKUST, Griffith, PolyU, SNS). See
>   `Inbox/icde-arxiv/_icde-arxiv-report.csv`; re-running `match` only helps as new
>   preprints appear.
> - **YouTube transcripts** (`scripts/import-youtube.py`) — backlog **927 videos**;
>   **185 done, 3 skipped, 739 pending**. This IP is **rate-limited by YouTube's
>   `timedtext` endpoint**: each run gets ~15–20 videos, then `IpBlocked`. Confirmed
>   that yt-dlp's caption URLs hit the *same* limit (HTTP 429), so a
>   `youtube-transcript-api` → yt-dlp fallback (now implemented) does not defeat the
>   block. What the block responds to is **elapsed time, not pacing**: bursts 25 min
>   apart returned 0/3, but a day later the first attempt succeeded 5/5 and then ran
>   19 more before blocking again — the same ~20-video quota as every prior run, and
>   a further attempt 6 h later got nothing. So the practical rate from this IP is
>   **~20 videos per day**, i.e. ~38 days for the remaining backlog. Three further
>   days confirmed the quota exactly: **+19, +19, +19** on consecutive days, each run
>   ending in `IpBlocked` with no partial credit for slower pacing. At that rate the
>   remaining 739 videos are **~37 days** of daily runs. All fetched transcripts are
>   indexed.
>
>   Since the ban is tied to the egress IP, the harvester now takes a **proxy** —
>   the only remedy the library documents. Set either pair and both the transcript
>   API and the yt-dlp fallback use it:
>
>   ```bash
>   export YOUTUBE_PROXY_HTTP=http://user:pass@host:port      # any http/https/SOCKS proxy
>   export WEBSHARE_PROXY_USERNAME=… WEBSHARE_PROXY_PASSWORD=…  # rotating residential
>   scripts/.venv/bin/python scripts/import-youtube.py run --loop
>   ```
>
>   With nothing set the direct path is unchanged. A datacenter/VPN exit is not
>   worth trying — YouTube blocks those ranges pre-emptively, which is exactly what
>   the library's error message warns about; residential rotation is what works.
> - ~~**Jure Leskovec (Stanford) publications**~~ — **done**. Of the 328 resolved
>   URLs, **326 downloaded** (2 dead links on an old KDD-Cup site) and **308 were
>   content-hash duplicates** of documents already in `Literature/`, so the round
>   netted ~18 new papers. The overlap warning was right; the lesson for the next
>   author-page round is that `fetch-papers.py` dedups only against `Inbox/`, so
>   duplicates are paid for in bandwidth and caught later by
>   `import-downloads.py`. Recording a `source_url` per document (design §4,
>   tier 1) is what would let a future round skip them without downloading.
>   (`fetch-papers.py` still has this gap; the SIGMOD/ICDE matchers no longer do.)
> - **Metadata enrichment backlog** — largely **cleared**: the ~7 h run described
>   below worked the backlog down from 8,336 to **27 of 11,212** documents. What
>   is left is the 2026-08-22 arrivals (the IDSA papers, the Networks documents
>   and a few others), which still carry heuristic titles taken from cover
>   boilerplate — the IDSA PDFs are indexed as *"Position Paper of members of the
>   IDS Association"* and the Networks `.docx` as *"Word Document"*. Only the
>   `title`/`keywords` fields are affected; the text is indexed and retrievable,
>   and the filenames are accurate.
>
>   Finishing it needs the **Celonis AI Gateway**, which was unreachable on the
>   evening of 2026-08-22: two `enrich` attempts sat for 12 and 7 minutes with a
>   **CLOSED** socket to the gateway and ~1 s of CPU, i.e. blocked on a read that
>   never returns. Worth fixing when convenient — `search/llm.py` sets no socket
>   timeout, so an unresponsive gateway hangs the pass indefinitely *while holding
>   the DuckDB write lock*, which blocks indexing and search too. Re-run when the
>   gateway is up (resumable, content-hash cached, ~3.2 s/doc, so 27 documents is
>   ~2 min), then `… -m search.cli graph --build`.
>
>   Do **not** run `search/retitle.py` over `Specifications/IDSA/` — those
>   filenames deliberately carry the edition (`(v1.1, 2025-11)`), which is what
>   distinguishes two same-titled papers and which an LLM-derived title drops.
>
>   Two things had to be fixed before this could run unattended. The model was
>   given **600 tokens** for its JSON reply and emitted it pretty-printed, so any
>   paper with a long author list was **truncated mid-string and discarded whole** —
>   two of the first three documents failed that way. The reply is now requested on
>   a single line with at most 15 authors in 1,024 tokens, and a truncated object is
>   **repaired rather than thrown away**: `llm._close_truncated` keeps the members
>   that completed (the cut almost always lands in the trailing keyword list, long
>   after the title and authors arrived). A member cut mid-write is dropped whole
>   rather than salvaged — half an author list reads as authoritative and is not.
>   Second, a 7-hour job does not survive this machine's reaper, which ended three
>   long runs today alone. Since every document is cached as it completes,
>   **`scripts/enrich-loop.sh`** simply restarts the pass until the backlog is empty,
>   and stops if a pass makes no progress (a real failure, e.g. the gateway being
>   unreachable, rather than a killed process).
> - **Luna Dong leftovers** — the **262 unresolved** citations have no freely
>   downloadable PDF via CMU catalog / DBLP / Unpaywall / arXiv (mostly older
>   ACM/VLDB paywalled classics). Report: `Inbox/lunadong/_lunadong-report.csv`.
>   Re-running `resolve` only helps if new OA copies appear.
> - **rxin/db-readings external lists** — **32 citations** from the linked schools'
>   lists have **no open copy** (`unresolved`) and 2 lists were unreachable; these
>   are best-effort leftovers (see `Inbox/db-readings/_db-readings-report.csv`).
>
> Everything else already downloaded into `Literature/`, `Transcripts/` and
> `db_systems/` **has been imported and indexed** into `search/index.duckdb`
> (including the IDSA, Networks and Panikzettel material, as of the 2026-08-25
> pass); the items above are the outstanding *fetch* (and enrichment) work.

### Companion data repo (`~/docs-data`, Git LFS)

The heavy, binary artifacts — the built DuckDB search index (`search/index.duckdb`, ~1.7 GB) and the
`Literature/` corpus (~2.8 GB) — are gitignored here and instead versioned in a **separate LFS-backed
git repository** so the code + agent skills stay lean and the data can be located/cloned
independently. `scripts/package-data.py` manages it:

```bash
scripts/.venv/bin/python scripts/package-data.py init       # create ~/docs-data (+ git-lfs, .gitattributes)
scripts/.venv/bin/python scripts/package-data.py pack        # checkpoint index, mirror data, write manifest, commit
scripts/.venv/bin/python scripts/package-data.py push        # push (or print GitHub remote-setup instructions)
scripts/.venv/bin/python scripts/package-data.py restore     # on a new machine: place index + Literature back (--link to symlink)
scripts/.venv/bin/python scripts/package-data.py status      # git status + drift vs. the live data
```

The location defaults to a `~/docs-data` sibling (override with `--repo` or `DOCS_DATA_REPO`). At
~4.5 GB total, pushing to GitHub LFS requires paid data packs, and the repo should be **private**.

---

## Agent notes (context for future sessions)

- **Root a session at `~/docs`** to work across the whole repository (Literature, Inbox, Outbox,
  scripts, and the Celonis reference checkouts under `reference/celonis/`).
- **Read `REFERENCE.md` before searching Celonis internals.** It names all 33 reference checkouts,
  what each answers and the terms worth grepping for. Without it the checkouts are invisible:
  `reference/` is gitignored, so `Glob`/`Grep` skip it and it is not in the DuckDB index. Search
  them with `rg` directly, aimed by that file — e.g.
  `rg -i --glob '*.md' 'asset lock' reference/celonis/`. If the answer is not on disk, ask the
  **Knowledge Lake / DeveloperAssist** (see the section above).
- **Listing gitignored/large trees:** `Literature/` and the project's `imports/` are gitignored, so
  the fast `Glob`/`Grep` tools return nothing for them. To enumerate files, use a Python walk, e.g.:
  ```bash
  python3 -c "import os;[print(os.path.join(r,f)) for r,_,fs in os.walk('Literature') for f in fs]"
  ```
  Individual files can still be read directly with the file-read tool.
- **`~/Downloads` path restriction:** an admin policy blocks shell commands whose paths traverse a
  folder named `agent-mining-data-collector-ms-copilot-studio` (a copy lives under `~/Downloads`).
  This is why the **Inbox** drop-zone exists — integrate material through `~/docs/Inbox` instead of
  reaching into Downloads.
- **Naming:** keep the `Author et al. - Title.ext` convention when adding to `Literature/`.
