#!/usr/bin/env python3
"""Build curated third-party documentation collections under ``Literature/``.

Each source declares a ``collection`` (a top-level ``Literature/`` subfolder);
by default that is **Tool & Competitor Documentation** (SQL dialects and
data-platform foundations), but a source can instead be filed under, e.g.,
**Source Systems Knowledge** (ERP/source-system table & schema references).

Companion to ``import-blogs.py`` (company blogs) and ``import-web-book.py``
(books). For each registered documentation source this tool discovers the doc
pages (via ``llms-full.txt``, a ``sitemap.xml``, a bounded BFS ``crawl``, a
``toc`` table-of-contents page, an explicit ``pages`` list, or a ``git``
checkout — either a shallow clone or an existing ``reference/`` checkout named
by ``clone_dir``), converts each page to markdown, and writes **one
consolidated markdown file per source** (``<Company> Documentation.md``) with a
per-page ``<!-- source: URL -->`` provenance marker — so the search engine
ingests a tool's docs as a single reference document and the knowledge graph can
attach a ``Company`` node (see ``search/graph.py``).

Runs are idempotent by default (an already-written source file is skipped; use
``--force`` to rebuild). Discovery is bounded by a per-source ``cap`` and an
optional ``prefer`` regex that front-loads the most relevant sections (e.g. the
SQL reference) before the cap is hit.

    scripts/.venv/bin/python scripts/import-docs.py --list
    scripts/.venv/bin/python scripts/import-docs.py --only relationalai clickhouse
    scripts/.venv/bin/python scripts/import-docs.py --only postgresql --cap 50 --force
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from lxml import html as H

DOCS_ROOT = Path(__file__).resolve().parent.parent
LITERATURE = DOCS_ROOT / "Literature"
DEST_ROOT = LITERATURE / "Tool & Competitor Documentation"
IMPORTS = DOCS_ROOT / "imports"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
TIMEOUT = 45

_spec = importlib.util.spec_from_file_location(
    "iwb", str(Path(__file__).resolve().parent / "import-web-book.py"))
_iwb = importlib.util.module_from_spec(_spec)
sys.modules["iwb"] = _iwb
_spec.loader.exec_module(_iwb)
html_to_markdown = _iwb.html_to_markdown
strip_noise = _iwb.strip_noise


@dataclass
class DocSource:
    key: str
    company: str
    title: str
    method: str                     # llms_full | sitemap | crawl | git | next_data | toc | pages | butter_cms
    license: str = ""
    # destination collection (top-level Literature/ subfolder). Defaults to the
    # tool/competitor docs collection; set to "Source Systems Knowledge" (etc.)
    # to file a source under a different curated collection.
    collection: str = "Tool & Competitor Documentation"
    # llms_full
    llms_url: str = ""
    # sitemap
    sitemaps: tuple[str, ...] = ()
    keep_re: str = ""
    md_suffix: bool = False         # fetch "<url>.md" for raw markdown (Docusaurus)
    # version-partitioned doc sites: a regex with a ``ver`` group over the URL.
    # Only the highest version found is kept (see ``_pick_latest_version``).
    version_pick: str = ""
    # sitemaps that declare the wrong host (see ``_rewrite_host``)
    rewrite_host: str = ""
    # crawl / toc
    seeds: tuple[str, ...] = ()     # crawl: BFS seeds; toc: table-of-contents page(s)
    prefix: str = ""                # crawled/toc URLs must start with this
    # httpd autoindex of per-release directories: descend into the newest one
    # before crawling, instead of pinning a version (see ``_autoindex_latest``)
    autoindex: bool = False
    # pages
    pages: tuple[str, ...] = ()     # explicit list of page URLs to fetch as-is
    # git
    repo: str = ""
    branch: str = ""                # blob-URL ref (and clone branch); defaults to HEAD
    subdir: str = ""
    clone_dir: str = ""             # reuse an existing checkout (relative to DOCS_ROOT)
    file_globs: tuple[str, ...] = ("*.md",)   # which files to ingest from a git checkout
    # docs monorepo: fetch only these paths, and only at the tip, so one section
    # of a multi-gigabyte repository costs megabytes (see ``_sparse_clone``)
    sparse: tuple[str, ...] = ()
    # doc site whose hosted URL is derivable from the repo path rather than
    # matched through a sitemap: ``{slug}`` is the file's path below ``subdir``,
    # without its suffix
    url_template: str = ""
    # repo files the site never publishes as pages of their own (transcluded
    # includes, fragments): a path-derived URL would name a 404 for each, so
    # these are cited by their GitHub blob URL instead
    unhosted_re: str = ""
    # repo-backed doc sites: sitemap URLs are matched to the repo files they are
    # generated from, so the provenance marker names the hosted page
    url_map: tuple[tuple[str, str], ...] = ()   # explicit relpath -> hosted URL
    # butter_cms
    api_url: str = ""               # JSON endpoint proxying the ButterCMS content API
    api_path: str = ""              # value of its ``path`` query parameter
    site_root: str = ""             # SPA root used to rebuild per-page permalinks
    # shared
    prefer: str = ""                # front-load URLs matching this before capping
    drop_re: str = ""               # never fetch URLs matching this
    cap: int = 300
    source_url: str = ""            # human-facing landing page for the header
    # second collection for the same company (the default file name is derived
    # from ``company``, so a company with two sources needs one of them named)
    filename: str = ""


ASF_LICENSE = "Apache-2.0 \u2014 \u00a9 The Apache Software Foundation"

# Apache doc sites translate into a dozen languages under a locale segment
# (``/zh/``, ``/zh-cn/``, ``/ja/`` …). The translations are a partial, older
# mirror of the English pages, so importing them doubles the file and adds
# nothing an English query can reach.
_ASF_LOCALES = (r"/(?:zh|zh-cn|zh-CN|zh-tw|zh-Hans|ja|jp|ko|kr|fr|de|es|pt|"
                r"pt-br|ru|it|tr|id|uk|vi|fa)(?:/|$)")

# Docusaurus (which most newer Apache projects use) serves the *current*
# release unversioned at ``/docs/<page>`` and every archived release under
# ``/docs/<version>/<page>``, plus an unreleased ``/docs/next/``. Dropping the
# version-prefixed paths therefore keeps exactly one copy of the manual — the
# released one — without having to name a version that goes stale.
_ASF_ARCHIVED = r"/docs/(?:\d+(?:[.\d]*)(?:\.x)?|next|master|nightly|dev|in-dev)(?:/|$)"


def _asf(key: str, company: str, title: str, **kw) -> DocSource:
    """A ``DocSource`` with the Apache Software Foundation defaults filled in.

    Every ASF project shares a license, a host pattern (``<key>.apache.org``,
    or ``<key>.incubator.apache.org`` while incubating) and a ``/docs/`` root,
    so an entry only has to state what deviates. ``drop`` is *added to* the
    locale filter rather than replacing it.
    """
    host = kw.pop("host", f"{key}.apache.org")
    docs = kw.pop("docs", "/docs/")
    drops = [_ASF_LOCALES] if kw.pop("locales", True) else []
    if kw.pop("archived", False):
        drops.append(_ASF_ARCHIVED)
    if drop := kw.pop("drop", ""):
        drops.append(drop)
    kw.setdefault("method", "sitemap")
    if kw["method"] == "sitemap":
        kw.setdefault("sitemaps", (f"https://{host}/sitemap.xml",))
        kw.setdefault("keep_re", rf"^https?://{re.escape(host)}{docs}")
    elif kw["method"] == "crawl":
        kw.setdefault("seeds", (f"https://{host}{docs}",))
        kw.setdefault("prefix", f"https://{host}{docs}")
    kw.setdefault("drop_re", "|".join(f"(?:{d})" for d in drops))
    kw.setdefault("cap", 250)
    kw.setdefault("license", ASF_LICENSE)
    kw.setdefault("source_url", f"https://{host}{docs}")
    return DocSource(key=key, company=company, title=title, **kw)


SOURCES: list[DocSource] = [
    DocSource(
        key="postgresql", company="PostgreSQL", method="sitemap",
        title="PostgreSQL 19 Documentation",
        sitemaps=("https://www.postgresql.org/sitemap.xml",),
        keep_re=r"^https://www\.postgresql\.org/docs/19/[^/]+\.html$",
        prefer=r"/docs/19/(sql|functions|datatype|ddl|dml|queries|typeconv|"
               r"indexes|tutorial|catalogs|ddl|mvcc|performance)",
        cap=400, source_url="https://www.postgresql.org/docs/19/index.html",
        license="PostgreSQL License \u2014 \u00a9 The PostgreSQL Global Development Group",
    ),
    DocSource(
        key="googlesql", company="GoogleSQL", method="git",
        title="GoogleSQL (ZetaSQL) Documentation",
        repo="https://github.com/google/googlesql", subdir="docs",
        source_url="https://github.com/google/googlesql/tree/master/docs",
        license="Apache-2.0 \u2014 \u00a9 Google LLC",
    ),
    DocSource(
        key="datafusion", company="Apache DataFusion", method="crawl",
        title="Apache DataFusion Documentation",
        seeds=("https://datafusion.apache.org/",),
        prefix="https://datafusion.apache.org/",
        prefer=r"/(user-guide|library-user-guide)/",
        drop_re=r"/(contributor-guide|_sources|genindex|search)",
        cap=200, source_url="https://datafusion.apache.org/",
        license="Apache-2.0 \u2014 \u00a9 The Apache Software Foundation",
    ),
    DocSource(
        key="cedardb", company="CedarDB", method="sitemap",
        title="CedarDB Documentation",
        sitemaps=("https://cedardb.com/docs/sitemap.xml",),
        keep_re=r"^https://cedardb\.com/docs/.+",
        prefer=r"/docs/(references|sql|getting_started|cookbook)",
        cap=250, source_url="https://cedardb.com/docs/",
        license="\u00a9 CedarDB",
    ),
    DocSource(
        key="duckdb", company="DuckDB", method="sitemap",
        title="DuckDB Documentation (stable)",
        sitemaps=("https://duckdb.org/sitemap.xml",),
        keep_re=r"^https://duckdb\.org/docs/(stable|current)/.+\.html$",
        prefer=r"/docs/[^/]+/sql/",
        cap=350, source_url="https://duckdb.org/docs/",
        license="MIT \u2014 \u00a9 DuckDB Foundation / contributors",
    ),
    DocSource(
        key="relationalai", company="RelationalAI", method="llms_full",
        title="RelationalAI Documentation",
        llms_url="https://docs.relational.ai/llms-full.txt",
        source_url="https://docs.relational.ai/",
        license="\u00a9 RelationalAI",
    ),
    # The llms-full export reduces every template and guide to an unrendered
    # Astro component tag (``<TemplateDetail template="defect_root_cause" />``),
    # so the modelling content — which reasoning types a use case combines, how
    # concepts and rules are declared — is missing from the export entirely. The
    # server-rendered HTML has it, and "<url>.md" is only the bare title, so
    # these pages are scraped rather than taken as markdown.
    DocSource(
        key="relationalai-templates", company="RelationalAI", method="sitemap",
        title="RelationalAI \u2014 Solution Templates & Build Guides",
        filename="RelationalAI Templates & Guides.md",
        sitemaps=("https://docs.relational.ai/sitemap-0.xml",),
        keep_re=r"^https://docs\.relational\.ai/build/(templates|guides|tutorials|agents)/.+",
        prefer=r"/build/templates/",
        cap=200, source_url="https://docs.relational.ai/build/templates/",
        license="\u00a9 RelationalAI",
    ),
    DocSource(
        key="clickhouse", company="ClickHouse", method="sitemap",
        title="ClickHouse SQL Reference",
        sitemaps=("https://clickhouse.com/docs/sitemap.xml",),
        keep_re=r"^https://clickhouse\.com/docs/sql-reference(/.*)?$",
        cap=300, source_url="https://clickhouse.com/docs/sql-reference",
        license="Apache-2.0 \u2014 \u00a9 ClickHouse, Inc.",
    ),
    DocSource(
        key="gel", company="Gel", method="crawl",
        title="Gel (EdgeDB) Documentation",
        seeds=("https://docs.geldata.com/",),
        prefix="https://docs.geldata.com/",
        drop_re=r"/(_next|api/|search)",
        cap=250, source_url="https://docs.geldata.com/",
        license="\u00a9 Gel Data Inc.",
    ),
    DocSource(
        key="malloy", company="Malloy", method="crawl",
        title="Malloy Documentation",
        seeds=("https://docs.malloydata.dev/documentation/",),
        prefix="https://docs.malloydata.dev/documentation/",
        cap=200, source_url="https://docs.malloydata.dev/documentation/",
        license="\u00a9 Meta Platforms / Malloy contributors",
    ),
    DocSource(
        # Palantir docs are a client-rendered SPA; the page markdown is embedded in
        # the __NEXT_DATA__ JSON (props.pageProps.markdown), so we read it there.
        #
        # Discovery needs all three sitemaps: each caps at 5,000 alphabetically
        # ordered URLs, and the first is exhausted by /docs/foundry/api/ plus the
        # /docs/jp/ locale mirror — so sitemap.xml alone stops at "j" and hides
        # every section after it (insight, notepad, quiver cards, vertex, …).
        key="palantir-ontology", company="Palantir Foundry", method="next_data",
        title="Palantir Foundry \u2014 Ontology, Analysis (Quiver / Insight / Vertex), "
              "Actions, Functions, Automation & Machinery Documentation",
        sitemaps=("https://palantir.com/docs/sitemap.xml",
                  "https://palantir.com/docs/sitemap-1.xml",
                  "https://palantir.com/docs/sitemap-2.xml"),
        keep_re=r"/docs/foundry/(ontology|ontologies|ontology-manager|object-link-types|"
                r"object-views|object-explorer|object-monitors|interfaces|action-types|"
                r"functions|foundry-rules|quiver|time-series|insight|vertex|notepad|"
                r"machinery|process-mining|logic|automate|ai-fde)/",
        prefer=r"/docs/foundry/[^/]+/(overview|core-concepts|concepts|getting-started)/",
        cap=900, source_url="https://www.palantir.com/docs/foundry/ontology/overview/",
        license="\u00a9 Palantir Technologies Inc.",
    ),
    # KumoAI's relational foundation model docs now live on the NVIDIA docs
    # portal under /sdgm/ ("Structured Data and Graph Models"). Every page also
    # serves clean markdown at "<url>.md", so we take that instead of scraping.
    DocSource(
        key="kumoai", company="KumoAI", method="sitemap",
        title="KumoAI \u2014 KumoRFM & Structured Data / Graph Models Documentation",
        sitemaps=("https://docs.nvidia.com/sdgm/sitemap.xml",),
        keep_re=r"^https://docs\.nvidia\.com/sdgm/.+",
        md_suffix=True,
        prefer=r"/sdgm/(rfm|quick-start|sdk|reference|fine-tuning)/",
        drop_re=r"/(privacy-policy|consumer-privacy|data-processing-addendum|releases/)",
        cap=300, source_url="https://docs.nvidia.com/sdgm/rfm/overview",
        license="\u00a9 NVIDIA Corporation / Kumo.AI",
    ),
    # The Ikigai docs site is a client-rendered SPA with no sitemap; its content
    # comes from a ButterCMS collection exposed through a public proxy endpoint,
    # which returns every doc page (HTML body + navigation grouping) in one call.
    DocSource(
        key="ikigai", company="Ikigai Labs", method="butter_cms",
        title="Ikigai Labs Documentation",
        api_url="https://first-api.ikigailabs.io/component/"
                "get-content-management-system-documentations",
        api_path="/v2/content/?keys=page",
        site_root="https://docs.ikigailabs.io",
        source_url="https://docs.ikigailabs.io/",
        license="\u00a9 Ikigai Labs",
    ),
    DocSource(
        key="bauplan", company="Bauplan", method="sitemap",
        title="Bauplan Documentation",
        sitemaps=("https://docs.bauplanlabs.com/sitemap.xml",),
        keep_re=r"^https://docs\.bauplanlabs\.com/.+",
        md_suffix=True, cap=200, source_url="https://docs.bauplanlabs.com/",
        license="\u00a9 Bauplan",
    ),
    DocSource(
        key="snowflake", company="Snowflake", method="sitemap",
        title="Snowflake Documentation",
        sitemaps=("https://docs.snowflake.com/sitemap.xml",),
        keep_re=r"^https://docs\.snowflake\.com/en/(sql-reference|user-guide|developer-guide)",
        prefer=r"/en/sql-reference",
        drop_re=r"/(release-notes|migrations)",
        cap=400, source_url="https://docs.snowflake.com/en/",
        license="\u00a9 Snowflake Inc.",
    ),
    DocSource(
        key="databricks", company="Databricks", method="sitemap",
        title="Databricks Documentation (AWS)",
        sitemaps=("https://docs.databricks.com/sitemap.xml",),
        keep_re=r"^https://docs\.databricks\.com/aws/en/(sql|ingestion|dev-tools|delta|lakehouse|oltp|ldp|metric-views)",
        prefer=r"/aws/en/sql/",
        drop_re=r"/(release-notes|archive|error-messages)",
        cap=400, source_url="https://docs.databricks.com/aws/en/",
        license="\u00a9 Databricks, Inc.",
    ),
    # Ontos is a Databricks Labs app implementing ODCS/ODPS on top of Unity
    # Catalog, so it is filed with the tool docs rather than the standards it
    # consumes. It publishes no doc site \u2014 the guides live in the repo. Its
    # internal churn (refactoring logs, security reviews, TODO trackers under
    # docs/notes/ and .planning/) is excluded: that is engineering bookkeeping,
    # not documentation, and it would dominate retrieval by sheer volume.
    DocSource(
        key="ontos", company="Databricks", method="git",
        title="Databricks Labs Ontos \u2014 Business Catalog for Unity Catalog "
              "(User Guide, Handbook & Compliance DSL)",
        filename="Databricks Labs Ontos Documentation.md",
        repo="https://github.com/databrickslabs/ontos",
        branch="development",
        clone_dir="reference/databrickslabs/ontos",
        file_globs=("*.md",),
        drop_re=r"^(CLAUDE|SECURITY|CONTRIBUTING|\.planning/|plans/|docs/notes/"
                r"|docs/TESTING_PLAN|docs/testing-guidelines|docs/LICENSE_CHECKING"
                r"|src/frontend/|src/backend/|src/e2e/)",
        prefer=r"^(README\.md|src/docs/USER-GUIDE\.md|src/docs/|docs/handbook/)",
        cap=120, source_url="https://github.com/databrickslabs/ontos",
        license="Databricks License \u2014 \u00a9 2025 Databricks, Inc.",
    ),
    # Microsoft Fabric IQ is the closest competitor statement of what the
    # Context Model is: a governed *ontology* item over lake data (entity types,
    # properties, relationship types, data bindings, rules), the Graph item that
    # holds its instance graph, and the agent surfaces that consume it. The
    # Graph tree comes with it because ontology does not document its own query
    # or storage semantics \u2014 it defers to Graph and GQL for both.
    #
    # Read from the repository the site is built from, per the rule the Bitol
    # and Ontos entries follow, but that repository carries every screenshot in
    # the Fabric documentation set (~3.3 GB) for ~2 MB of IQ markdown, hence
    # ``sparse``. Learn publishes no per-section sitemap and no raw-markdown
    # endpoint (``<page>.md`` answers 404), so the hosted page each file renders
    # to is derived from its path rather than matched through a sitemap.
    DocSource(
        key="fabric-iq", company="Microsoft", method="git",
        title="Microsoft Fabric IQ \u2014 Ontology, Graph & Planning Documentation",
        filename="Microsoft Fabric IQ Documentation.md",
        repo="https://github.com/MicrosoftDocs/fabric-docs",
        branch="main", subdir="docs",
        sparse=("/docs/iq/*.md", "/docs/iq/**/*.md",
                "/docs/iq/ontology/*.yml",
                "/docs/graph/*.md", "/docs/graph/**/*.md"),
        file_globs=("iq/**/*.md", "graph/**/*.md",
                    "iq/ontology/resources-frequently-asked-questions.yml"),
        prefer=r"^docs/iq/(?:overview|get-started|ontology/(?:overview|resources-glossary"
               r"|concepts|how-to))",
        cap=400,
        url_template="https://learn.microsoft.com/en-us/fabric/{slug}",
        unhosted_re=r"/includes/",
        source_url="https://learn.microsoft.com/en-us/fabric/iq/",
        license="CC-BY-4.0 \u2014 \u00a9 Microsoft Corporation",
    ),
    # Real-Time Intelligence is where Fabric IQ's two loose ends are actually
    # specified: an *eventhouse* is the store a time-series property binds to,
    # and *Activator* is what evaluates an ontology rule. It also holds the
    # eventstream ingestion side and the operations agent the ontology docs
    # hand off to. Same repository and same sparse mechanism as `fabric-iq`.
    DocSource(
        key="fabric-rti", company="Microsoft", method="git",
        title="Microsoft Fabric Real-Time Intelligence \u2014 Eventhouse, KQL "
              "Databases, Eventstreams & Activator Documentation",
        filename="Microsoft Fabric Real-Time Intelligence Documentation.md",
        repo="https://github.com/MicrosoftDocs/fabric-docs",
        branch="main", subdir="docs",
        sparse=("/docs/real-time-intelligence/*.md",
                "/docs/real-time-intelligence/**/*.md"),
        file_globs=("real-time-intelligence/**/*.md",),
        prefer=r"^docs/real-time-intelligence/(?:overview|architecture|event"
               r"|create-|one-logical-copy|kql|table-|data-activator/|operations-agent)",
        cap=500,
        url_template="https://learn.microsoft.com/en-us/fabric/{slug}",
        unhosted_re=r"/includes/",
        source_url="https://learn.microsoft.com/en-us/fabric/real-time-intelligence/",
        license="CC-BY-4.0 \u2014 \u00a9 Microsoft Corporation",
    ),
    # An eventhouse is a Kusto cluster, and none of what makes it interesting is
    # in the Fabric documentation: the query language, and the engine policies
    # (update, retention, caching, partitioning, materialized views) that decide
    # what a "real-time" store actually costs. KQL is a dataflow query language
    # over semistructured data with graph operators (`graph-match`,
    # `node-degree-in`) and time-series operators in the same surface, which is
    # the comparison the SQL dialects here cannot supply. Held for the same
    # reason as GoogleSQL and the SAP HANA/Oracle dialects: the language, not
    # the product. `api/` and `tools/` are dropped \u2014 client SDKs and Kusto.Explorer
    # are the product's plumbing, not its semantics.
    DocSource(
        key="kusto", company="Microsoft", method="git",
        title="Kusto Query Language (KQL) \u2014 Query, Management & Concepts Reference",
        filename="Kusto Query Language (KQL) Reference.md",
        repo="https://github.com/MicrosoftDocs/dataexplorer-docs",
        branch="main", subdir="data-explorer",
        sparse=("/data-explorer/kusto/*.md", "/data-explorer/kusto/**/*.md"),
        file_globs=("kusto/**/*.md",),
        drop_re=r"^data-explorer/kusto/(?:api|tools)/",
        prefer=r"^data-explorer/kusto/(?:concepts/|query/(?:index|tutorials|scalar"
               r"|kql-|graph-|time-series|series-)|management/(?:index|.*polic))",
        cap=1200,
        url_template="https://learn.microsoft.com/en-us/{slug}",
        unhosted_re=r"/includes/",
        source_url="https://learn.microsoft.com/en-us/kusto/query/",
        license="CC-BY-4.0 \u2014 \u00a9 Microsoft Corporation",
    ),
    # Datadog is the reference system the Celonis Context Model's event handling
    # is argued from ("events are data, not schema"; one index across all
    # sources, not one per source), so its *query* surfaces are the part worth
    # holding: span search, Trace Queries (the `->` / `=>` structural operators
    # over a trace), the trace pipeline/retention rules those operators depend
    # on, DDSQL, and the log-management pipeline that turns raw logs into facets
    # and metrics. Every page serves clean markdown at "<url>.md".
    #
    # `ddsql_reference/data_directory/` is 2,100+ generated per-dataset schema
    # stubs (one per AWS/Azure/GCP resource type) and would drown the rest, so
    # it is dropped; the language reference itself is a handful of pages.
    DocSource(
        key="datadog", company="Datadog", method="sitemap",
        title="Datadog \u2014 Trace Explorer, Trace Queries, DDSQL & Log Management "
              "Documentation",
        sitemaps=("https://docs.datadoghq.com/en/sitemap.xml",),
        keep_re=r"^https://docs\.datadoghq\.com/"
                r"(tracing|ddsql_reference|ddsql_editor|logs|events|opentelemetry)(/|$)",
        md_suffix=True,
        prefer=r"/(tracing/trace_explorer|tracing/glossary|tracing/trace_pipeline"
               r"|ddsql_reference|ddsql_editor|logs/explorer|logs/log_configuration"
               r"|events)",
        drop_re=r"/(ddsql_reference/data_directory|tracing/trace_collection/"
                r"(compatibility_requirements|library_config|automatic_instrumentation)"
                r"|tracing/guide/setting_primary_tags|integrations)/",
        cap=450, source_url="https://docs.datadoghq.com/tracing/trace_explorer/",
        license="\u00a9 Datadog, Inc.",
    ),
    DocSource(
        key="flink", company="Apache Flink", method="sitemap",
        title="Apache Flink Documentation (stable)",
        sitemaps=("https://nightlies.apache.org/flink/flink-docs-stable/en/sitemap.xml",),
        keep_re=r"nightlies\.apache\.org/flink/.+/docs/.+",
        prefer=r"/docs/(dev/table|dev/table/sql|dev/table/functions)",
        cap=300, source_url="https://nightlies.apache.org/flink/flink-docs-stable/",
        license="Apache-2.0 \u2014 \u00a9 The Apache Software Foundation",
    ),
    # --- SQL dialects: Oracle SQL --------------------------------------------
    # The book landing page is a thin shell; the full page set is enumerated by
    # the DITA-generated ``toc.htm`` (one .html per statement/function/concept).
    DocSource(
        key="oracle-sql", company="Oracle", method="toc",
        title="Oracle Database SQL Language Reference (26ai)",
        seeds=("https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/toc.htm",),
        prefix="https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/",
        keep_re=r"/sqlrf/[^/]+\.html$",
        drop_re=r"/index\.html$",
        cap=800,
        source_url="https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/index.html",
        license="\u00a9 Oracle Corporation",
    ),
    # --- SQL dialects: SAP HANA SQL ------------------------------------------
    # NOTE: the SAP Help Portal is a client-rendered Vue SPA with an obscured
    # content API and no server-side rendering (not even for crawler UAs), so
    # HTTP-based discovery/extraction yields no content. Registered here so the
    # collection definition is complete; import currently produces no file.
    DocSource(
        key="saphana-sql", company="SAP", method="pages",
        title="SAP HANA SQL Reference Guide",
        pages=("https://help.sap.com/docs/SAP_HANA_PLATFORM/4fe29514fd584807ac9f2a04f6754767/2969da89b87f4abd85fd0b5f9f5bc395.html",),
        cap=50,
        source_url="https://help.sap.com/docs/SAP_HANA_PLATFORM/4fe29514fd584807ac9f2a04f6754767/2969da89b87f4abd85fd0b5f9f5bc395.html",
        license="\u00a9 SAP SE",
    ),
    # --- Source Systems Knowledge: ERP source-system table references --------
    DocSource(
        key="oracle-tables", company="Oracle", method="pages",
        collection="Source Systems Knowledge",
        title="Oracle Fusion Cloud SCM \u2014 Order Management Interface Tables",
        pages=("https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26c/oedsc/dooorderheadersallint-24219.html",),
        cap=50,
        source_url="https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26c/oedsc/dooorderheadersallint-24219.html",
        license="\u00a9 Oracle Corporation",
    ),
    DocSource(
        key="sap-tables", company="SAP", method="pages",
        collection="Source Systems Knowledge",
        title="SAP ERP Data Dictionary \u2014 Tables",
        pages=("https://leanx.eu/sap/table/cdpos/",),
        cap=50,
        source_url="https://leanx.eu/en/sap/table/cdpos.html",
        license="Reference data \u00a9 the respective vendor; page \u00a9 LeanX",
    ),
    # Jira Data Center is the source system behind most ticket/ITSM process
    # mining, and it is the rare case where the *vendor* documents its own
    # tables: the `database-*` family names the columns of the change history,
    # the custom-field value tables, the OS_* workflow tables and the Embedded
    # Crowd user directories, i.e. exactly the joins an extraction has to get
    # right. Discovery is by sitemap rather than an enumerated list so a new
    # `database-…` page is picked up on the next run, and the two pages that
    # explain *how* the tables are reached come with it — the Entity Engine
    # (OfBiz) overview in `architecture-overview`, and `entity-properties`,
    # which is where entity data that has no column of its own is kept as JSON.
    #
    # Only Data Center has a database a reader can query; the Cloud docs are
    # REST-only, which is why nothing under /cloud/ is in this collection.
    DocSource(
        key="jira-db", company="Atlassian", method="sitemap",
        collection="Source Systems Knowledge",
        title="Jira Data Center \u2014 Database Schema & Data Model",
        filename="Jira Data Center Database Schema & Data Model.md",
        sitemaps=("https://developer.atlassian.com/server/jira/platform/sitemap.xml",),
        keep_re=r"^https://developer\.atlassian\.com/server/jira/platform/"
                r"(database-[a-z-]+|entity-properties|architecture-overview)/$",
        prefer=r"/database-schema/",
        cap=40,
        source_url="https://developer.atlassian.com/server/jira/platform/database-schema/",
        license="\u00a9 Atlassian Pty Ltd",
    ),
    # The data pipeline is the sanctioned alternative to reading those tables:
    # a scheduled CSV export of issues, issue fields, issue *history*, links,
    # SLA cycles and users, versioned by an export schema. The export-schema
    # page is the valuable half — it is a field-by-field description of the
    # extract, and `issue_history` is a Jira event log in all but name — and it
    # lives in the product docs rather than the developer site, so both are
    # taken. Their URLs are the `/display/<space>/<page+title>/` aliases, which
    # redirect to the current version's page id (…-1027142324.html): the id
    # changes with every Data Center release, the alias does not.
    DocSource(
        key="jira-data-pipeline", company="Atlassian", method="pages",
        collection="Source Systems Knowledge",
        title="Jira Data Center \u2014 Data Pipeline & Export Schema "
              "(issues, issue history, links, SLA cycles, users)",
        filename="Jira Data Center Data Pipeline & Export Schema.md",
        pages=(
            "https://confluence.atlassian.com/display/adminjiraserver/data+pipeline/",
            "https://confluence.atlassian.com/display/adminjiraserver/"
            "data+pipeline+export+schema/",
            "https://developer.atlassian.com/server/data-pipeline/about/about/",
            "https://developer.atlassian.com/server/data-pipeline/security/authentication/",
            "https://developer.atlassian.com/server/data-pipeline/rest/api-group-export/",
            "https://developer.atlassian.com/server/data-pipeline/rest/api-group-config/",
        ),
        cap=20,
        source_url="https://confluence.atlassian.com/display/adminjiraserver/"
                   "data+pipeline+export+schema/",
        license="\u00a9 Atlassian Pty Ltd",
    ),
    # --- Specifications: standards & ontologies ------------------------------
    # W3C Semantic Web standards (RDF + OWL) — server-rendered TR pages.
    DocSource(
        key="w3c-semweb", company="W3C", method="pages",
        collection="Specifications",
        title="W3C Semantic Web Standards \u2014 RDF & OWL",
        pages=(
            "https://www.w3.org/TR/rdf11-concepts/",
            "https://www.w3.org/TR/rdf12-concepts/",
            "https://www.w3.org/OWL/",
            "https://www.w3.org/TR/owl2-overview/",
            "https://www.w3.org/TR/owl2-primer/",
            "https://www.w3.org/TR/owl2-syntax/",
        ),
        cap=50, source_url="https://www.w3.org/standards/semanticweb/",
        license="\u00a9 W3C \u2014 W3C Document License",
    ),
    # OntoUML: the specification/catalogue is authored as Sphinx (.rst) + README.
    DocSource(
        key="ontouml", company="OntoUML", method="git",
        collection="Specifications",
        title="OntoUML Specification & Pattern Catalogue",
        repo="https://github.com/OntoUML/OntoUML",
        file_globs=("*.md", "*.rst"),
        source_url="https://github.com/OntoUML/OntoUML",
        license="\u00a9 OntoUML / NEMO",
    ),
    # BFO (Basic Formal Ontology): README + release notes (canonical artifact is bfo.owl).
    DocSource(
        key="bfo", company="BFO", method="git",
        collection="Specifications",
        title="Basic Formal Ontology (BFO)",
        repo="https://github.com/bfo-ontology/bfo",
        file_globs=("*.md",),
        source_url="https://github.com/bfo-ontology/bfo",
        license="\u00a9 BFO project (CC BY)",
    ),
    # gist upper ontology (Semantic Arts) — landing/overview page.
    DocSource(
        key="gist", company="Semantic Arts", method="pages",
        collection="Specifications",
        title="gist \u2014 Upper Ontology for the Enterprise",
        pages=("https://www.semanticarts.com/gist/",),
        cap=50, source_url="https://www.semanticarts.com/gist/",
        license="\u00a9 Semantic Arts (gist released under CC BY)",
    ),
    # --- Specifications: data contracts & data products (Bitol / LF AI & Data) -
    # Both Bitol sites are mkdocs builds of the checkouts below \u2014 build_docs.sh
    # copies the root markdown into docs/ and renders one page per example YAML \u2014
    # so ingesting the repo yields the hosted pages verbatim (cited by their site
    # URL) plus the normative JSON Schema, which the site does not publish.
    # Superseded schema versions are dropped; only the latest is kept.
    DocSource(
        key="odcs", company="Bitol", method="git",
        collection="Specifications",
        title="Open Data Contract Standard (ODCS) v3.1.0 \u2014 Specification, "
              "JSON Schema & Examples",
        filename="Open Data Contract Standard (ODCS).md",
        repo="https://github.com/bitol-io/open-data-contract-standard",
        branch="main",
        clone_dir="reference/bitol/open-data-contract-standard",
        file_globs=("*.md", "*.yaml", "*.json"),
        sitemaps=("https://bitol-io.github.io/open-data-contract-standard/"
                  "latest/sitemap.xml",),
        drop_re=r"^(AUTHORS|CONTRIBUTING|LICENSE|building-doc|history"
                r"|context7\.json|\.github/|src/|schema/odcs-json-schema-v)",
        prefer=r"^(README\.md|docs/(README|fundamentals|schema|references"
               r"|data-quality)\.md)",
        url_map=(
            ("README.md",
             "https://bitol-io.github.io/open-data-contract-standard/latest/home/"),
            ("docs/README.md",
             "https://bitol-io.github.io/open-data-contract-standard/latest/"),
            ("docs/examples/README.md",
             "https://bitol-io.github.io/open-data-contract-standard/latest/examples/"),
        ),
        cap=100,
        source_url="https://bitol-io.github.io/open-data-contract-standard/latest/",
        license="Apache-2.0 \u2014 \u00a9 Bitol / LF AI & Data Foundation",
    ),
    DocSource(
        key="odps", company="Bitol", method="git",
        collection="Specifications",
        title="Open Data Product Standard (ODPS) v1.0.0 \u2014 Specification, "
              "JSON Schema & Examples",
        filename="Open Data Product Standard (ODPS).md",
        repo="https://github.com/bitol-io/open-data-product-standard",
        branch="main",
        clone_dir="reference/bitol/open-data-product-standard",
        file_globs=("*.md", "*.yaml", "*.json"),
        sitemaps=("https://bitol-io.github.io/open-data-product-standard/"
                  "latest/sitemap.xml",),
        drop_re=r"^(AUTHORS|CONTRIBUTING|LICENSE|context7\.json|package\.json"
                r"|\.github/|scripts/|schema/odps-json-schema-v)",
        prefer=r"^(docs/README\.md|README\.md)",
        url_map=(
            ("README.md",
             "https://bitol-io.github.io/open-data-product-standard/latest/home/"),
            ("docs/README.md",
             "https://bitol-io.github.io/open-data-product-standard/latest/"),
            ("docs/examples/README.md",
             "https://bitol-io.github.io/open-data-product-standard/latest/examples/"),
        ),
        cap=60,
        source_url="https://bitol-io.github.io/open-data-product-standard/latest/",
        license="Apache-2.0 \u2014 \u00a9 Bitol / LF AI & Data Foundation",
    ),
    # Open Knowledge Format (OKF) \u2014 Google's proposal for shipping a knowledge
    # corpus as a directory of markdown files with YAML frontmatter, aimed at a
    # corpus that agents write and maintain rather than one authored once: the
    # frontmatter makes provenance, trust, freshness, lifecycle and attestation
    # first-class. It sits with ODCS/ODPS and Ossie \u2014 those standardise the
    # contract over data, the product around it and the semantic layer between
    # tools; OKF standardises the prose *about* them.
    #
    # The specification's canonical home is this repository. The copy under
    # ``okf/`` in ``GoogleCloudPlatform/knowledge-catalog`` is a frozen snapshot
    # its own README disowns \u2014 byte-identical to this text today, and guaranteed
    # not to be tomorrow.
    #
    # The four example bundles are taken with the spec because OKF is a
    # convention rather than a schema, so the worked corpora (acme_retail's
    # attested metrics, and the BigQuery public datasets modelled as tables,
    # joins and metrics) are where the conventions are actually pinned down.
    # The reference agent's prompts come too: they are the statement of how a
    # bundle is meant to be *written* by an agent, which is the format's whole
    # premise and appears nowhere in the specification.
    DocSource(
        key="okf", company="Google Cloud", method="git",
        collection="Specifications",
        title="Open Knowledge Format (OKF) v0.2 \u2014 Specification, Example "
              "Bundles & Reference-Agent Prompts",
        filename="Open Knowledge Format (OKF).md",
        repo="https://github.com/GoogleCloudPlatform/open-knowledge-format",
        branch="main",
        file_globs=("*.md",),
        drop_re=r"^(CONTRIBUTING|CODE_OF_CONDUCT|LICENSE)\.md$",
        prefer=r"^(SPEC|README)\.md$",
        cap=130,
        source_url="https://github.com/GoogleCloudPlatform/open-knowledge-format",
        license="Apache-2.0 \u2014 \u00a9 Google LLC",
    ),
    # HQDM — Matthew West's 4-dimensionalist data model, as implemented for the
    # UK Information Management Framework. The book is paywalled; these repos are
    # the open expression of the same entity-relationship model.
    DocSource(
        key="hqdm", company="HQDM", method="git",
        collection="Specifications",
        title="HQDM \u2014 High Quality Data Model (4-dimensionalist)",
        repo="https://github.com/gchq/HQDM",
        file_globs=("*.md",),
        source_url="https://github.com/gchq/HQDM",
        license="Apache-2.0 \u2014 \u00a9 Crown Copyright (GCHQ)",
    ),
    DocSource(
        key="magmacore", company="MagmaCore", method="git",
        collection="Specifications",
        title="Magma Core \u2014 HQDM/4D Linked-Data Reference Implementation",
        repo="https://github.com/gchq/MagmaCore",
        file_globs=("*.md",),
        source_url="https://github.com/gchq/MagmaCore",
        license="Apache-2.0 \u2014 \u00a9 Crown Copyright (GCHQ)",
    ),
    # OpenTelemetry — the normative definition of a trace: trace/span ids minted
    # by context propagation, the parent-child relation the tracing arrow is
    # read off, and span *links*, which are the observability world's answer to
    # "an event referencing more than one correlation value". The specification
    # repo is the normative text; the semantic conventions repo is what actually
    # names the attributes, so both are taken.
    DocSource(
        key="opentelemetry-spec", company="OpenTelemetry", method="git",
        collection="Specifications",
        title="OpenTelemetry Specification \u2014 Traces, Context Propagation, "
              "Metrics, Logs & Protocol",
        filename="OpenTelemetry Specification.md",
        repo="https://github.com/open-telemetry/opentelemetry-specification",
        file_globs=("*.md",),
        drop_re=r"^(CONTRIBUTING|CHANGELOG|CODE_OF_CONDUCT|README-|\.github/"
                r"|oteps/|internal/|spec-compliance-matrix)",
        prefer=r"^specification/(overview|trace/api|trace/sdk|context|logs|"
               r"common)",
        cap=200,
        source_url="https://opentelemetry.io/docs/specs/otel/",
        license="Apache-2.0 \u2014 \u00a9 The OpenTelemetry Authors",
    ),
    DocSource(
        key="opentelemetry-semconv", company="OpenTelemetry", method="git",
        collection="Specifications",
        title="OpenTelemetry Semantic Conventions",
        filename="OpenTelemetry Semantic Conventions.md",
        repo="https://github.com/open-telemetry/semantic-conventions",
        file_globs=("*.md",),
        drop_re=r"^(CONTRIBUTING|CHANGELOG|CODE_OF_CONDUCT|\.github/"
                r"|internal/|supplementary-guidelines/)",
        prefer=r"^docs/(general|http|database|messaging|rpc)/",
        cap=200,
        source_url="https://opentelemetry.io/docs/specs/semconv/",
        license="Apache-2.0 \u2014 \u00a9 The OpenTelemetry Authors",
    ),
    # Industrial Ontologies Foundry — the BFO-based (3D) counterpart, kept
    # alongside HQDM so the 3D/4D contrast is documented from both sides.
    DocSource(
        key="iof", company="Industrial Ontologies Foundry", method="git",
        collection="Specifications",
        title="Industrial Ontologies Foundry (IOF) \u2014 Core & Domain Ontologies",
        repo="https://github.com/iofoundry/ontology",
        file_globs=("*.md",),
        source_url="https://www.industrialontologies.org/",
        license="\u00a9 Industrial Ontologies Foundry / OAGi (CC BY)",
    ),
    # --- IDSA: the normative half of the data-spaces corpus -------------------
    # The position papers harvested by scripts/idsa-papers.py argue the case;
    # these two repos are what the argument resolves to. Both are published as
    # GitBook sites generated from markdown already in git, so the repo is the
    # better source (see the note on repo-backed doc sites in SOURCES.md \u00a73).
    # IDS-RAM 4.0 is the layered reference architecture \u2014 roles, the connector,
    # the five layers, certification \u2014 and is the document the papers page links
    # to instead of offering a PDF.
    DocSource(
        key="ids-ram", company="IDSA", method="git",
        collection="Specifications",
        title="IDS Reference Architecture Model (IDS-RAM) 4.0",
        filename="IDS Reference Architecture Model (IDS-RAM) 4.0.md",
        repo="https://github.com/International-Data-Spaces-Association/IDS-RAM_4_0",
        branch="main",
        file_globs=("*.md",),
        drop_re=r"^(CHANGELOG|CODE_OF_CONDUCT|CONTRIBUTING|LICENSE)",
        prefer=r"^(README\.md|documentation/[1-5]_)",
        cap=120,
        source_url="https://docs.internationaldataspaces.org/ids-knowledgebase/v/ids-ram-4/",
        license="CC BY 4.0 \u2014 \u00a9 International Data Spaces Association",
    ),
    # The Dataspace Protocol is the wire contract the RAM's connector speaks:
    # catalog, contract negotiation (ODRL) and transfer process. The JSON
    # Schemas, message examples and SHACL shapes are taken alongside the prose
    # because they, not the specification text, are what an implementation is
    # actually checked against \u2014 the same reason the Bitol JSON Schemas are held.
    DocSource(
        key="dataspace-protocol", company="IDSA", method="git",
        collection="Specifications",
        title="Dataspace Protocol (DSP) \u2014 Catalog, Contract Negotiation & "
              "Transfer Process, with JSON Schemas and SHACL Shapes",
        filename="Dataspace Protocol (DSP).md",
        repo="https://github.com/International-Data-Spaces-Association/ids-specification",
        branch="main",
        file_globs=("*.md", "*.json", "*.ttl"),
        drop_re=r"^(CONTRIBUTING|LICENSE|\.github/|CODE_OF_CONDUCT)",
        prefer=r"^(README\.md|SUMMARY\.md|model/|common/|catalog/catalog\.|"
               r"negotiation/contract\.|transfer/transfer\.)",
        cap=260,
        source_url="https://docs.internationaldataspaces.org/ids-knowledgebase/"
                   "dataspace-protocol",
        license="CC BY 4.0 / Apache-2.0 \u2014 \u00a9 International Data Spaces "
                "Association",
    ),
    # --- Philosophy: encyclopedia entries on time, persistence and process ---
    # The library argues about whether a thing stays the same thing through
    # change (bitemporal modelling, object-centric event data, 3D/4D upper
    # ontologies) while holding none of the philosophy that debate came from.
    # SEP and IEP are free, citable, and survey exactly the missing ground.
    DocSource(
        key="sep-temporality", company="Stanford Encyclopedia of Philosophy",
        method="pages", collection="Philosophy",
        title="SEP \u2014 Time, Persistence, Identity & Process",
        pages=(
            # identity over time / the 3D-4D debate
            "https://plato.stanford.edu/entries/identity-time/",
            "https://plato.stanford.edu/entries/temporal-parts/",
            "https://plato.stanford.edu/entries/identity/",
            "https://plato.stanford.edu/entries/identity-personal/",
            "https://plato.stanford.edu/entries/identity-relative/",
            "https://plato.stanford.edu/entries/ordinary-objects/",
            "https://plato.stanford.edu/entries/material-constitution/",
            "https://plato.stanford.edu/entries/sortals/",
            "https://plato.stanford.edu/entries/essential-accidental/",
            "https://plato.stanford.edu/entries/intrinsic-extrinsic/",
            "https://plato.stanford.edu/entries/substance/",
            "https://plato.stanford.edu/entries/supervenience/",
            "https://plato.stanford.edu/entries/vagueness/",
            # mereology
            "https://plato.stanford.edu/entries/mereology/",
            "https://plato.stanford.edu/entries/location-mereology/",
            # time
            "https://plato.stanford.edu/entries/time/",
            "https://plato.stanford.edu/entries/presentism/",
            "https://plato.stanford.edu/entries/mctaggart/",
            "https://plato.stanford.edu/entries/spacetime-bebecome/",
            "https://plato.stanford.edu/entries/consciousness-temporal/",
            "https://plato.stanford.edu/entries/logic-temporal/",
            # change, events, process
            "https://plato.stanford.edu/entries/change/",
            "https://plato.stanford.edu/entries/events/",
            "https://plato.stanford.edu/entries/process-philosophy/",
            "https://plato.stanford.edu/entries/causation-metaphysics/",
            "https://plato.stanford.edu/entries/causation-physics/",
            "https://plato.stanford.edu/entries/wesley-salmon/",
            # figures: presocratics through the process tradition
            "https://plato.stanford.edu/entries/heraclitus/",
            "https://plato.stanford.edu/entries/parmenides/",
            "https://plato.stanford.edu/entries/aristotle-metaphysics/",
            "https://plato.stanford.edu/entries/aristotle-categories/",
            "https://plato.stanford.edu/entries/aristotle-natphil/",
            "https://plato.stanford.edu/entries/heidegger/",
            "https://plato.stanford.edu/entries/whitehead/",
            "https://plato.stanford.edu/entries/bergson/",
            "https://plato.stanford.edu/entries/deleuze/",
            "https://plato.stanford.edu/entries/david-lewis/",
            "https://plato.stanford.edu/entries/lewis-metaphysics/",
        ),
        cap=60, source_url="https://plato.stanford.edu/",
        license="\u00a9 the individual authors / Metaphysics Research Lab, "
                "Stanford University \u2014 free to read",
    ),
    DocSource(
        key="iep-temporality", company="Internet Encyclopedia of Philosophy",
        method="pages", collection="Philosophy",
        title="IEP \u2014 Time, Persistence & Process",
        pages=(
            "https://iep.utm.edu/time/",
            "https://iep.utm.edu/person-i/",
            "https://iep.utm.edu/processp/",
            "https://iep.utm.edu/heraclit/",
            "https://iep.utm.edu/parmen/",
            "https://iep.utm.edu/differential-ontology/",
            "https://iep.utm.edu/substance/",
            "https://iep.utm.edu/aristotle-metaphysics/",
            "https://iep.utm.edu/whitehead/",
            "https://iep.utm.edu/bergson/",
            "https://iep.utm.edu/heidegge/",
            "https://iep.utm.edu/deleuze/",
        ),
        cap=40, source_url="https://iep.utm.edu/",
        license="\u00a9 the individual authors / IEP \u2014 free to read",
    ),
    # --- Apache Software Foundation: the data/cloud project documentation ----
    # Selected and probed by ``scripts/apache-projects.py`` (see SOURCES.md §3b
    # for why the ASF's own category listing is not sufficient to enumerate
    # them, and ``imports/apache-doc-probe.csv`` for the evidence behind each
    # method below). Apache Flink and DataFusion are registered further up,
    # from before this section existed.
    #
    # Apache Ossie is the odd one out and comes first because it is a
    # *specification*, not a product: a vendor-neutral YAML format for metrics,
    # dimensions and their relationships, contributed to the incubator in
    # 2026-07 as the former Open Semantic Interchange (OSI, started by
    # Snowflake). It is the semantic-layer counterpart to the Bitol data
    # contract/product standards already held, and it belongs in
    # ``Specifications/`` with them. The site is five pages plus a news
    # archive; the specification, its JSON Schema, the expression language, the
    # ontology and the per-vendor converters all live in the repo, so the repo
    # is what is read. The converter READMEs earn their place: each is a
    # documented mapping between Ossie and one vendor's semantic model
    # (Databricks metric views, dbt, GoodData, Honeydew, NVIDIA GSF, Omni,
    # Snowflake, Salesforce, Polaris), which is the interoperability claim
    # stated in concrete terms. Their tests and lockfiles are not.
    _asf(
        "ossie", "Apache Ossie",
        "Apache Ossie (incubating) \u2014 Open Semantic Interchange: "
        "Specification, Expression Language, Ontology, JSON Schema & Converters",
        method="git", collection="Specifications",
        filename="Apache Ossie (Open Semantic Interchange).md",
        repo="https://github.com/apache/ossie", branch="main",
        file_globs=("*.md", "*.json", "*.yaml"),
        drop_re=r"(?:^\.github/|/tests?/|/__snapshots__/|uv\.lock|"
                r"^cli/go\.|\.asf\.yaml)",
        prefer=r"^(README\.md|core-spec/|ontology/|docs/|examples/|"
               r"converters/README\.md|ROADMAP\.md)",
        cap=80, source_url="https://ossie.apache.org/spec/",
        license=ASF_LICENSE + " (incubating)",
    ),
    # Table formats, catalogs and the columnar file formats under them.
    _asf("iceberg", "Apache Iceberg", "Apache Iceberg Documentation",
         docs="/docs/latest/", cap=350),
    _asf("hudi", "Apache Hudi", "Apache Hudi Documentation",
         archived=True, cap=350),
    _asf("paimon", "Apache Paimon", "Apache Paimon Documentation",
         method="crawl", cap=250),
    # Incubating projects are reachable at both ``<key>.incubator.apache.org``
    # (what the podlings register lists) and the short ``<key>.apache.org``
    # their own sitemaps declare. The short form is used here: it is the name
    # the site self-identifies by, and the one that survives graduation.
    _asf("xtable", "Apache XTable", "Apache XTable (incubating) Documentation",
         archived=True, cap=100),
    _asf("polaris", "Apache Polaris",
         "Apache Polaris \u2014 Iceberg REST Catalog Documentation",
         docs="/releases/", version_pick=r"/releases/(?P<ver>\d+\.\d+\.\d+)/",
         cap=150),
    # ``/docs/latest/`` exists but is a 300-byte redirect stub rather than a
    # served tree, so the release directories are what the sitemap offers.
    _asf("gravitino", "Apache Gravitino", "Apache Gravitino Documentation",
         version_pick=r"/docs/(?P<ver>\d+\.\d+\.\d+(?:-incubating)?)/",
         cap=350),
    _asf("amoro", "Apache Amoro",
         "Apache Amoro (incubating) \u2014 Lakehouse Management Documentation",
         method="crawl", docs="/docs/latest/", cap=120),
    _asf("orc", "Apache ORC", "Apache ORC Documentation",
         method="crawl", cap=120),
    _asf("parquet", "Apache Parquet", "Apache Parquet Documentation",
         cap=120),
    _asf("avro", "Apache Avro", "Apache Avro Documentation",
         sitemaps=("https://avro.apache.org/en/sitemap.xml",),
         version_pick=r"/docs/(?P<ver>\d+\.\d+\.\d+)/",
         drop=r"/api-(?:c|c\+\+|cpp|csharp|py|rust)/", cap=200),
    _asf("arrow", "Apache Arrow",
         "Apache Arrow Documentation (format, C++, Python, Java, Go, Rust)",
         method="crawl",
         drop=r"/(?:_sources|_static|genindex|py-modindex|search)"
              r"|/(?:generated|api)/", cap=350),
    # Query engines, warehouses and OLAP stores.
    _asf("calcite", "Apache Calcite",
         "Apache Calcite \u2014 SQL Parser, Optimizer & Adapters Documentation",
         method="crawl", cap=150),
    _asf("hive", "Apache Hive", "Apache Hive Documentation",
         docs="/docs/latest/", cap=300),
    _asf("impala", "Apache Impala", "Apache Impala Documentation",
         method="crawl", cap=300),
    _asf("drill", "Apache Drill", "Apache Drill Documentation",
         method="crawl", cap=350),
    _asf("doris", "Apache Doris", "Apache Doris Documentation",
         version_pick=r"/docs/(?P<ver>\d+\.[\dx]+)/", drop=r"/docs/dev/",
         prefer=r"/sql-manual/", cap=400),
    _asf("kylin", "Apache Kylin", "Apache Kylin Documentation",
         archived=True, cap=250),
    _asf("druid", "Apache Druid", "Apache Druid Documentation",
         docs="/docs/latest/", cap=350),
    # GitBook publishes a sitemap *index* whose other members are frozen
    # release-N.N.N mirrors of the same pages; read only the live one.
    _asf("pinot", "Apache Pinot", "Apache Pinot Documentation",
         host="docs.pinot.apache.org", docs="/",
         sitemaps=("https://docs.pinot.apache.org/sitemap-pages.xml",),
         cap=400),
    _asf("kudu", "Apache Kudu", "Apache Kudu Documentation",
         method="crawl", cap=150),
    _asf("cloudberry", "Apache Cloudberry",
         "Apache Cloudberry (incubating) Documentation \u2014 MPP analytical "
         "database (Greenplum lineage)",
         version_pick=r"/docs/(?P<ver>\d+\.[\dx]+)/", md_suffix=True, cap=350),
    _asf("asterixdb", "Apache AsterixDB",
         "Apache AsterixDB \u2014 SQL++ and the Semistructured BDMS",
         method="crawl", autoindex=True, drop=r"\?C=", cap=150),
    _asf("wayang", "Apache Wayang",
         "Apache Wayang \u2014 Cross-Platform Data Processing Documentation",
         archived=True, cap=100),
    # Gluten publishes no doc site — `/docs/` is a plain httpd autoindex of
    # per-release directories, so the crawl descends into the newest one and
    # skips the column-sort links the autoindex adds.
    _asf("gluten", "Apache Gluten",
         "Apache Gluten \u2014 Native Execution for Spark Documentation",
         method="crawl", autoindex=True, drop=r"\?C=", cap=200),
    _asf("systemds", "Apache SystemDS",
         "Apache SystemDS \u2014 Declarative ML Pipelines (DML) Documentation",
         method="crawl", autoindex=True, drop=r"\?C=", cap=150),
    _asf("spark", "Apache Spark", "Apache Spark Documentation",
         method="crawl", docs="/docs/latest/",
         drop=r"/api/|/docs/latest/(?:api|generated)/", cap=350),
    # Graph, geospatial and search.
    # `/docs/current/` is an index whose links are script-generated, so a crawl
    # finds nothing to follow; the manual is a few enormous single-page books
    # (the reference alone is ~290 KB of prose), so they are named directly.
    _asf("tinkerpop", "Apache TinkerPop",
         "Apache TinkerPop \u2014 Gremlin Reference Documentation",
         method="pages",
         pages=("https://tinkerpop.apache.org/docs/current/reference/",
                "https://tinkerpop.apache.org/docs/current/tutorials/"
                "getting-started/",
                "https://tinkerpop.apache.org/docs/current/tutorials/"
                "the-gremlin-console/",
                "https://tinkerpop.apache.org/docs/current/tutorials/"
                "gremlin-language-variants/",
                "https://tinkerpop.apache.org/docs/current/recipes/",
                "https://tinkerpop.apache.org/docs/current/upgrade/",
                "https://tinkerpop.apache.org/docs/current/dev/provider/"),
         cap=20, source_url="https://tinkerpop.apache.org/docs/current/"),
    _asf("hugegraph", "Apache HugeGraph", "Apache HugeGraph Documentation",
         sitemaps=("https://hugegraph.apache.org/en/sitemap.xml",), cap=200),
    _asf("age", "Apache AGE",
         "Apache AGE \u2014 Graph Extension for PostgreSQL",
         method="crawl", docs="/age-manual/master/", cap=100),
    _asf("sedona", "Apache Sedona",
         "Apache Sedona \u2014 Cluster Computing for Geospatial Data",
         method="crawl", docs="/latest/", cap=300),
    _asf("graphar", "Apache GraphAr",
         "Apache GraphAr (incubating) \u2014 Graph File Format Documentation",
         archived=True, cap=100),
    # GeaFlow's sitemap declares apache.github.io as its host; only the paths
    # are usable (see ``_rewrite_host``).
    _asf("geaflow", "Apache GeaFlow",
         "Apache GeaFlow (incubating) \u2014 Streaming Graph Computing",
         rewrite_host="geaflow.apache.org", archived=True, cap=150),
    # Operational stores: wide-column, key-value, time-series and consensus.
    # HBase and Phoenix publish a single ``llms-full.txt`` covering the whole
    # book (3.5 MB and 1.1 MB), which is both the completest and the cheapest
    # route — one request instead of a few hundred.
    _asf("hbase", "Apache HBase", "Apache HBase Reference Guide",
         method="llms_full", llms_url="https://hbase.apache.org/llms-full.txt",
         source_url="https://hbase.apache.org/book.html"),
    _asf("phoenix", "Apache Phoenix",
         "Apache Phoenix \u2014 SQL over HBase Documentation",
         method="llms_full",
         llms_url="https://phoenix.apache.org/llms-full.txt",
         source_url="https://phoenix.apache.org/docs/"),
    # The sitemap still lists the 4.x path layout (`getting_started/`,
    # `architecture/snitch`) under `/doc/latest/`, which 5.x reorganised into
    # `getting-started/` and `managing/operating/` — 219 of its 230 URLs 404.
    # Crawling `latest` reads the layout the site actually has.
    _asf("cassandra", "Apache Cassandra", "Apache Cassandra Documentation",
         method="crawl", docs="/doc/latest/", cap=400),
    _asf("accumulo", "Apache Accumulo", "Apache Accumulo Documentation",
         method="crawl", docs="/docs/2.x/", cap=200),
    _asf("ignite", "Apache Ignite",
         "Apache Ignite 2 & 3 Documentation (distributed SQL database)",
         cap=400),
    _asf("geode", "Apache Geode", "Apache Geode Documentation",
         method="crawl", cap=250),
    _asf("couchdb", "Apache CouchDB", "Apache CouchDB Documentation",
         method="crawl", host="docs.couchdb.org", docs="/en/stable/",
         drop=r"/_sources/|/genindex|/search\.html", cap=300),
    _asf("kvrocks", "Apache Kvrocks",
         "Apache Kvrocks \u2014 RocksDB-backed Redis-protocol Store",
         archived=True, cap=100),
    _asf("iotdb", "Apache IoTDB", "Apache IoTDB User Guide",
         docs="/UserGuide/", version_pick=r"/UserGuide/(?P<ver>V[\d.x]+)/",
         cap=350),
    _asf("tsfile", "Apache TsFile",
         "Apache TsFile \u2014 Time-Series File Format Documentation",
         docs="/UserGuide/", cap=120),
    _asf("ozone", "Apache Ozone", "Apache Ozone Documentation",
         version_pick=r"/docs/(?P<ver>\d+\.\d+\.\d+)/",
         drop=r"/docs/(?:next|edge)/", cap=300),
    # The sitemap advertises a restructured tree (`admin-ops/…`) that does not
    # exist yet — every one of those URLs 404s. The published manual is still
    # the flat set of `zookeeper*.html` pages under the `current` alias.
    _asf("zookeeper", "Apache ZooKeeper", "Apache ZooKeeper Documentation",
         method="crawl", docs="/doc/current/", cap=80),
    _asf("derby", "Apache Derby", "Apache Derby Documentation",
         method="crawl", host="db.apache.org", docs="/derby/docs/",
         autoindex=True, drop=r"\?C=", cap=700),
    # Streaming, messaging and shuffle.
    # Kafka's Hugo rebuild left `/documentation/` as an empty redirect stub and
    # moved the manual to a per-release tree, publishing every release since
    # 0.8 side by side. The version segment is a compact code, not a number:
    # `08` and `0100` are 0.8 and 0.10.0, while current releases are two digits
    # (`40` = 4.0). Restricting to two digits therefore selects the modern
    # scheme, and the highest of those is the current release.
    _asf("kafka", "Apache Kafka", "Apache Kafka Documentation",
         keep_re=r"^https?://kafka\.apache\.org/\d{2}/",
         version_pick=r"^https?://kafka\.apache\.org/(?P<ver>\d{2})/",
         cap=250, source_url="https://kafka.apache.org/documentation/"),
    _asf("pulsar", "Apache Pulsar", "Apache Pulsar Documentation",
         version_pick=r"/docs/(?P<ver>\d+\.\d+\.x)/",
         drop=r"/docs/next/", cap=400),
    _asf("bookkeeper", "Apache BookKeeper", "Apache BookKeeper Documentation",
         version_pick=r"/docs/(?P<ver>\d+\.\d+\.\d+)/", cap=200),
    # RocketMQ ships the Docusaurus scaffold's placeholder host in its sitemap.
    _asf("rocketmq", "Apache RocketMQ", "Apache RocketMQ Documentation",
         rewrite_host="rocketmq.apache.org", archived=True, cap=250),
    _asf("fluss", "Apache Fluss",
         "Apache Fluss \u2014 Streaming Storage Documentation",
         version_pick=r"/docs/(?P<ver>\d+\.\d+)/", drop=r"/docs/next/",
         cap=250),
    _asf("samza", "Apache Samza", "Apache Samza Documentation",
         docs="/learn/documentation/", cap=200),
    _asf("storm", "Apache Storm", "Apache Storm Documentation",
         method="crawl", docs="/releases/current/", cap=200),
    _asf("beam", "Apache Beam", "Apache Beam Documentation",
         docs="/documentation/", cap=400),
    _asf("seatunnel", "Apache SeaTunnel", "Apache SeaTunnel Documentation",
         archived=True, cap=350),
    _asf("inlong", "Apache InLong", "Apache InLong Documentation",
         version_pick=r"/docs/(?P<ver>\d+\.\d+\.\d+)/",
         drop=r"/docs/next/", cap=300),
    _asf("eventmesh", "Apache EventMesh", "Apache EventMesh Documentation",
         archived=True, drop=r"/docs/v\d", cap=200),
    _asf("celeborn", "Apache Celeborn",
         "Apache Celeborn \u2014 Remote Shuffle Service Documentation",
         method="crawl", cap=120),
    _asf("uniffle", "Apache Uniffle",
         "Apache Uniffle \u2014 Remote Shuffle Service Documentation",
         archived=True, cap=80),
    # Pipelines, schedulers, gateways and notebooks.
    _asf("airflow", "Apache Airflow", "Apache Airflow Documentation",
         method="crawl", docs="/docs/apache-airflow/stable/",
         drop=r"/_api/|/_modules/|/_sources/|/genindex|/py-modindex", cap=400),
    # No DolphinScheduler entry: its site is a client-rendered SPA that answers
    # every path — including the ones its own sitemap lists — with the same
    # 3.6 KB shell and an HTTP 404, so there is nothing to extract. Its manual
    # is markdown in apache/dolphinscheduler-website if it is ever wanted.
    _asf("hop", "Apache Hop", "Apache Hop Documentation",
         method="crawl", docs="/manual/latest/", cap=350),
    _asf("zeppelin", "Apache Zeppelin", "Apache Zeppelin Documentation",
         method="crawl", docs="/docs/latest/", cap=200),
    _asf("livy", "Apache Livy", "Apache Livy Documentation",
         method="crawl", docs="/docs/latest/", cap=80),
    # kyuubi.apache.org publishes only news and release notes; the manual is
    # hosted on Read the Docs, which is what the project's own docs link points
    # at.
    _asf("kyuubi", "Apache Kyuubi",
         "Apache Kyuubi \u2014 Multi-tenant SQL Gateway Documentation",
         method="crawl", host="kyuubi.readthedocs.io", docs="/en/master/",
         drop=r"/_sources/|/genindex|/search\.html|/_modules/", cap=250),
    _asf("linkis", "Apache Linkis", "Apache Linkis Documentation",
         docs="/docs/latest/", cap=250),
    _asf("streampark", "Apache StreamPark", "Apache StreamPark Documentation",
         archived=True, cap=150),
    _asf("streampipes", "Apache StreamPipes", "Apache StreamPipes Documentation",
         archived=True, version_pick=r"/docs/(?P<ver>\d+\.\d+\.\d+)/",
         cap=250),
    _asf("nifi", "Apache NiFi", "Apache NiFi Documentation",
         method="crawl", docs="/documentation/", cap=250),
    # Governance, security, storage abstraction and observability.
    _asf("opendal", "Apache OpenDAL",
         "Apache OpenDAL \u2014 Unified Data Access Layer Documentation",
         method="llms_full",
         llms_url="https://opendal.apache.org/llms-full.txt",
         source_url="https://opendal.apache.org/docs/"),
    _asf("skywalking", "Apache SkyWalking",
         "Apache SkyWalking \u2014 Observability & Tracing Documentation",
         docs="/docs/main/", version_pick=r"/(?P<ver>v\d+\.\d+\.\d+)/",
         cap=350),
    _asf("knox", "Apache Knox",
         "Apache Knox \u2014 Hadoop Gateway User Guide",
         method="pages",
         pages=("https://knox.apache.org/books/knox-2-1-0/user-guide.html",
                "https://knox.apache.org/books/knox-2-0-0/user-guide.html",
                "https://knox.apache.org/books/knox-2-1-0/dev-guide.html"),
         cap=10, source_url="https://knox.apache.org/books/"),
    # Cloud / cluster infrastructure.
    _asf("cloudstack", "Apache CloudStack", "Apache CloudStack Documentation",
         method="crawl", host="docs.cloudstack.apache.org", docs="/en/latest/",
         drop=r"/_sources/|/genindex|/search\.html", cap=350),
    _asf("yunikorn", "Apache YuniKorn",
         "Apache YuniKorn \u2014 Kubernetes Resource Scheduler Documentation",
         archived=True, cap=250),
    _asf("fory", "Apache Fory",
         "Apache Fory \u2014 Serialisation Framework Documentation",
         archived=True, cap=250),
    # Data visualisation and analytics front-ends.
    # Superset splits its manual into three trees and versions each of them,
    # serving the current release unversioned.
    _asf("superset", "Apache Superset", "Apache Superset Documentation",
         keep_re=r"^https://superset\.apache\.org/(?:user|admin|developer)-docs/",
         drop=r"-docs/\d+\.\d+\.\d+/|/developer-docs/api",
         prefer=r"/(?:user|admin)-docs/", cap=350,
         source_url="https://superset.apache.org/user-docs/intro"),
    _asf("echarts", "Apache ECharts", "Apache ECharts Handbook",
         method="crawl", docs="/handbook/en/", cap=250),
    # Texera generates its site on a staging host and its sitemap says so.
    _asf("texera", "Apache Texera",
         "Apache Texera (incubating) \u2014 Collaborative Dataflow Workflows",
         rewrite_host="texera.apache.org",
         version_pick=r"/docs/(?P<ver>v\d+\.\d+\.\d+)/", cap=200),
    _asf("hamilton", "Apache Hamilton",
         "Apache Hamilton (incubating) \u2014 Dataflow Definition Framework",
         method="llms_full",
         llms_url="https://hamilton.apache.org/llms-full.txt",
         source_url="https://hamilton.apache.org/"),
]

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def _get(session, url, as_text=False):
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text if as_text else r


def _p_chars(node) -> int:
    return sum(len(p.text_content()) for p in node.xpath(".//p"))


def _densest(node):
    """The smallest node still holding *all* of ``node``'s paragraph text.

    A CSS-in-JS site names every wrapper with a build-generated hash — Atlassian's
    developer docs are ``sc-dfRKBO hSAwOa`` and ``css-1xjox7o`` all the way down,
    with no ``<article>``, no ``<main>`` and no id — so the picker below
    recognises nothing and falls through to ``<body>``, which imports the site
    header, the documentation tree and the footer onto every page. Paragraph text
    is the signal the picker already ranks candidates by, and descending while it
    is unchanged locates the wrapper the prose sits in without naming a class
    that the next deploy renames.
    """
    while (total := _p_chars(node)):
        for child in node.iterchildren():
            if isinstance(child.tag, str) and _p_chars(child) == total:
                node = child
                break
        else:
            break
    return node


def _pick_content(doc):
    cands = doc.xpath(
        '//article | //main | //div[@role="main"] | '
        '//div[contains(@class,"prose") or contains(@class,"markdown") or '
        'contains(@class,"theme-doc-markdown") or contains(@class,"md-content") or '
        'contains(@class,"document") or contains(@class,"body") or '
        'contains(@class,"content")]'
    )
    cands = [c for c in cands if _p_chars(c) > 0]
    if cands:
        return max(cands, key=_p_chars)
    body = doc.xpath("//body")
    return _densest(body[0]) if body else doc


def _title_of(doc, fallback="") -> str:
    for h in doc.xpath("//h1"):
        t = re.sub(r"\s+", " ", h.text_content()).strip()
        if t:
            return t
    t = (doc.xpath("//title/text()") or [fallback])[0]
    return re.sub(r"\s*[|\u2013\u2014]\s.*$", "", t).strip() or fallback


def _order(urls, prefer: str, drop: str, cap: int) -> list[str]:
    if drop:
        d = re.compile(drop)
        urls = [u for u in urls if not d.search(u)]
    urls = sorted(dict.fromkeys(urls))
    if prefer:
        pr = re.compile(prefer)
        preferred = [u for u in urls if pr.search(u)]
        rest = [u for u in urls if not pr.search(u)]
        urls = preferred + rest
    return urls[:cap]


# --- discovery -------------------------------------------------------------

def _sitemap_locs(session, sitemaps, _depth: int = 0) -> list[str]:
    """Every ``<loc>`` in the given sitemaps, following sitemap *indexes*.

    A ``<sitemapindex>`` lists further sitemaps rather than pages, so reading
    only the top level yields the child sitemap URLs — which pass the page
    filter for nothing and make a site look like it publishes no docs at all.

    ``<loc>`` is *required* by the sitemap protocol to be an absolute URL, and
    plenty of generators emit a site-relative path anyway (Hugo behind a
    ``baseURL`` of ``/``, which is how Avro, Cassandra, Beam and Parquet
    publish theirs). Both the entries and any nested sitemap reference are
    therefore resolved against the sitemap's own URL — otherwise a
    host-anchored ``keep_re`` matches nothing and the site reads as
    undocumented. A literal ``None`` is dropped: some generators write one per
    page when the template variable is unset, producing a well-formed sitemap
    in which every entry is the string "None".
    """
    out: list[str] = []
    for sm in sitemaps:
        try:
            txt = _get(session, sm, as_text=True)
        except Exception as exc:
            print(f"    ! sitemap {sm}: {exc}", file=sys.stderr)
            continue
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", txt)
        # normalize protocol-relative (//host/...) and site-relative (/path) URLs
        locs = [("https:" + l if l.startswith("//") else urljoin(sm, l))
                for l in locs if l and l != "None"]
        if "<sitemapindex" in txt[:2000] and _depth < 2:
            out.extend(_sitemap_locs(session, tuple(locs), _depth + 1))
            continue
        out.extend(locs)
    return out


def _rewrite_host(urls: list[str], host: str) -> list[str]:
    """Move every URL onto ``host``, keeping its path.

    A sitemap can name a host that does not serve the site. Two ways this
    happens in practice, both silent: a Docusaurus site shipped with the
    scaffold's placeholder ``url`` (``your-docusaurus-test-site.com``, which is
    what Ambari and RocketMQ publish), and a site generated on a staging host
    (``<project>.staged.apache.org``) whose sitemap keeps that name. The paths
    are correct in both cases, so the fix is to re-point them.
    """
    out = []
    for u in urls:
        parts = urlsplit(u)
        out.append(urlunsplit(("https", host, parts.path, parts.query, "")))
    return out


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", v)) or (0,)


def _autoindex_latest(session, index_url: str) -> str:
    """Resolve the newest release directory listed by an httpd autoindex.

    Several ASF projects publish no doc *site* at all: ``/docs/`` is mod_autoindex
    listing one directory per release (Derby, AsterixDB, SystemDS, Gluten). A
    crawl rooted there follows only sibling listings, so the import silently
    yields a table of contents of version numbers and no documentation — 19
    "pages" of 11 KB in Derby's case. Reading the listing and descending into the
    highest version gets the manual, and re-reading it on each run is what keeps
    the entry from being pinned to whatever release was current the day it was
    written.
    """
    doc = H.fromstring(_get(session, index_url).content)
    doc.make_links_absolute(index_url)
    versions = {}
    for a in doc.xpath("//a[@href]"):
        href = a.get("href").split("#")[0].split("?")[0]
        if not href.startswith(index_url) or href == index_url:
            continue
        tail = href[len(index_url):].strip("/")
        if re.fullmatch(r"v?\d+(?:\.\d+)*(?:-incubating)?", tail):
            versions[tail] = href.rstrip("/") + "/"
    if not versions:
        return index_url
    newest = max(versions,
                 key=lambda v: _version_key(v.lstrip("v").split("-")[0]))
    print(f"    autoindex: newest of {len(versions)} release dirs is {newest}")
    return versions[newest]


def _pick_latest_version(urls: list[str], pattern: str) -> list[str]:
    """Keep only the newest release of a version-partitioned doc site.

    Apache projects publish every release side by side (``/docs/1.5.0/``,
    ``/docs/1.6.0/``, …, and often ``/docs/next/``), so an unfiltered sitemap
    imports the same manual a dozen times over. Where the site offers a
    ``latest/`` alias the ``keep_re`` can just name it; where it does not, this
    picks the highest numbered version actually present — which is what keeps
    the entry from rotting at the project's next release. URLs the pattern does
    not match are kept as they are (a spec page that sits outside the versioned
    tree still belongs in the collection).
    """
    rx = re.compile(pattern)
    versions = {m.group("ver") for u in urls if (m := rx.search(u))}
    if not versions:
        return urls
    newest = max(versions, key=_version_key)
    out = []
    for u in urls:
        m = rx.search(u)
        if not m or m.group("ver") == newest:
            out.append(u)
    print(f"    version-pinned to {newest} (of {len(versions)} published)")
    return out


def _toc_locs(session, src: DocSource) -> list[str]:
    """Enumerate page URLs by parsing table-of-contents page(s) in ``seeds``.

    Unlike ``crawl`` (which fetches every page to discover links), this reads the
    links directly off a single generated TOC — ideal for DITA/Docbook-style
    books whose content pages only link prev/next.
    """
    keep = re.compile(src.keep_re) if src.keep_re else None
    out: list[str] = []
    for toc in src.seeds:
        try:
            r = _get(session, toc)
        except Exception as exc:
            print(f"    ! toc {toc}: {exc}", file=sys.stderr)
            continue
        doc = H.fromstring(r.content)
        doc.make_links_absolute(toc)
        for a in doc.xpath("//a[@href]"):
            h = a.get("href").split("#")[0].split("?")[0]
            if src.prefix and not h.startswith(src.prefix):
                continue
            if keep and not keep.search(h):
                continue
            out.append(h)
    return out


def _crawl(session, src: DocSource) -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    q = deque(src.seeds)
    drop = re.compile(src.drop_re) if src.drop_re else None
    # Bound discovery to the cap: query-string/anchor variants otherwise explode
    # the frontier on SSR sites (a small buffer lets the prefer-ordering choose).
    budget = src.cap if not src.prefer else src.cap * 2
    while q and len(order) < budget:
        url = q.popleft().split("#")[0].split("?")[0]
        if url in seen or not url.startswith(src.prefix):
            continue
        if drop and drop.search(url):
            continue
        seen.add(url)
        try:
            r = _get(session, url)
        except Exception:
            continue
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype:
            continue
        order.append(url)
        doc = H.fromstring(r.content)
        # Resolve against the URL that actually answered: stripping a trailing
        # slash (as this loop does when normalizing) makes the server redirect to
        # the directory, and resolving relative links against the pre-redirect
        # form silently lifts every one of them a directory too high.
        doc.make_links_absolute(r.url or url)
        # Frames count as links: DITA-generated manuals (Derby) publish a
        # frameset whose only outbound reference is `<frame src="toc.html">`, so
        # following anchors alone stops dead at the cover page.
        for el in doc.xpath("//a[@href] | //frame[@src] | //iframe[@src]"):
            h = (el.get("href") or el.get("src"))
            h = h.split("#")[0].split("?")[0].rstrip("/")
            if not h:
                continue
            if h.startswith(src.prefix) and h not in seen:
                q.append(h)
    return order


# --- per-method importers --------------------------------------------------

def _header(src: DocSource, n_pages: str) -> str:
    return (
        f"# {src.title}\n\n"
        f"**Company/Tool:** {src.company}  \n"
        f"**Source:** {src.source_url}  \n"
        + (f"**License:** {src.license}  \n" if src.license else "")
        + f"**Retrieved:** {date.today().isoformat()} "
        f"(imported as markdown for local search indexing; {n_pages})\n\n"
        "> Third-party documentation assembled for offline reading and semantic "
        "search. All rights remain with the original authors/vendor.\n\n---\n\n"
    )


def _next_data_md(session, url) -> tuple[str, str]:
    """Extract markdown from a Next.js __NEXT_DATA__ payload (client-rendered docs)."""
    txt = _get(session, url, as_text=True)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', txt, re.S)
    if not m:
        return "", ""
    data = json.loads(m.group(1))
    md = (((data.get("props") or {}).get("pageProps") or {}).get("markdown") or "")
    title = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
    mt = re.search(r"^#\s+(.+)", md, re.M)
    if mt:
        title = mt.group(1).strip()
    return title, md.strip()


# Markdown endpoints often prepend a blockquote telling AI clients how to fetch
# the docs ("append .md to the page URL", "connect to the MCP server at …").
# Repeated once per page it is pure noise for retrieval, so drop it.
_AGENT_PREAMBLE = re.compile(
    r"\A(?:>\s*For\s[^\n]*(?:append\s+`?\.md|llms\.txt|MCP server at)[^\n]*\n"
    r"|>\s*\n)+", re.I)


def _strip_agent_preamble(md: str) -> str:
    prev = None
    while prev != md:
        prev = md
        md = _AGENT_PREAMBLE.sub("", md.lstrip())
    return md.strip()


def _fetch_page_md(session, url, md_suffix) -> tuple[str, str]:
    """Return (title, markdown) for a doc page."""
    if md_suffix:
        try:
            txt = _strip_agent_preamble(_get(session, url.rstrip("/") + ".md",
                                             as_text=True))
            if txt.strip():
                m = re.match(r"^#\s+(.+)", txt.strip())
                title = m.group(1).strip() if m else url.rstrip("/").rsplit("/", 1)[-1]
                return title, txt.strip()
        except Exception:
            pass
    r = _get(session, url)
    doc = H.fromstring(r.content)
    strip_noise(doc)
    title = _title_of(doc, fallback=url.rstrip("/").rsplit("/", 1)[-1])
    return title, html_to_markdown(_pick_content(doc))


def import_pages(session, src, urls, delay, dry_run) -> tuple[int, str]:
    parts, kept = [], 0
    for i, url in enumerate(urls, 1):
        try:
            if src.method == "next_data":
                title, md = _next_data_md(session, url)
            else:
                title, md = _fetch_page_md(session, url, src.md_suffix)
        except Exception as exc:
            print(f"    ! {url}: {exc}", file=sys.stderr)
            continue
        if len(md) < 200:
            continue
        parts.append(f"\n\n<!-- source: {url} -->\n")
        # Only a *top-level* heading identifies the page; a page whose content
        # node starts at "## Requirements" (Confluence keeps its `h1.page-title`
        # outside the `<article>`) would otherwise be filed under no title at
        # all, which is how a 15 KB reference page becomes unattributable.
        if not re.match(r"#\s", md.lstrip()):
            parts.append(f"## {title}\n")
        parts.append(md)
        kept += 1
        if kept % 25 == 0:
            print(f"    [{kept}] pages fetched (of {len(urls)}) …")
        if delay and not dry_run:
            time.sleep(delay)
    return kept, "".join(parts)


_FENCE_LANG = {".yaml": "yaml", ".yml": "yaml", ".json": "json"}


def _alias_prefix(sitemap_url: str, locs: list[str]) -> tuple[str, str]:
    """Detect a versioned-docs alias, as ``(resolved prefix, alias prefix)``.

    ``mike`` serves an alias directory (``latest/``) whose sitemap lists the
    version it currently resolves to (``v3.1.0/``). The alias is the durable
    URL, so entries are rewritten onto it — but only when the two differ in a
    single path segment, which is what makes one an alias of the other rather
    than an unrelated location.
    """
    alias = sitemap_url.rsplit("/", 1)[0] + "/"
    common = os.path.commonprefix(locs) if locs else ""
    common = common[:common.rindex("/") + 1] if "/" in common else ""
    if not common or common == alias:
        return "", ""
    if alias[:-1].rsplit("/", 1)[0] != common[:-1].rsplit("/", 1)[0]:
        return "", ""
    return common, alias


def _hosted_slugs(session, src: DocSource) -> dict[str, str]:
    """Index a doc site's sitemap by page slug (and its parent path).

    Static site generators publish one URL per source file, so a repo-backed
    site can be ingested from the checkout while still citing the page a reader
    would open. Keys are the last one to three path segments of each URL.
    """
    out: dict[str, str] = {}
    for sm in src.sitemaps:
        locs = _sitemap_locs(session, (sm,))
        resolved, alias = _alias_prefix(sm, locs)
        for url in locs:
            if resolved and url.startswith(resolved):
                url = alias + url[len(resolved):]
            segs = [s for s in url.split("://")[-1].rstrip("/").split("/") if s][1:]
            for n in (1, 2, 3):
                if len(segs) >= n:
                    out.setdefault("/".join(segs[-n:]).lower(), url)
    return out


def _git_source_url(rel: Path, slugs: dict[str, str], src: DocSource) -> str:
    """Hosted doc-page URL for a repo file, or its GitHub blob URL."""
    for pat, url in src.url_map:
        if rel.as_posix() == pat:
            return url
    unhosted = re.search(src.unhosted_re, rel.as_posix()) if src.unhosted_re else None
    if src.url_template and not unhosted:
        below = rel.relative_to(src.subdir) if src.subdir else rel
        return src.url_template.format(slug=below.with_suffix("").as_posix())
    if slugs:
        # docs/examples/quality/column-accuracy.odcs.yaml -> "column-accuracy",
        # then "quality/column-accuracy" — the qualified form wins on collision.
        stem = rel.name.split(".")[0].lower()
        parents = [p.lower() for p in rel.parent.parts]
        cands = [stem] + ["/".join(parents[-n:] + [stem]) for n in (1, 2)]
        for key in reversed(cands):
            if key in slugs:
                return slugs[key]
    return f"{src.repo}/blob/{src.branch or 'HEAD'}/{rel.as_posix()}"


def _sparse_clone(src: DocSource, clone: Path) -> None:
    """Clone only the paths in ``src.sparse``, without historical file contents.

    A vendor's docs monorepo can be enormous next to the section that is wanted:
    ``MicrosoftDocs/fabric-docs`` is ~3.3 GB, nearly all of it screenshots, for
    ~2 MB of Fabric IQ markdown. ``--filter=blob:none`` defers file contents to
    the checkout, so only the matched files are ever transferred. The patterns
    are matched in **non-cone** mode, which is what allows a suffix filter —
    cone mode selects whole directories, which brings the media straight back.
    """
    IMPORTS.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1"]
    if src.branch:
        cmd += ["--branch", src.branch]
    subprocess.run(cmd + [src.repo, str(clone)], capture_output=True, check=True)
    git = ["git", "-C", str(clone)]
    subprocess.run(git + ["sparse-checkout", "set", "--no-cone", *src.sparse],
                   capture_output=True, check=True)
    subprocess.run(git + ["checkout"], capture_output=True, check=True)


def import_git(session, src: DocSource, dry_run) -> tuple[int, str]:
    if src.clone_dir:
        clone = DOCS_ROOT / src.clone_dir
        if not clone.exists():
            raise FileNotFoundError(f"checkout missing: {clone}")
    else:
        clone = IMPORTS / f"{src.key}-src"
    if clone.exists():
        subprocess.run(["git", "-C", str(clone), "pull", "--ff-only"],
                       capture_output=True)
    elif src.sparse:
        _sparse_clone(src, clone)
    else:
        IMPORTS.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", "--depth", "1"]
        if src.branch:
            cmd += ["--branch", src.branch]
        subprocess.run(cmd + [src.repo, str(clone)], capture_output=True, check=True)
    root = clone / src.subdir if src.subdir else clone
    files: set[Path] = set()
    for pat in src.file_globs:
        files.update(root.rglob(pat))
    rels = sorted(f.relative_to(clone) for f in files)
    if src.drop_re:
        drop = re.compile(src.drop_re)
        rels = [r for r in rels if not drop.search(r.as_posix())]
    if src.prefer:
        pr = re.compile(src.prefer)
        rels = ([r for r in rels if pr.search(r.as_posix())]
                + [r for r in rels if not pr.search(r.as_posix())])
    slugs = _hosted_slugs(session, src) if src.sitemaps else {}
    parts, kept = [], 0
    for rel in rels[:src.cap]:
        text = (clone / rel).read_text(encoding="utf-8", errors="replace").strip()
        if len(text) < 120:
            continue
        parts.append(f"\n\n<!-- source: {_git_source_url(rel, slugs, src)} -->\n")
        lang = _FENCE_LANG.get(rel.suffix.lower())
        if lang:
            parts.append(f"## {rel.as_posix()}\n\n```{lang}\n{text}\n```")
        else:
            parts.append(text)
        kept += 1
    return kept, "".join(parts)


def import_llms_full(session, src: DocSource) -> tuple[int, str]:
    txt = _get(session, src.llms_url, as_text=True)
    return 1, txt.strip()


def _butter_order(page: dict) -> tuple:
    grp = page.get("url_group") or {}
    sub = page.get("url_subgroup") or {}
    menu = (page.get("menu_item") or [{}])[0]
    return (grp.get("order") or 999, sub.get("order") or 0,
            menu.get("order") or 0, page.get("name") or "")


def import_butter_cms(session, src: DocSource) -> tuple[int, str]:
    """Ingest every doc page from a ButterCMS-backed docs SPA in one API call.

    The proxy returns the whole ``page`` collection, so there is nothing to
    crawl: we only re-derive each page's permalink (``/<group>/<subgroup>/<slug>``,
    matching the SPA's catch-all route) for the provenance marker.
    """
    r = session.get(src.api_url, params={"path": src.api_path}, timeout=TIMEOUT)
    r.raise_for_status()
    pages = (((r.json().get("raw_content") or {}).get("data") or {}).get("page") or [])
    parts, kept, group_seen = [], 0, None
    for page in sorted(pages, key=_butter_order):
        body = (page.get("content") or "").strip()
        if len(body) < 200:
            continue
        grp = page.get("url_group") or {}
        sub = page.get("url_subgroup") or {}
        slug = page.get("slug-new") or ""
        url = "/".join(x for x in (src.site_root, grp.get("slug"),
                                   sub.get("slug"), slug) if x)
        group_name = grp.get("name") or "Documentation"
        if group_name != group_seen:
            parts.append(f"\n\n## {group_name}\n")
            group_seen = group_name
        md = html_to_markdown(H.fromstring(f"<div>{body}</div>"))
        parts.append(f"\n\n<!-- source: {url} -->\n")
        parts.append(f"### {page.get('name') or slug}\n\n{md}")
        kept += 1
    return kept, "".join(parts)


def import_source(session, src: DocSource, delay, dry_run, force) -> dict:
    dest = (LITERATURE / src.collection / src.company /
            (src.filename or f"{src.company} Documentation.md"))
    if dest.exists() and not force:
        print(f"[{src.key}] exists, skipping (use --force) -> "
              f"{dest.relative_to(DOCS_ROOT)}")
        return {"kept": 0, "skipped": 1}

    print(f"[{src.key}] method={src.method} -> {dest.relative_to(DOCS_ROOT)}")
    if src.method == "llms_full":
        n, body = import_llms_full(session, src)
        pages_note = "single llms-full.txt export"
    elif src.method == "git":
        n, body = import_git(session, src, dry_run)
        pages_note = f"{n} files from {src.repo}"
    elif src.method == "butter_cms":
        n, body = import_butter_cms(session, src)
        pages_note = f"{n} pages (via the ButterCMS content API)"
    else:
        if src.method in ("sitemap", "next_data"):
            raw = _sitemap_locs(session, src.sitemaps)
            if src.rewrite_host:
                raw = _rewrite_host(raw, src.rewrite_host)
            keep = re.compile(src.keep_re)
            # english-only for multilingual sitemaps: strip /jp/ /zh/ /kr/ /ja/…
            norm = []
            for u in raw:
                u2 = re.sub(r"/docs/(jp|zh|kr|ja|de|fr|es|pt|ru|it)/", "/docs/", u)
                norm.append(u2)
            urls = [u for u in dict.fromkeys(norm) if keep.search(u)]
        elif src.method == "toc":
            urls = _toc_locs(session, src)
        elif src.method == "pages":
            urls = list(src.pages)
        else:  # crawl
            if src.autoindex:
                root = _autoindex_latest(session, src.seeds[0])
                src = replace(src, seeds=(root,), prefix=root)
            urls = _crawl(session, src)
        if src.version_pick:
            urls = _pick_latest_version(urls, src.version_pick)
        urls = _order(urls, src.prefer, src.drop_re, src.cap)
        print(f"    discovered {len(urls)} page URLs (cap {src.cap})")
        if dry_run:
            for u in urls[:12]:
                print("      ", u)
            return {"kept": len(urls), "skipped": 0}
        n, body = import_pages(session, src, urls, delay, dry_run)
        pages_note = f"{n} pages"
        if src.method == "next_data":
            pages_note = f"{n} pages (via __NEXT_DATA__)"

    if dry_run:
        print(f"[{src.key}] dry-run: would write ~{n} unit(s)")
        return {"kept": n, "skipped": 0}
    if not body.strip():
        print(f"[{src.key}] no content extracted", file=sys.stderr)
        return {"kept": 0, "skipped": 0}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_header(src, pages_note) + body, encoding="utf-8")
    kb = dest.stat().st_size / 1024
    print(f"[{src.key}] wrote {dest.name} ({n} unit(s), {kb:.0f} KB)")
    return {"kept": n, "skipped": 0}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", metavar="KEY",
                   help=f"import only these ({', '.join(s.key for s in SOURCES)})")
    p.add_argument("--cap", type=int, default=None, help="override per-source page cap")
    p.add_argument("--delay", type=float, default=0.2, help="seconds between fetches")
    p.add_argument("--dry-run", action="store_true", help="discover only, write nothing")
    p.add_argument("--force", action="store_true", help="rebuild existing source files")
    p.add_argument("--list", action="store_true", help="list sources and exit")
    args = p.parse_args(argv)

    if args.list:
        for s in SOURCES:
            print(f"{s.key:18} [{s.method:9}] -> "
                  f"{s.collection}/{s.company}/")
        return 0

    sources = SOURCES
    if args.only:
        keys = set(args.only)
        sources = [s for s in SOURCES if s.key in keys]
        if not sources:
            print(f"no matching sources for {args.only}", file=sys.stderr)
            return 2
    if args.cap:
        for s in sources:
            s.cap = args.cap

    session = _session()
    totals = {"kept": 0, "skipped": 0}
    for s in sources:
        try:
            r = import_source(session, s, args.delay, args.dry_run, args.force)
            for k in totals:
                totals[k] += r.get(k, 0)
        except Exception as exc:
            print(f"[{s.key}] FAILED: {exc}", file=sys.stderr)
    print(f"\nDone. units {totals['kept']} | skipped-sources {totals['skipped']} "
          f"across {len(sources)} source(s).")
    if not args.dry_run:
        print("Next: scripts/.venv/bin/python -m search.cli index --roots literature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
