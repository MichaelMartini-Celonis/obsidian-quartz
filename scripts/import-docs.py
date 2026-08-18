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
checkout of markdown), converts each page to markdown, and writes **one
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
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
    # crawl / toc
    seeds: tuple[str, ...] = ()     # crawl: BFS seeds; toc: table-of-contents page(s)
    prefix: str = ""                # crawled/toc URLs must start with this
    # pages
    pages: tuple[str, ...] = ()     # explicit list of page URLs to fetch as-is
    # git
    repo: str = ""
    subdir: str = ""
    file_globs: tuple[str, ...] = ("*.md",)   # which files to ingest from a git checkout
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
    return body[0] if body else doc


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

def _sitemap_locs(session, sitemaps) -> list[str]:
    out: list[str] = []
    for sm in sitemaps:
        try:
            txt = _get(session, sm, as_text=True)
        except Exception as exc:
            print(f"    ! sitemap {sm}: {exc}", file=sys.stderr)
            continue
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", txt)
        # normalize protocol-relative (//host/...) URLs
        locs = [("https:" + l if l.startswith("//") else l) for l in locs]
        out.extend(locs)
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
        doc.make_links_absolute(url)
        for a in doc.xpath("//a[@href]"):
            h = a.get("href").split("#")[0].split("?")[0].rstrip("/")
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
        if not md.lstrip().startswith("#"):
            parts.append(f"## {title}\n")
        parts.append(md)
        kept += 1
        if kept % 25 == 0:
            print(f"    [{kept}] pages fetched (of {len(urls)}) …")
        if delay and not dry_run:
            time.sleep(delay)
    return kept, "".join(parts)


def import_git(src: DocSource, dry_run) -> tuple[int, str]:
    clone = IMPORTS / f"{src.key}-src"
    if clone.exists():
        subprocess.run(["git", "-C", str(clone), "pull", "--ff-only"],
                       capture_output=True)
    else:
        IMPORTS.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", src.repo, str(clone)],
                       capture_output=True, check=True)
    root = clone / src.subdir if src.subdir else clone
    files: list[Path] = []
    for pat in src.file_globs:
        files.extend(root.rglob(pat))
    parts, kept = [], 0
    for f in sorted(set(files)):
        rel = f.relative_to(clone)
        text = f.read_text(encoding="utf-8", errors="replace").strip()
        if len(text) < 120:
            continue
        parts.append(f"\n\n<!-- source: {src.repo}/blob/master/{rel} -->\n")
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
        n, body = import_git(src, dry_run)
        pages_note = f"{n} markdown files from {src.repo}"
    elif src.method == "butter_cms":
        n, body = import_butter_cms(session, src)
        pages_note = f"{n} pages (via the ButterCMS content API)"
    else:
        if src.method in ("sitemap", "next_data"):
            raw = _sitemap_locs(session, src.sitemaps)
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
            urls = _crawl(session, src)
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
