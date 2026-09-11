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
| `columbia.edu/~ww2040/journal.html` (+ `bookspapers.html`)                               | Ward Whitt (Columbia IEOR) — **452** linked PDFs covering the whole of modern queueing theory (heavy-traffic limits, infinite-server and many-server queues, time-varying arrivals, Erlang A/B/C, fluid models, Little's law). Indexed and matched by title in `scripts/gap-simulation.py`; this is the only *open* route to the results the INFORMS/Cambridge originals sit behind (Little 1961, Kingman 1961, Lindley 1952, Jackson 1963), since Whitt's own surveys restate each one. A handful of links on the page are dead (`LittlePredict081712.pdf`, `PLL_042917.pdf` → 404) | ✅                        |
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
| **PVLDB** (`vldb.org/pvldb`) | ✅ fully open (`volNN/p*.pdf`)                   | Vols 14–18 (2021–2025) already swept. `pvldb-papers.py` harvests by volume (default **vol 19 = VLDB 2026**); Next.js `__NEXT_DATA__` listing. Filed under `Proceedings/PVLDB/` | 🔄     |
| **SIGMOD**                   | ⛔ ACM DL paywall                                | Author-page + award coverage; `sigmod-arxiv.py` covers **2015–2026** (research + industry/demo/tutorial) → arXiv, Unpaywall DOI fallback. Two DBLP layouts: one `conf/sigmod/sigmodYYYY` volume per year to 2022, then PACMMOD research volumes + a `sigmodYYYYc` companion. **Complete and imported:** 2,758 papers → 1,158 open copies, of which **1,001 were already held** by the corpus and only **~54 were new**. Coverage is generational: 87% for 2023 (PACMMOD born OA) vs. 13% for 2015 | ✅     |
| **CIDR** (`vldb.org/cidrdb`) | ✅ fully open (`papers/<year>/*.pdf`)            | `cidr-papers.py` harvests the Skeleton/paper-card site (**2019–2026**). Seed: [Trampoline-Style Queries for SQL](https://vldb.org/cidrdb/2025/trampoline-style-queries-for-sql.html). `gather` writes the backlog (`Inbox/cidr-papers/_cidr-papers.json`); every listing entry has a PDF. Filed under `Proceedings/CIDR/` | 🔄     |
| **Iterative SQL / Halloween / fixpoints** | mixed OA (cidrdb, Tübingen, Jim Gray, Unpaywall) | `gap-recursive-sql.py` — the CIDR 2025 trampoline paper, WITH ITERATIVE, semi-naive/magic-sets evaluation, Tandem NonStop SQL (Halloween), Chamberlin oral history. Filed under `Process Querying/` | 🔄     |
| **Agentic SQL / PQL reliability** | mixed OA (arXiv, Unpaywall, author PDFs) | `gap-agentic-sql.py` — RUBICON (Wenz/Stonebraker), Spider 2.0, DIN/MAC/CHASE/CHESS, SQL HCI classics, abstention/ambiguity. BEAVER/BenchPress/QueryVis deduped if held. Bauplan safe-execution shelf stays in `bauplan-papers.py`. Stonebraker CACM blog via `import-blogs.py` (`stonebraker-cacm`). Synthesis: `Outbox/agentic-sql-reliability/`. Topic map: `gap-topics.json` → `agentic-sql-reliability`. Filed under `Process Mining/AI/`. Known closed OA: Reisner, Smelcer, Borthick | ✅     |
| **ICDE**                     | ⛔ IEEE Xplore paywall                           | DBLP (2021–2025) + 2026 HTML → arXiv, Unpaywall DOI fallback (`icde-arxiv.py`) | 🧭     |
| **BPM**                      | ⛔ Springer LNCS/LNBIP (workshops open via CEUR) | Extend author-page coverage; awards | 🧭     |
| **ICPM**                     | ⛔ IEEE (workshops open via CEUR)                | Extend author-page coverage; awards | 🧭     |
| **CAiSE**                    | ⛔ Springer LNCS                                 | Author-page + award coverage        | 🧭     |
| **WSC** — Winter Simulation Conference (`informs-sim.org`) | ✅ fully open since 1968, self-hosted | Year-index pages (`wscYYpapers.html`) scraped into a **10,477-paper** title index that `scripts/gap-simulation.py` matches against. For simulation *methodology* the WSC paper is usually the canonical statement and the journal version (JORS, *J. Simulation*, *Management Science*) is the paywalled one, which makes this archive the single most productive source for the discrete-event-simulation foundations the process-mining corpus inherits without restating | ✅     |


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
**Microsoft** (Fabric IQ — ontology, Graph/GQL, planning; Fabric Real-Time
Intelligence — eventhouse/KQL databases, eventstreams, Activator; and the
**Kusto Query Language** reference — see §3f) ·
Apache Flink · Oracle (SQL) · SAP HANA (SQL) ·
**Datadog** (Trace Explorer, Trace Queries, trace pipeline/retention, DDSQL, log
management, events).

> Datadog is the reference system the Context Model's event handling is argued
> from, so its *query* surfaces are the part held. Its `ddsql_reference/` tree is
> 2,100+ generated per-dataset schema stubs under `data_directory/`, which the
> source drops so the language reference is not buried.

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

### 3b. The Apache data-platform corpus (77 projects)

The ASF is where most of the open data stack is maintained, so it is held as one
sweep rather than project by project: **77 collections, ~10,300 pages, ~83 MB**
under `Literature/Tool & Competitor Documentation/Apache <Project>/`, registered
through the `_asf()` factory in `import-docs.py` and enumerated from the
foundation's own JSON (`projects.apache.org/json/foundation/projects.json` plus
`podlings.json`, cached in `imports/`). ✅

The pick is the storage, engine, streaming, catalog and visualisation layers the
Context Model competes with or sits on: table formats (**Iceberg**, **Hudi**,
**Paimon**, **XTable**, **Amoro**) · catalogs and governance (**Polaris**,
**Gravitino**, **Atlas**, **Ranger**) · file formats (**Parquet**, **ORC**,
**Avro**, **Arrow**) · query engines (**Spark**, **Flink**, **Calcite**,
**DataFusion**, **Drill**, **Impala**, **Hive**, **Kyuubi**, **Wayang**,
**Gluten**) · OLAP stores (**Druid**, **Pinot**, **Doris**, **Kudu**,
**Kylin**) · operational stores (**Cassandra**, **HBase**, **Phoenix**,
**CouchDB**, **Ignite**, **Geode**, **Derby**, **AsterixDB**, **IoTDB**,
**Kvrocks**) · graph and geo (**TinkerPop**, **AGE**, **HugeGraph**,
**GraphAr**, **Sedona**) · streaming and messaging (**Kafka**, **Pulsar**,
**RocketMQ**, **BookKeeper**, **StreamPipes**, **InLong**, **EventMesh**,
**Celeborn**, **Uniffle**) · orchestration and pipelines (**Airflow**, **Hop**,
**NiFi**, **Gobblin**, **SeaTunnel**, **Beam**, **Livy**, **Zeppelin**) ·
coordination and cluster (**ZooKeeper**, **Ozone**, **YuniKorn**, **Knox**,
**Ambari**, **CloudStack**) · ML and visualisation (**SystemDS**, **ECharts**,
**Superset**, **Texera**, **GeaFlow**, **SkyWalking**).

> **Apache Ossie** (incubating) is filed under `Specifications/` rather than here
> — it is a vendor-neutral **Open Semantic Interchange** format for exchanging
> semantic-layer metadata (metrics, dimensions, joins) between tools, so it
> belongs with ODCS/ODPS and the W3C specs, not with a product manual. It is read
> from `github.com/apache/ossie` with the `git` method, which also captures the
> normative JSON Schema and the converter set the site does not publish; that set
> — Databricks metric views, dbt, GoodData, Honeydew, Snowflake, Polaris — is the
> interoperability claim stated in concrete terms.

Because 77 sites were configured at once, the failure modes became legible in a
way one site at a time never makes them. Four were bugs in the importer, not in
the sites, and each had been **silently** losing content:

- **A content wrapper can be named like navigation.** Sphinx's ReadTheDocs theme
  — the most common Python doc theme there is — puts the page in
  `<div class="wy-nav-content">`, which the chrome filter matched on `nav-` and
  discarded, so AGE, CouchDB and CloudStack imported as "no content extracted"
  while reading perfectly in a browser. The filter now exempts the node the
  picker already chose as content, on the grounds that a wrapper cannot be both.
- **Utility CSS mentions chrome without being chrome.** Tailwind encodes variants
  in the class name, so Pinot's GitBook content column carries
  `layout-wide:no-sidebar:lg:max-xl:pb-20` — a substring match on "sidebar"
  dropped all 398 pages. Chrome is now matched per class *token*, skipping tokens
  that contain `:`/`[`/`(`, which are framework utilities rather than role names.
- **`/docs/` is sometimes just a directory listing.** Derby, AsterixDB, SystemDS
  and Gluten publish no doc site at all: mod_autoindex lists one directory per
  release. A crawl rooted there imports a table of contents of version numbers —
  Derby was 19 "pages" of 11 KB. `autoindex=True` reads the listing and descends
  into the highest release, which also stops the entry rotting at the next one
  (Derby: 667 pages, 1.4 MB).
- **Relative links must resolve against the URL that answered.** The crawler
  normalises away a trailing slash, the server redirects to the directory, and
  resolving against the pre-redirect form lifts every relative link one directory
  too high. Invisible on flat sites; fatal on Derby, whose DITA manuals reach
  their content only through `<frame src="toc.html">` (frames are now followed
  too).

Four more were the sites disagreeing with their own metadata — worth stating
because in each case the sitemap looked healthy:

- **Cassandra's sitemap describes the previous layout.** It lists 4.x paths
  (`getting_started/`, `architecture/snitch`) under `/doc/latest/`, which 5.x
  reorganised; 219 of 230 URLs 404. Crawling `latest` reads the layout the site
  has (11 → 385 pages).
- **ZooKeeper's sitemap describes a layout that does not exist yet** — an
  `admin-ops/…` tree where every URL 404s, while the published manual is still
  the flat `zookeeper*.html` set (1 → 76 pages).
- **Kafka's Hugo rebuild left `/documentation/` an empty redirect stub** and moved
  the manual into a per-release tree holding every release since 0.8. The version
  segment is a code, not a number — `08` is 0.8 and `0100` is 0.10.0, while
  current releases are two digits — so a numeric "highest version" picks 0.10.0.
  Restricting to two digits selects the modern scheme (1 → 80 pages, 2.2 MB).
- **TinkerPop's `/docs/current/` index is script-generated**, so a crawl finds
  nothing to follow; its manual is a handful of enormous single-page books (the
  reference alone ~290 KB of prose), now named explicitly.

> **DolphinScheduler is deliberately absent** — its site is a client-rendered SPA
> that answers every path, including the ones its own sitemap lists, with the same
> 3.6 KB shell *and* an HTTP 404. Nothing can be extracted; its manual is markdown
> in `apache/dolphinscheduler-website` if it is ever wanted.

The general lesson is the one Palantir and RelationalAI already taught in §3, in
a sharper form: **every one of these failures was silent**. A source that reports
"no content extracted", or writes a plausible-looking file of nineteen pages, is
indistinguishable at a glance from a project that is thinly documented. The
byte-per-page ratio is what exposed them — 0.6 KB/page for Derby against 5 KB/page
for a healthy Docusaurus site — so it is worth checking after a bulk run rather
than trusting the source count.

### 3c. The Apache papers — a citation cohort

`scripts/apache-papers.py` — **87 papers across 52 projects**, resolved through
the shared open-access backends and filed in `Literature/Data Platforms/Apache/`.
25 were already in the index, 56 downloaded (of which **54 filed as new**; two
were byte-identical to held IoTDB copies), and 6 have no reachable open copy. ✅

This is enumerated, not scraped: Apache projects publish documentation, and their
papers are at VLDB, SIGMOD, CIDR, NSDI and OSDI under the authors' names with no
per-project listing to crawl. The manual says how to use a system; the paper says
what it gave up — log-structured storage, snapshot isolation over object stores,
watermarks over out-of-order streams, columnar layout trade-offs — which is the
prior art the Context Model's storage and event semantics are argued against, and
exactly what the manuals omit.

Some entries are **ancestors** rather than Apache papers, because a project's
design is unreadable without them and its documentation never cites them:
Bigtable behind HBase, Dremel behind Parquet and Drill, Percolator behind Fluo,
Pregel behind Giraph, Raft behind Ratis, Dapper behind SkyWalking, Mesos and Borg
behind YuniKorn.

**Half the cohort is invisible to the open-access graph.** A first pass resolved
20 of 62 — the verified mirrors ended up supplying **39 of the 56** downloads,
more than arXiv, OpenAlex and Unpaywall combined. OpenAlex reports Spark SQL,
HDFS, YARN, Hive and Storm@Twitter as
`closed` even though a free PDF has sat on an author's university page for
fifteen years — the copy exists, nothing links it to the DOI. So the harvester
keeps a `MIRRORS` map of verified open locations, consulted **last** so a paper
that later becomes properly open is still taken from its canonical home. Three
venue patterns cover most of it: VLDB's proceedings are open at
`vldb.org/pvldb/vol<N>/`, **ACM serves author-selected open articles at
`dl.acm.org/doi/pdf/<doi>` even where the abstract page presents a paywall**, and
USENIX publishes everything. Every URL was checked by fetching it and confirming
a `%PDF` header rather than trusting it to look plausible — a third of the
plausible-looking guesses returned an HTML error page with `HTTP 200`. Expect the
author-page third to rot; a `dl_failed` line in the report means re-verifying
that entry, not that the paper vanished.

Routing needed a new mechanism. The keyword classifier in `import-downloads.py`
scattered all 54 across six process-mining folders on incidental vocabulary —
HDFS to *Stochastic Process Mining* ("probability"), Spark to *Process Mining/AI*
("machine learning"), Druid to *Visual Analytics* ("visualization"), Hive to
*Process Querying* ("SQL"). Each match is defensible alone and the result is
unusable as a body of work. Analyst reports, IDSA and the Panikzettel are grouped
ahead of the topic rules for the same reason, but they can be recognised from
cover-page boilerplate; thirty years of VLDB and SIGMOD papers share none. So
`COHORT_FOLDERS` routes on **the drop-zone subfolder the harvester wrote to** —
provenance from where the file came rather than what is printed on it — which is
the reusable form of what the three publisher rules do by hand.

### 3d. Artifact-centric & declarative process models

`scripts/gap-artifact-centric.py` — **80 works in six cohorts**; 47 obtained, 15
already held, 16 with no open copy, 2 blocked at fetch. Filed in
`Literature/Process Modeling/`. ✅

Assembled to answer one question — *has anyone simulated an artifact-centric or
Guard-Stage-Milestone model the way BPMN models are simulated?* — and the cohort
is shaped by the four different things the field says instead of "yes":
enactment engines (Barcelona, PHILharmonicFlows, DCR), verification (GSM as
interpreted systems, GSM as DCDS, relational artifacts), constraint-based log
generation (Declare/automata, MuDePS/Alloy, SAT and ASP), and the object-centric
turn that keeps the token game by changing the formalism. Auditing each theme
separately is what lets a `MISSING` verdict distinguish a hole in the library
from a hole in the research — and here it was the research: after the round,
`simulation of artifact-centric` and `simulating GSM` still match **zero of
13,434 documents**.

**Filed flat rather than in a subfolder of its own**, which is a deliberate
departure from §3c. The gap audit scores a concept partly on whether a *path*
names it, so a folder called "Artifact-centric and Declarative" would report all
47 papers as holdings of `artifact-centric` and `declarative` regardless of
subject, and destroy the one column that separates a primary source from a paper
that merely cites one.

Three properties of this literature drove the resolver work:

- **"Resolvable" and "downloadable" are different properties.** The sibling
  harvesters stop at the first resolver that answers; OpenAlex and Unpaywall
  answered for three Hull/Su papers with `dl.acm.org` 403s and publisher landing
  pages while plain PDFs sat on Su's own page, which the ladder never reached.
  `candidates()` now returns **every** open location, best first, and the caller
  tries each — override, then metadata backends, then self-hosting archives.
- **A fuzzy title match can return the wrong paper, not just no paper.** See
  `README.md` → *Latest round* for the Fahland Understandability/Maintainability
  collision and the six-character-token guard that fixes it. The failure mode
  is silent by construction: the file downloads, and its name comes from the
  requested title.
- **Author pages are the archive of record here, and each is idiosyncratic.**
  Su's page writes hrefs with a leading tab (`href="\t./2009/ICDT2009.pdf"`),
  which 404s if passed to `urljoin` unstripped. De Masellis' hrefs are relative
  to `/pages/`, so the page URL must keep that segment. His page matters out of
  proportion to its size: he is a co-author on the **DEBS 2011 GSM paper** and
  self-hosts it, making it the only reachable primary statement of the GSM
  meta-model.

Two further open locations that generalise beyond this round:

- **bitsavers** (`bitsavers.trailing-edge.com/pdf/ibm/IBM_Systems_Journal/`)
  mirrors the IBM Systems Journal by volume/issue, one PDF per article named
  after the first author — the only free copy of Nigam & Caswell 2003, which
  IEEE holds closed and the aggregators only have behind bot walls.
- **IEEE Data Engineering Bulletin** (`sites.computer.org/debull/`) has been
  free since 1977 and is absent from Unpaywall, so the direct path is the only
  way in — and it is not guessable, because each file is named after the first
  author's *given* name: Cohn & Hull is `david.pdf`, not `cohn.pdf` or
  `hull.pdf`.

**What is gated, and why it matters more than usual.** The sixteen unreachable
works cluster on the primary sources rather than the periphery: Hull's ODBASE
2008 survey, the WS-FM 2010 GSM paper, the Damaggio/Hull/Vaculín equivalence
result, Bhattacharya et al.'s BPM 2007 formal analysis, Barcelona (ICSOC 2013),
Hull et al. on artifact-centric hubs, and the Marin/Hull/Vaculín CMMN survey —
all Springer LNCS or ACM, all IBM Research work from a period whose author
copies are gone with the `researcher.watson.ibm.com` pages that hosted them
(the surviving `researcher.ibm.com` file directory lists three papers, all from
2016). Two partial substitutes stand in: the **2011 IBM technical report** *A
Formal Introduction to Business Artifacts with GSM Lifecycles* is the
authoritative rule system the paywalled papers refer to and is served from IBM's
object store, and Cohn & Hull's DEBull survey covers the same ground as the
ODBASE one. `re.public.polimi.it` returns 403 to everything, which costs the
E-GSM monitoring paper.

### 3e. Time-series data mining — two author archives and a missing bridge

`scripts/gap-timeseries.py` — **258 works** across three passes (**250**
distinct; the two authors and the curated cohort overlap by 8); **197** fetched,
**192** filed into `Literature/Time Series/`. ✅

Started from two Google Scholar profiles and aimed at an internal requirement.
The Supply Chain / Ontology / AI summit (`Internal/Summit -
Supply Chain, Ontology, AI summit.docx`, the Redwood City summit) asks the PIG
for six things that are all time-series problems and none of which the corpus
had the literature for: **time series held as a first-class object type**
"without helper objects … include forward-looking/planning data"; a
**`ReferenceStream`** primitive of "time-indexed environmental variables and
calendars"; **time-bound attributes**, so every node and link attribute is
time-versioned; a **time-based query interface** standardising
`Inventory(now)`, `Inventory(yesterday)` and `Inventory(future)` "leveraging
different models for projection"; **distributions** derived from data as the
base for simulation; and an **`InfluenceLink`** carrying an
`Occurrence_Probability` and an `Impact_Distribution`. The deck also asks, in
the models discussion, "*can we infer rules from the data? E.g. we can see the
timestamps for different events, and see that people don't do X on sundays*" —
which is motif and seasonality discovery, stated without knowing the field
exists.


| Source | What | How | Status |
| ------ | ---- | --- | ------ |
| `cs.ucr.edu/~eamonn/` | **Eamonn Keogh** (UC Riverside; [profile](https://scholar.google.com/citations?user=slVcOQIAAAAJ)) — **111 self-hosted PDFs** across six hand-maintained pages: dynamic time warping and its lower bounds (`LB_Keogh`, the UCR Suite), the symbolic representations (SAX, iSAX), PAA/APCA dimensionality reduction, segmentation, shapelets, and the **Matrix Profile series I–XXIII** with the motif, discord, chain, snippet and semantic-segmentation primitives built on it | `gap-timeseries.py keogh` → `Inbox/gap-timeseries/` | ✅ 110/111 — the one loss is an arXiv SSL failure |
| `scholar.google.com` + `devavrat.mit.edu` | **Devavrat Shah** (MIT; [profile](https://scholar.google.com/citations?user=3qPiYJoAAAAJ), 443 works, 38,598 citations across them, the top one being OpenFlow at 13,875) — the **67-work time-series subset**: latent-source models, blind regression, iterative collaborative filtering, *Time Series Analysis via Matrix Estimation*, multivariate singular spectrum analysis, **tspDB**, robust synthetic control, synthetic interventions and causal matrix completion | `gap-timeseries.py shah` | ✅ 44/67 |
| curated cohort | **80 works** closing the audit's `mention-only` and `thin` verdicts: the anomaly-detection benchmark critique and evaluation-protocol argument, change-point detection, deep and foundation forecasting models, hierarchical forecast reconciliation, the synthetic-control and causal-panel literature, the data-series index line (ADS, the two *Lernaean Hydra* evaluations), the time-series storage engines (Gorilla, Monarch), and the **performance spectrum** | `gap-timeseries.py gaps` | ✅ 49 fetched, 7 already held |


**Why these two authors together.** They answer the same question from opposite
ends, and the summit needs both halves. Keogh's line answers *what happened and
what is unlike anything else* over an observed series, without labels and
without a model — which is what "what turns red" and "infer rules from the
timestamps" are asking for. Shah's answers *what is missing, what comes next,
and what would have happened otherwise*, and its interesting claim is
**unification**: imputation, forecasting and counterfactual estimation are one
matrix-estimation problem on a page-matrix view of the series, with **tspDB**
arguing the whole thing belongs *inside the database* rather than in a pipeline
beside it. That is the same collapse the summit's three-tense query interface
asks for — `Inventory(yesterday)`, `Inventory(now)` and `Inventory(future)` from
one interface — and the closest thing to prior art for the *Scenario Layer*,
since a scenario overlay is a counterfactual and synthetic control is how that
question is asked elsewhere.

**The finding is asymmetric coverage, and the audit states it in one line.**
Before this round (`imports/gap-audit-timeseries-process-mining.md`, 46 concepts
across 8 themes) the collection held **both banks of the river and no bridge**.
The systems half was strong — 713 documents mention data-series similarity
search, 181 sketching, 111 the storage engines, all inherited from the
Apache/PVLDB/SIGMOD sweeps — and the process-mining half was strong: 237 on
concept drift, 161 on predictive process monitoring, 122 on decision mining.
But **`event log to time series` matched one document out of 13,050**,
`synthetic control` **one**, `latent source model` **one**, and
`singular spectrum analysis` **three**. A corpus can hold the storage engine for
a numeric series and the discovery algorithm for an event sequence and nothing
that turns one into the other.

**After the round the two banks are much stronger and the bridge is exactly
where it was.** Re-audited against the new index (13,626 documents / 945,849
chunks), the verdicts move from **0 MISSING / 12 mention-only / 3 thin / 31
covered** to **0 / 3 / 4 / 39**. Eleven concepts move up, and the ones worth
naming are the ones the summit needs: `synthetic control` goes from **1 mention
and no holdings to 26 mentions and 3 holdings**, nearest-neighbour and
latent-source models from 1 to 12 with 3 holdings, singular spectrum analysis
from 3 to 9, dynamic time warping from 74 to 151 with **16** holdings, and the
Matrix Profile to 76 with **21**. Hierarchical forecast reconciliation, the
UCR/UEA archives, PAA/APCA dimensionality reduction and counterfactual
forecasting all cross into `covered`.

**Measured against the profiles themselves** (`gap-timeseries.py scholar` →
`imports/gap-timeseries-scholar-coverage.csv`), the corpus now holds **110 of
Keogh's 413 works, including 36 of his 50 most-cited**, and **41 of Shah's
443, but only 6 of his 50 most-cited** — the expected shape, since Shah's
most-cited work is networking (OpenFlow, gossip algorithms) and deliberately out
of scope, while Keogh's most-cited work *is* this subject.

That report also produced the round's sharpest methodological lesson, by being
run twice. Before enrichment it claimed **36/413 for Keogh** — a third of the
truth — because it matches on the `title` column, and a freshly indexed PDF's
title is whatever the first text block happens to be:
`arXiv:2504.01702v1 [econ.EM] 2 Apr 2025`, `NBER TECHNICAL WORKING PAPER
SERIES`, `, Amy C. Murillo`. **A coverage report over unenriched titles measures
extraction quality, not holdings**, and it fails in the flattering direction for
a harvest (it under-reports what you have, so the next run re-fetches it). The
order is therefore load-bearing: index, enrich, *then* measure.

Three concepts do not move, and they are the same three the paywalls hold.
**`Event log to time series / performance signals` is unchanged at one mention
and zero holdings** — the performance-spectrum papers are the literature for it
and they are gated (below). `Bullwhip and demand amplification` is unchanged at
five mentions because all four canonical works sit in *Management Science* and
the *Sloan Management Review*. `The benchmark critique` gained the Keogh/Wu
paper itself but stays `mention-only`, which is the audit working correctly: one
holding is not a discussion. So the honest result of the round is that **the
gap is real, it is now precisely located, and it is not closable by open
access** — which is a more useful finding than a number that went up.

Three things are worth recording about the harvest itself.

- **A publication page and a profile answer different questions, and mixing
  them up loses the recent half of an author's work.** Keogh self-hosts
  essentially everything, so his page *is* his bibliography. Shah's page carries
  year headings from 1999 to **2018 and stops** — so mSSA, tspDB, synthetic
  interventions and causal matrix completion, i.e. precisely the line this round
  wanted, are not on it. Enumeration therefore comes from Scholar (the only
  complete and current statement) and the page is consulted as a *resolver*. The
  profile is cached to `imports/scholar-<user>.json` and used when Scholar
  refuses, so a blocked run degrades to the last good enumeration instead of
  silently reporting an author with no publications.
- **Titles cannot separate a method paper from an application of it; the venue
  can.** Shah's profile carries 19 patents and a substantial haematology
  collaboration, and *Forecasting optimal treatments in relapsed/refractory
  mature T-cell lymphoma* is a forecasting paper by every word in its title. A
  keep-list on the title admits it; a drop-list on the **venue**
  (`US Patent`, `Blood`, `British journal of haematology`, `medRxiv`, …) removes
  14 works cleanly. This is the third time this repository has reached the same
  conclusion — see the Databricks breadcrumb filter (§4) and the `Analyst
  Reports/` routing (§5) — that where a publisher classifies its own output, that
  classification beats one inferred from the text.
- **A hand-maintained page mislabels its own links, and only reading the file
  catches it.** Keogh's pages carry no markup separating a title from the
  authors and venue around it, so the parser attributed **97 of 192 files to a
  venue token** (`Icdm - …`, `Discovery et al - …`, `Databases - …`), and **four
  of the page's hyperlinks point at a different paper than the title above
  them** — `Matrix Profile XIV` links the consensus-motif PDF, which is XV; XVII
  links LAMP, which is XVIII; XXVIII links the DMKD journal version of Matrix
  Profile I; and *Accelerating Time Series Searching with Large Uniform
  Scaling* links the poultry-welfare paper. Eight further entries name a
  conference version and link the retitled journal one. This is §3d's defect
  one layer later — a file named from the *requested* title, invisible to every
  check that trusts the citation — and the thing that catches it is
  **enrichment**, which reads the PDF's front matter and disagrees. Hence
  `scripts/rename-from-metadata.py` and its rule that the PDF outranks the page
  it was linked from: **91 renames**, 79 on the author prefix, 12 where the
  title belonged to another paper. Four intended works turn out not to be held;
  four unintended but in-scope ones arrived instead.
- **The same duplicate-title trap as §3d, arriving from the other direction.**
  Scholar profiles carry merged records, so the same work appears as
  *tspdb: Time series predict db* and *Time Series Predict DB.*, and as *Time
  series analysis via matrix estimation* and *Model Agnostic Time Series
  Analysis via Matrix Estimation*. Fuzzy-matching them away is what produced the
  wrong file in §3d, so nothing is dropped on title similarity here — both are
  fetched and `import-downloads.py`'s byte-dedup collapses them. It caught
  exactly **5**, all of them these pairs, which is the cheap end of the trade:
  five redundant downloads against one paper filed under a title it does not
  have.

**What is gated: 46 works, and they cluster by publisher rather than by
subject.** **39** have no open copy any resolver knows, and **7** more resolve
to a URL that then refuses the fetch. The painful cluster is the **performance
spectrum** — Denisov, Belkina & Fahland's BPM 2018 paper is behind a `403` at
`research.tue.nl`, and the ICPM 2019 predictive-monitoring paper, Klijn &
Fahland on batch processing, Maaradji's drift detection and the inter-case
remaining-time paper have no open copy at all. That is precisely the bridge
literature the audit found thinnest, so the gap this round set out to close is
the one the paywalls defend best. Beyond it: all four **bullwhip** works
(Lee/Padmanabhan/Whang, Chen et al., Sterman 1989, and the *Management Science*
survey); the M4 and M5 competition papers, which Elsevier answers `403` to
despite both being open access; the JAIR causal-discovery survey (`404` at its
own download endpoint); Faloutsos & Rafiei's wavelet paper and Cormode's
Count-Min sketch; *Revisiting Time Series Outlier Detection*; and
`dspace.mit.edu`, which answers **405** to a plain GET for the only open copy of
Shah's mSSA paper that Unpaywall knows about. On Shah's side the 22 unreachable
works are mostly recent conference versions — synthetic A/B testing, synthetic
interventions extended to multiple treatments, CausalSim, the Prediction Query
Language paper — where no preprint was posted.

**`MIRRORS` earned its keep again, and so did verifying it.** The table holds
**25** hand-checked direct URLs, and **8** of them were the only route to the
file this round: Faloutsos self-hosts the 1994 subsequence-matching paper at
CMU; KDD-94 was an AAAI *workshop*, so Berndt & Clifford is in the AAAI
technical-report series; SIGMOD Record has been free since 1969 and is absent
from Unpaywall; the *Journal of Statistical Software* is gold OA but serves PDFs
under a content type of `pb`, which the generic downloader declines; and Hyndman
self-hosts his bibliography under short internal names (`Hierarchical6.pdf`,
`mase.pdf`, `MinT.pdf`) that bear no relation to the published titles, so no
title-driven resolver can reach them. Roughly half the plausible-looking first
guesses returned an HTML error page rather than a file, which is why every entry
was checked by fetching it and confirming a `%PDF` header — the same discipline
§3c records.

### 3f. Microsoft Fabric IQ — the competitor ontology item, and the engine under it

`import-docs.py --only fabric-iq fabric-rti kusto` — **1,918 pages, 11.2 MB**
in three files under `Literature/Tool & Competitor Documentation/Microsoft/`.
All CC-BY-4.0. ✅

Fabric IQ is the closest thing another vendor has shipped to the Context Model:
a governed **ontology** item that declares entity types, properties,
relationship types and rules over lake data, binds them to lakehouse tables and
eventhouse streams without copying, materialises the result as an instance
graph, and exposes the whole thing to agents (including as an MCP server). It
is held whole rather than as the ontology tree alone, because the ontology
documentation **defers its storage and query semantics to two neighbours**:
*Graph in Microsoft Fabric* (the labeled-property-graph item that ontology
creates and manages for it, and where GQL, node/edge types and node-key
constraints are actually specified) and *Fabric Activator* (where a rule is
evaluated). The planning tree comes with it because Planning is an item of the
same workload.

| Source | What | How | Status |
| ------ | ---- | --- | ------ |
| `github.com/MicrosoftDocs/fabric-docs` → `docs/iq/` | **Fabric IQ** — the workload overview and item inventory; the ontology item (core concepts, entity/relationship type creation, data binding, semantic enrichment, rules, resource links, generation from a Power BI semantic model, the five agent surfaces, the MCP endpoint, glossary, FAQ, troubleshooting, capacity), the 6-part Lakeshore Retail tutorial, the Cowork / M365 Copilot connectors, and the planning (PowerTable / InfoBridge) tree | `import-docs.py --only fabric-iq` (git, sparse) | ✅ |
| the same repo → `docs/graph/` | **Graph in Microsoft Fabric** — labeled property graph vs. RDF, schema design, node and edge types, GQL (graph patterns, expressions, values and value types, conformance, reserved terms, the query API), performance and monitoring | same source | ✅ |
| the same repo → `docs/real-time-intelligence/` | **470 pages** — the **eventhouse** (a container of KQL databases: creation, OneLake availability / "one logical copy", the SQL and eventhouse endpoints, encryption, reliability, capacity planning and autoscale, monitoring, the remote MCP server, vector search), **KQL databases** (tables, update policies, materialized views, database shortcuts, retention), **eventstreams** (sources, destinations, routing, transformations), **Activator** (rules, triggers, actions — what an ontology rule actually runs on) and the **operations agent** | `import-docs.py --only fabric-rti` (git, sparse) | ✅ |
| `github.com/MicrosoftDocs/dataexplorer-docs` → `data-explorer/kusto/` | **1,159 pages** — the **Kusto Query Language** reference: the tabular/dataflow operators, ~500 scalar and aggregation functions, the time-series operators (`make-series`, `series_decompose`, anomaly detection, forecasting), the **graph operators** (`graph-match`, `make-graph`, `node-degree-in`), and the management surface where the engine's economics live (update, retention, caching, partitioning and restricted-view policies; materialized views) | `import-docs.py --only kusto` (git, sparse) | ✅ |

**Why the last two came along.** The ontology's own documentation stops at the
boundary of the ontology item, and the two things a reader most wants are on the
other side of it. A **time-series property binds to an eventhouse**, so what
"real-time" costs — the ingestion path, the OneLake copy, the caching and
retention policies, whether the store is even warm — is specified in Real-Time
Intelligence and nowhere in the IQ tree. And an eventhouse **is a Kusto
cluster**: the query the binding ultimately runs is KQL, which the corpus held
nothing on at all (a search for the engine returned Databricks ingestion blog
posts). KQL is also the one dialect here that puts tabular, time-series and
graph operators in a single language, which is the comparison the SQL dialects
in §3 cannot supply and the exact question the Context Model's own query surface
faces.

Three things are worth knowing before re-running any of it.

- **The docs are open source, and the repository is 3.3 GB.** Microsoft
  publishes the whole Fabric documentation set as markdown, so the §3 rule
  applies — read it from the repository rather than scraping the rendered site.
  But the repository carries every screenshot in the Fabric docs, and a
  `--depth 1` clone still materialises all of it for ~2 MB of IQ markdown. The
  `git` method therefore gained a `sparse` option: `--filter=blob:none` with a
  **non-cone** sparse pattern set, which fetches file contents only for the
  matched paths (**2.2 MB working tree, 3.4 MB `.git`, ~4 s**). Non-cone
  matching is the load-bearing part — cone mode selects whole *directories*, so
  it cannot express "the markdown but not the media" and brings the 3.3 GB back.
  `dataexplorer-docs` is 454 MB and behaves the same way.
- **Learn publishes neither a per-section sitemap nor raw markdown.**
  `/en-us/fabric/sitemap.xml` is a 404 and so is the `<page>.md` suffix that
  Docusaurus sites answer, so the sitemap-matching that gives the Bitol and
  Ontos entries their hosted URLs has nothing to match against. The hosted page
  is derived from the repo path instead (`url_template`), which is exact here
  because Learn's URL *is* the path below `docs/` with the suffix dropped.
- **A path-derived URL invents a 404 for every file the site doesn't publish.**
  Nine of the Fabric IQ units are `includes/` fragments — transclusion targets like
  `supported-property-types.md`, which appears inside two published pages and
  has no page of its own. Every one of them resolved to a plausible-looking
  Learn URL that answers 404. They are cited by GitHub blob URL instead
  (`unhosted_re`), which matters much more for the other two: Real-Time
  Intelligence keeps **111** of its 470 units in `includes/`, and KQL 42.
  The general form of this is the trap §3b keeps finding from
  the other direction: a derived identifier is silently wrong exactly where the
  source's structure disagrees with the rule that derived it, and it fails
  looking correct.

---

## 4. Company / practitioner blogs

Imported to `Literature/Blogs/<Company>/` via `scripts/import-blogs.py`
(changelogs/release/PR posts dropped). ✅

**Databricks** · MotherDuck · DuckDB · RelationalAI · Firebolt · Gel · Malloy ·
Bauplan · Anchor Modeling · CedarDB · Kùzu · TypeDB · **Andy Pavlo (CMU)** ·
**Martin Fowler** · **Ole Olesen-Bagneux** (Substack) · **OneWill** 🔄.

The `#llm-paper-sharing` sweep added full, rerunnable technical-blog sources for
**Google Research** (current + legacy archive), **Anthropic Engineering &
Research**, **OpenAI** (engineering / research / publication sitemaps;
posts at `openai.com/index/<slug>/`), **Microsoft Engineering**, **Berkeley AI
Research**, **Hugging Face** (official posts only), **Meta Engineering**,
**Zalando Engineering** (`engineering.zalando.com`, dated `/posts/YYYY/MM/…`),
**Chip Huyen**, and **METR**. The same sweep keeps an explicit manifest of 38
technical posts named in the channel whose publishers do not justify a
whole-corpus import (Uber QueryGPT, Chroma, Schneier, Mistral, Snowflake, SAP,
SemiAnalysis, Cohere, and others): `scripts/slack-llm-sources.py blogs`.

Two of these needed more than a sitemap and a URL pattern:

- **Databricks** is by far the largest (~3,340 posts across the current site and
  the 2013–2023 legacy archive, read as two sitemaps) and most of it is vertical
  marketing, CxO thought-leadership or SEO glossary pages. Each post names its
  own section in a breadcrumb, so the source filters on **that** rather than on
  title words: `engineering`, `platform` and `databricks-ai` are kept, and
  `industries`, `company`, `data-strategy` and `data-ai-foundations` are dropped.
  See `README.md` → *`Blogs/<Company>/`* for why the structural signal beats a
  title regex here.
- **Kùzu** — `kuzudb.com` no longer resolves (Kuzu Inc. wound down), so the
  registry points at the surviving GitHub Pages mirror,
  [`kuzudb.github.io/blog`](https://kuzudb.github.io/blog/). Its 40 posts are the
  18 already held plus 22 release notes, i.e. the collection is complete; the
  entry exists so the source is citable and re-runnable rather than orphaned.
- **Martin Fowler** — no sitemap; `/tags/` is the complete articles + bliki
  index. Fragments and photography are not imported.
- **Ole Olesen-Bagneux** — Substack sitemap (`/p/…` posts) on data catalogs
  and the meta-grid.
- **Bauplan papers** — the 2025–2026 arXiv set (`scripts/bauplan-papers.py`)
  sits next to the blog, under `Literature/Data Platforms/Bauplan/`. Shelf role:
  *safe agent execution* (branch → verify → merge, contracts), not Text-to-SQL
  SOTA — pair with `gap-agentic-sql.py` / `Outbox/agentic-sql-reliability/` for
  the enterprise query-correctness half.
- **Agentic SQL / PQL reliability** — `scripts/gap-agentic-sql.py` (RUBICON,
  Spider 2.0, DIN/MAC/CHASE/CHESS, SQL HCI) → `Literature/Process Mining/AI/`;
  Stonebraker CACM via `import-blogs.py --only stonebraker-cacm`; gap topic
  `agentic-sql-reliability` in `scripts/gap-topics.json`.
- **OneWill** — [`onewill.ai/blog`](https://onewill.ai/blog/). Sitemap
  `https://onewill.ai/sitemap.xml`, posts at `/blog/<year>/<slug>/`. The
  currently listed piece is *Stealing 50 Years of Database Ideas for AI Agents*
  (Lim & Zhang, Jul 2026; reviewed by Andy Pavlo): write-ahead logging,
  UNDO/REDO and compensating actions as the control plane between speculative
  agent work and durable world mutations (Wally). Adjacent Columbia/Wu work
  already in the corpus is CIDR’26 *Please Don’t Kill My Vibe*, *Agentic Data
  Environments*, and *BranchBench*.

CedarDB, Kùzu and TypeDB were listed here while **missing from the importer's
registry**, so for a while they could not be re-run — restoring the three entries
immediately turned up 16 unheld posts. A source that is documented but not
registered looks maintained and is not, which is worth checking for.

---

## 5. Source-system knowledge, specifications & analyst reports


| Collection                  | Sources                                                                    | Status |
| --------------------------- | -------------------------------------------------------------------------- | ------ |
| `Source Systems Knowledge/` | Oracle Fusion interface tables · SAP data-dictionary tables · **Atlassian** (Jira Data Center database schema & data model, the data-pipeline export schema, and 7 per-version schema documents — see §5c) | ✅      |
| `Specifications/`           | OMG (BPMN/CMMN/DMN) · W3C (RDF/OWL) · OntoUML · BFO · Semantic Arts (gist) · HQDM / MagmaCore · Industrial Ontologies Foundry · **Bitol** (ODCS v3.1.0, ODPS v1.0.0) · **OpenTelemetry** (specification + semantic conventions) · **Google Cloud** (Open Knowledge Format v0.2 — see §5d) · **IDSA** (19 position/white papers + IDS-RAM 4.0 + Dataspace Protocol — see §5b) | ✅      |
| `Analyst Reports/`          | **Gartner** (11: Magic Quadrants for Process Intelligence, Process Mining, DTO, Decision Intelligence, BOAT; Critical Capabilities; Market Guides) · **Everest Group** (1: Process Mining PEAK Matrix 2023) | ✅      |

Acquired manually rather than harvested — these are licensed, per-seat documents
with no scrapeable source. Drop new ones in `Inbox/` and the importer files them
by publisher fingerprint (see `README.md` → *`Analyst Reports/<Firm>/`*).
Forrester · IDC · HFS · ISG · NelsonHall rules exist but have no documents yet.


## 5b. Data spaces — IDSA (International Data Spaces Association)

The standards-body corpus on **cross-company data sharing**: how independent
organisations exchange data across an organisational boundary while each keeps
control of its own (data sovereignty, usage control, a shared semantic model,
participant onboarding, certification, governance). Pulled in as the external
prior art for the **Celonis Networks** design documents that arrived in
`Internal/` — Networks is a hub-and-spoke platform for
sharing *process outcomes* between business partners under a common taxonomy and
a data-minimisation principle, which is the same problem IDSA has been
specifying since 2016. All of it is CC-BY.


| Source                                                        | What                                                                                                                                                                                                                                            | How                                                                | Status |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------ |
| `internationaldataspaces.org/publications/papers/`            | **19 position & white papers, 2021–2026** — Usage Control (v3.0) · Data Sovereignty (manufacturing requirements + critical success factors) · Governance for Data Space Instances · Semantic Interoperability (2024-04 and v1.1) · Data Spaces Landscape / Standardization Landscape (v1.0 and v2.0) · Business Models · Observability · Reference Testbed · IDS ↔ Industry 4.0 · the DGA & data intermediaries · the EU AI Act · Data Spaces and AI (agentic participation) · the **IDSA Rulebook 2026** white paper | `scripts/idsa-papers.py` → `Inbox/idsa/` (direct PDFs)              | ✅      |
| `github.com/…/IDS-RAM_4_0`                                    | **IDS Reference Architecture Model 4.0** — roles, the connector, the five layers (business / functional / process / information / system), certification. The papers page links the GitBook rather than offering a PDF                            | `import-docs.py --only ids-ram` (git → 92 pages)                    | ✅      |
| `github.com/…/ids-specification`                              | **Dataspace Protocol** — catalog, ODRL contract negotiation, transfer process, plus the JSON Schemas, message examples and SHACL shapes an implementation is checked against                                                                     | `import-docs.py --only dataspace-protocol` (git → 227 units)        | ✅      |


Two things are worth knowing before re-running the harvester:

- **The edition lives on the page, not in the PDF.** Several papers exist in two
  editions under an identical title (*Semantic Interoperability*,
  *Standardization Landscape*), and only the listing's "Version 1.1 | November
  2025" subtitle distinguishes them. So the harvester parses the listing for
  title + version + date and writes them into the filename
  (`IDSA - <Title> (v1.1, 2025-11).pdf`), following the `Analyst Reports/`
  convention for dated snapshots from one publisher.
- **`IndexDedup` must not gate the download here.** The shared title check (§1b)
  would match the newer edition against the older one already in the index and
  skip it. Skipping is decided by the exact versioned filename instead; the
  title-match result is recorded in `Inbox/idsa/_idsa-report.csv` for
  information only.

Routing is by publisher fingerprint, like the analyst reports: the
`Specifications/IDSA` rule in `import-downloads.py` keys on the cover boilerplate
of IDSA's own template (*"Position Paper of the IDS Association"*, printed on
every edition), so an academic paper *about* IDS by an IDSA-affiliated author is
not captured by it.

## 5c. Source systems — the Jira Data Center database (Atlassian)

Jira is the source system behind most ticket, ITSM and software-delivery process
mining, and it is the uncommon case where the **vendor documents its own
tables**: `changegroup`/`changeitem` (the change history — a Jira event log in
all but name), the `customfieldvalue` family, the `OS_*` OfBiz workflow tables,
and the Embedded Crowd `CWD_*` user directories. That is what an extraction has
to join correctly, and it is what the REST API describes only indirectly.

Held in three parts under `Literature/Source Systems Knowledge/Atlassian/`, all
© Atlassian:


| Source                                                       | What                                                                                                                                                                                                                                                       | How                                                        | Status |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------ |
| `developer.atlassian.com/server/jira/platform/database-schema/` | **9 pages** — the `database-*` family (schema overview, change history, configuration properties, custom fields, issue fields, issue status & workflow, user and group tables) plus the two pages that explain how the tables are reached: `architecture-overview` (Entity Engine / OfBiz, `GenericValue`) and `entity-properties` (entity data kept as JSON rather than as columns) | `import-docs.py --only jira-db` (sitemap → 9 pages, 75 KB) | ✅      |
| `confluence.atlassian.com/display/adminjiraserver/data+pipeline+export+schema/` | **The data pipeline** — the sanctioned scheduled CSV export (issues, issue fields, issue **history**, issue links, SLA cycles, users, approvals, canned responses, knowledge base) and its versioned, field-by-field export schema, plus the export/config REST groups | `import-docs.py --only jira-data-pipeline` (6 pages, 47 KB) | ✅      |
| The attachments on the `database-schema` page                 | **7 per-version schema documents**, Jira 5.12 → 9.0. Six are SchemaCrawler text listing every table and column with its type (8.20: **176 tables**), which is the only complete statement of the schema Atlassian publishes — the prose pages cover five table groups | `scripts/atlassian-schema.py all` → `Inbox/jira-schema/`    | ✅      |


Only **Data Center** has a database a reader can query, so nothing under
`/cloud/` is in this collection. Confluence and Bitbucket Data Center share the
data pipeline and its product-doc family, which is the cheapest extension of
this entry if their tables are ever wanted.

Five things worth knowing before re-running any of it:

- **The newest schema document is the unusable one.**
  `jira_9.0_database_schema.pdf` is 3 MB of two embedded images with **zero**
  extractable characters, while every older edition is ~80 KB of text. Nothing
  about the download says so — it is a valid PDF, the largest of the set, and it
  renders perfectly — so `atlassian-schema.py` probes each file's text layer and
  records `text_chars` per version in its report. OCR does not rescue this one
  either: the page is 5449×5858 pt (**76×81 inches**), and rendering it to the
  OCR stage's 2200 px maximum edge puts 8 pt table labels at about 3 px. **8.20
  is therefore the newest edition whose schema can actually be queried**, and it
  describes the same core tables.
- **Routing is by drop-zone folder, not by content.** A SchemaCrawler export
  opens on *"Generated by: SchemaCrawler 8.16 / Database: H2"* and then lists
  table names, which the keyword rules read as a database paper (and the
  image-only 9.0 edition as nothing at all), so
  `COHORT_FOLDERS["jira-schema"]` in `import-downloads.py` files the cohort from
  where it was dropped — the same mechanism the Apache papers use (§3c).
- **Do not run `search/retitle.py` over this folder.** The LLM titles these
  documents from their own first page, which drops the Jira version the filename
  carries and names the *host* database instead: the 6.1 export is titled
  *"PostgreSQL Database Schema Documentation"* and three others *"SchemaCrawler
  Database Schema Export — H2 Database"*. Accurate about the dump, useless as a
  distinguishing title — the same reason the IDSA editions are excluded (§5b).
- **Cite the product docs by their alias.** `confluence.atlassian.com` answers
  `/display/<space>/<page+title>/` with a redirect to the current release's page
  id (`data-pipeline-1027142324.html`, Data Center 11.3). The id changes with
  every release; the alias does not, so the alias is what the source list holds.
- **Discovery is by sitemap, not an enumerated list**, so a `database-…` page
  Atlassian adds later is picked up on the next run — and `atlassian-schema.py`
  reads the versions off the anchor text (`Jira_8.20_schema.pdf`) for the same
  reason, including the typo the page has carried for years
  (`Jira_5.12_chema.pdf`).

Three importer defects had to be fixed before any of this could be read, and all
three were silent — see `README.md` → *Latest round* for what each one produced.

## 5d. Open Knowledge Format (OKF) — a specification for what this repository is

OKF is Google Cloud's format for shipping a body of knowledge as a directory of
markdown files with YAML frontmatter: no schema registry, no central authority,
no required tooling. Its premise is that a knowledge corpus is no longer
authored once and then read but **continuously written and maintained by
agents**, so the frontmatter makes first-class the four questions a reader of
machine-written prose has — what was this derived from and how was it verified
(provenance), how much should it be trusted, is it still true, and is it the
current version — plus *attestation*, a signed claim that a number was produced
by the computation it says it was.

It belongs in `Specifications/` next to ODCS, ODPS and Apache Ossie, which it
completes rather than competes with: those standardise the contract over a
dataset, the product wrapped around it and the semantic layer between tools,
and OKF standardises the prose *about* all three. It is also the closest thing
in the corpus to a written-down version of what this repository does by hand.


| Source                                                | What                                                                                                                                                                                                                     | How                                       | Status |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ------ |
| `github.com/GoogleCloudPlatform/open-knowledge-format` | **86 files, 236 KB** — the v0.2 specification, the four worked bundles (`acme_retail`'s attested metrics and policies; the BigQuery public datasets — Bitcoin, GA4, Stack Overflow — modelled as tables, joins and metrics), the reference agent's prompts, and the GCP knowledge-catalog connector note | `import-docs.py --only okf` (git → 86 units) | ✅      |


Two notes for a re-run:

- **The URL that circulates is a frozen copy.** The specification is widely
  linked as `GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md`, and
  that file is byte-identical to the canonical one today (modulo trailing
  whitespace) — while its own README says the directory is a frozen snapshot,
  no longer maintained, and that OKF now lives in
  `GoogleCloudPlatform/open-knowledge-format`. Registering the snapshot would
  have looked correct indefinitely and silently stopped tracking the spec at
  v0.2, which is the §4 Kùzu lesson in its quieter form: a source that cannot
  be re-run to the *current* text is not a source, even when it currently
  matches.
- **The examples and the agent prompts are taken with the specification**,
  because OKF is a convention rather than a schema. There is no validator to
  check a bundle against, so the worked bundles are where the conventions are
  actually pinned down, and the reference agent's prompts are the only
  statement of how a bundle is meant to be *written* by an agent — the format's
  whole premise, and absent from the normative text.

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
| `Internal/`                              | Curated internal docs (PIG-SL / PQL / Saola / CCMM / EMS 2.0 slide decks & specs), plus the **Networks** set — product memo, technical handover, macro-architecture review, the PnE high-level backend design, CDN architecture and infrastructure responsibilities (its external counterpart is the IDSA corpus in §5b). Routed by the internal-marker detector in `scripts/import-downloads.py`; office files (`.docx/.pptx/.xlsx`) treated as internal by suffix. | ✅      |
| `reference/celonis/`                     | Celonis checkouts — Context Model wiki (`pig-sl`), Studio Platform HQ, PM Solutions, PMI LaTeX, OCDM prototyping env. Reference only.                                                                                          | ✅      |
| `reference/bitol/`                       | ODCS + ODPS standards. Also the *source* of the two `Specifications/Bitol/` collections (§5) — the doc sites are mkdocs builds of these repos.                                                                                 | ✅      |
| `reference/databrickslabs/ontos/`        | Ontos (branch `development`). Also the source of the Ontos collection (§3); the repo's internal churn (`docs/notes/`, `.planning/`, testing plans) is excluded from the import.                                               | ✅      |


---

## 8. Books, textbooks & standards specs

`Literature/Books/` and `Literature/Reference and Textbooks/` — curated reference
works; `Specifications/OMG/` also holds the OMG DMN 1.5 spec pulled during the
seed-catalog gap-fill. ✅

## 8b. Course notes — RWTH Aachen Panikzettel

The [Panikzettel](https://htwr-aachen.de/panikzettel) are student-written
distillations of RWTH Aachen computer-science lectures — a whole course in two to
six dense pages, CC-BY-SA, LaTeX sources at
[htwr-aachen/panikzettel](https://github.com/htwr-aachen/panikzettel). The site
is a maintained fork of the original, now-unmaintained
[panikzettel.philworld.de](https://panikzettel.philworld.de) collection.

They are here for their density rather than their novelty: *Berechenbarkeit und
Komplexität*, *Formale Systeme, Automaten und Prozesse*, *Datenbanken und
Informationssysteme* and *Mathematische Logik* state the definitions and theorems
the process-mining and database corpus assumes without restating, in a form short
enough to retrieve whole rather than as a chunk.


| Source                              | What                                                                                                                                                                                       | How                                                                       | Status |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------ |
| `api.htwr-aachen.de/api/panikzettel/` | **36 sheets** — 14 compulsory subjects (analysis, linear algebra, data structures & algorithms, automata, computability & complexity, databases, logic, stochastics, software engineering, OS, networks, IT security, ML) · 16 compulsory electives (advanced automata theory, efficient algorithms, static program analysis, functional programming, probabilistic programming, HPC, social networks, AI, computer graphics, algorithmic foundations of data science …) · 5 application-area subjects (incl. **Business Process Intelligence**, operations research, decision theory) · the Meta-Panikzettel | `scripts/panikzettel.py all` → `Inbox/panikzettel/` (direct PDFs)           | ✅      |


Two notes for a re-run:

- **The metadata is in the API, not the page.** `htwr-aachen.de/panikzettel` is a
  Next.js app that renders its list client-side from
  `api.htwr-aachen.de/api/panikzettel/`, so the harvester reads the JSON. That is
  a feature, not a workaround: the course name, the curriculum slot and the
  **revision date** live only there, and the date is what the filename needs
  (`Panikzettel - <Course> (<YYYY-MM-DD>).pdf`).

  Taking the date from the *document* instead would have been the obvious move
  and is wrong. 27 of the 36 sheets print a date that matches the API exactly,
  but seven — FoSAP, Berechenbarkeit und Komplexität, Datenbanken und
  Informationssysteme, Stochastik, Datenkommunikation, Betriebssysteme,
  Maschinengestaltung — all print **30. Juli 2026**, which is not seven
  simultaneous revisions but `\today` at the site's last build. Those are exactly
  the sheets that have not been touched in years, so the one date a reader would
  most want is the one the PDF cannot supply, and it fails *silently* by looking
  freshly current.
- **`IndexDedup` must not gate the download**, for the same reason as IDSA (§5b):
  a new revision of a sheet shares its title with the copy already held. Skipping
  is decided by the exact dated filename; the title match is recorded in
  `Inbox/panikzettel/_panikzettel-report.csv` for information only.

Routing is by the collection's own name — the `Course Notes/RWTH Aachen
Panikzettel` rule in `import-downloads.py` keys on "panikzettel", which is printed
on every sheet and is the filename prefix the harvester writes. It sits with the
other publisher-keyed rules, *before* the topic rules, because otherwise the
database sheet and the logic sheet would classify on their subject vocabulary and
the collection would arrive scattered.

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
`import-docs.py` (docs), `atlassian-schema.py` (the Jira schema documents),
`import-blogs.py` (blogs), `import-youtube.py`
(transcripts), `fetch-papers.py` (paper PDFs), `dedup-inbox.py` (title dedup),
`import-downloads.py` (Inbox importer — `--only <subfolder>` files a single
harvester's output without sweeping in the rest of the drop zone, and
`COHORT_FOLDERS` routes a whole harvested cohort by that subfolder instead of
guessing at its vocabulary), `apache-projects.py` (enumerate + probe the ASF doc
sites), `apache-papers.py` (the Apache citation cohort),
`slack-llm-sources.py` (primary papers and technical posts shared in
`#llm-paper-sharing`; excludes news/social/product-only links),
`bauplan-papers.py` (recent Bauplan Labs arXiv papers → `Data Platforms/Bauplan/`),
`scholar-authors.py` (Zaharia, Xin, Snowflake founding staff),
`gap-artifact-centric.py` (the artifact-centric / declarative cohort, §3d).

## Known-gated sources (need manual drop into `Inbox/`)

- **TU/e Pure portals** (Fahland, van Dongen) — HTTP 403, PDFs behind portal.
- **ResearchGate** (Weske) — blocks automated access.
- **ACM DL** (SIGMOD, KDD), **IEEE** (ICPM), **Springer LNCS** (BPM, CAiSE, ER,
Petri Nets) — paywalled; rely on author copies / arXiv / CEUR where they exist.
- **SAP LeanIX** docs — JS single-page app. **Apache DolphinScheduler** docs are
  the same shape (see §3b), except its SPA also answers `404`.
- **Pure portals generally**, not just TU/e — `pure.itu.dk` and
  `research.tue.nl` answer `403` to their own `/en/publications/?search=` form,
  so a title cannot be looked up; a pinned `/ws/files/<id>/<name>.pdf` path
  still works, which is how the Reijers/Slaats/Stahl paper was taken (§3d).
- **`re.public.polimi.it`** — Politecnico di Milano's IRIS answers `403` to
  every `/retrieve/` and `/handle/` URL regardless of headers, which is what
  gates the Baresi/Meroni/Plebani E-GSM monitoring paper.
- **The Hull/IBM artifact-centric primary sources** — the GSM meta-model papers
  (WS-FM 2010, the Inf. Syst. equivalence result), Hull's ODBASE 2008 survey,
  Bhattacharya et al.'s BPM 2007 formal analysis, Barcelona (ICSOC 2013) and the
  Marin/Hull/Vaculín CMMN survey. All Springer/ACM, and the author copies went
  with the retired `researcher.watson.ibm.com` pages. See §3d for what stands in
  for them; the DEBS 2011 paper survives only because a co-author self-hosts it.
- **Five Apache-project papers** with no open copy anywhere the resolvers or the
  verified mirrors reach: Pulsar's *Efficient and Flexible Multi-Tenant
  Messaging*, BookKeeper's *DistributedLog* (ICDE 2017, IEEE), *Apache Doris*
  (SIGMOD 2024), ZooKeeper's *Zab* (DSN 2011, IEEE) and the CouchDB-adjacent
  document-vs-relational comparison. ECharts' paper is open at Elsevier's *Visual
  Informatics* but its PDF endpoint answers `403` to non-browser clients.
- **The queueing classics** — Little's *A Proof for the Queuing Formula: L = λW*
  (1961) and *Little's Law as Viewed on its 50th Anniversary* (2011), Jackson's
  *Jobshop-Like Queueing Systems* (1963) at INFORMS; Kingman's *The single server
  queue in heavy traffic* (1961) and Lindley's *The theory of queues with a single
  server* (1952) at Cambridge; Gans, Koole & Mandelbaum's call-centre survey
  (*M&SOM* 2003). None has an open copy anywhere the resolvers can reach, and the
  author-hosted mirrors that used to serve them are gone. Whitt's own reviews
  (`§1`) restate all of them and are held instead.
- **Pre-web theses and proceedings** — van der Aalst's ExSpect-era work
  (*Specificatie en Simulatie met behulp van ExSpect*, 1988; the two Waltmans
  papers, 1990–91) predates his publications page's PDF archive, which starts at
  the 1992 PhD thesis (`p7.pdf`). Only a physical or library scan would close this.
- **Bot-challenged repositories** — some institutional repositories hold a genuinely
  open PDF behind a JS proof-of-work page or CAPTCHA, answering `HTTP 200` with an
  HTML challenge: `hal.science`, `madoc.bib.uni-mannheim.de`, `repository.hkust.edu.hk`.
  `paperfetch.download_pdf` reports these as `bot challenge (JS/CAPTCHA)`; they need
  a real browser, so treat them as manual drops.

