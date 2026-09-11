#!/usr/bin/env python3
"""Select and probe the Apache Software Foundation's data-area projects.

Feeds two things that are maintained by hand elsewhere: the documentation
sources in ``scripts/import-docs.py`` and the citation cohort in
``scripts/apache-papers.py``. This script is what makes those two lists
*checkable* — it enumerates the ASF's own project register, decides which
projects belong to the database / data-engineering / data-visualisation /
cloud area, and probes each one's doc site to establish how it can be read.

Source of truth is the register behind https://projects.apache.org/, which
publishes the per-project DOAP data as JSON:

    https://projects.apache.org/json/foundation/projects.json   (378 TLPs)
    https://projects.apache.org/json/foundation/podlings.json   (25 incubating)

**Do not filter on ``category`` alone**, which is what the site's own
``projects.html?category`` view does. The category comes from each project's
DOAP file, and 52 of the 378 entries have none at all — they are tagged
``no-tlp-doap``, meaning the register never found a DOAP to read. That bucket is
not a random remainder: it holds Paimon, Sedona, Gravitino, Kyuubi, Celeborn,
HugeGraph, Kvrocks, ShardingSphere, TinkerPop, AsterixDB, Atlas, Hudi, Wayang,
SystemDS, MADlib, Livy, Ratis, Fluss, Gluten, Uniffle, DolphinScheduler and
StreamPipes — i.e. most of the modern lakehouse and streaming stack, because a
DOAP file is an old convention that newer projects (and projects that arrived
through the incubator with their own site) never adopted. Selecting on category
would have silently dropped all of them, so ``EXTRA`` names them explicitly and
this script reports the size of the blind spot on every run.

Podlings are included for the same reason in reverse: they are not in
``projects.json`` at all, and one of them (**Ossie**, the former Open Semantic
Interchange) is the semantic-metadata specification this collection most wants.

Probing answers one question per project — *how would ``import-docs.py`` read
this?* — by testing, in order: a ``sitemap.xml`` (and the usual variants), an
``llms.txt`` / ``llms-full.txt`` export, and whether a sample doc page also
serves markdown at ``<url>.md``. It also detects a **version-partitioned** doc
tree (``/docs/1.11.0/…`` next to ``/docs/1.10.0/…``), which is the
characteristic Apache layout and the reason ``import-docs.py`` has
``version_pick``: an unfiltered sitemap otherwise imports the same manual once
per release.

    scripts/.venv/bin/python scripts/apache-projects.py select
    scripts/.venv/bin/python scripts/apache-projects.py probe [--only iceberg …]
    scripts/.venv/bin/python scripts/apache-projects.py all --refresh
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import requests

DOCS_ROOT = Path(__file__).resolve().parent.parent
IMPORTS = DOCS_ROOT / "imports"
PROJECTS_JSON = IMPORTS / "apache-projects.json"
PODLINGS_JSON = IMPORTS / "apache-podlings.json"
SELECTED_CSV = IMPORTS / "apache-projects-selected.csv"
PROBE_CSV = IMPORTS / "apache-doc-probe.csv"
ROOTS_CSV = IMPORTS / "apache-doc-roots.csv"

PROJECTS_URL = "https://projects.apache.org/json/foundation/projects.json"
PODLINGS_URL = "https://projects.apache.org/json/foundation/podlings.json"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
TIMEOUT = 25

# The DOAP categories that put a project in this collection's area.
WANT_CATEGORIES = {
    "big-data", "database", "data-engineering", "data-visualization",
    "data-management-platform", "distributed-sql-database", "nosql", "sql",
    "hadoop", "cloud", "geospatial", "search", "observability",
}

# Projects whose DOAP carries no category (``no-tlp-doap``) or a category that
# does not reflect what they are, keyed by the register's own project key. The
# note is why the project belongs in a data/cloud collection.
EXTRA: dict[str, str] = {
    "asterixdb": "semistructured BDMS; SQL++ (UC Irvine)",
    "atlas": "metadata management and data governance for Hadoop",
    "celeborn": "remote shuffle service for Spark/Flink",
    "dolphinscheduler": "distributed workflow scheduler for data pipelines",
    "fluss": "streaming storage for real-time analytics",
    "fory": "serialisation framework (formerly Fury)",
    "gluten": "native (Velox/ClickHouse) execution engine for Spark",
    "gravitino": "federated metadata lake / catalog of catalogs",
    "hudi": "transactional lakehouse table format with upserts",
    "hugegraph": "distributed graph database",
    "iggy": "persistent message streaming platform",
    "kvrocks": "RocksDB-backed key-value store speaking the Redis protocol",
    "kyuubi": "multi-tenant SQL gateway over Spark/Flink/Trino",
    "livy": "REST service for interactive Spark sessions",
    "madlib": "in-database machine learning for PostgreSQL/Greenplum",
    "paimon": "streaming lakehouse table format",
    "ratis": "Raft consensus library (used by Ozone)",
    "rocketmq": "distributed messaging and streaming platform",
    "rya": "scalable RDF triple store over Accumulo",
    "sdap": "science data analytics platform (NASA/JPL)",
    "sedona": "cluster computing for large-scale geospatial data",
    "shardingsphere": "distributed SQL / sharding middleware",
    "streampark": "stream-processing application management",
    "streampipes": "self-service (industrial) IoT data analytics",
    "systemds": "declarative end-to-end machine-learning pipelines",
    "tinkerpop": "graph computing framework; the Gremlin traversal language",
    "uniffle": "unified remote shuffle service",
    "wayang": "cross-platform data processing (federated execution)",
}

# In-area by category but out of scope, with the reason. Kept explicit so a
# re-run does not quietly re-add them.
SKIP: dict[str, str] = {
    "camel": "enterprise integration patterns, not data management",
    "cayenne": "Java ORM",
    "curator": "ZooKeeper client library",
    "daffodil": "DFDL data-format description, not a data platform",
    "empire-db": "Java persistence library",
    "jackrabbit": "JCR content repository",
    "openjpa": "Java persistence implementation",
    "lucenenet-lucenedotnet": "port of Lucene to .NET",
    "lucene-pylucene": "Python bindings for Lucene",
    "ofbiz": "ERP application suite",
    "unomi": "customer-data platform (profile store)",
    "vcl": "lab-machine provisioning, not a data platform",
    "tvm": "deep-learning compiler stack",
    "helix": "generic cluster-management framework",
    "brooklyn": "application blueprint/deployment framework",
    "airavata": "science-gateway middleware",
    "libcloud": "multi-cloud provider abstraction library",
    "solr-operator": "Kubernetes operator for Solr",
    "accumulo-fluo": "Accumulo-layered incremental-processing library",
    "accumulo-fluo_recipes": "library layered on Fluo",
    "accumulo-fluo_yarn": "YARN launcher for Fluo",
    "datafu": "Pig/Hive UDF library",
    "commons-rdf": "RDF abstraction library",
    "incubator-pouchdb": "browser database (JavaScript client)",
    "db-jdo": "Java persistence API specification",
    "db-torque": "Java ORM",
}

# Incubating projects in the same area, keyed by the podlings register.
PODLING_EXTRA: dict[str, str] = {
    "ossie": "vendor-neutral semantic-metadata specification (formerly OSI)",
    "amoro": "lakehouse management for Iceberg/Paimon/Hudi",
    "auron": "native vectorised execution engine for Spark",
    "cloudberry": "MPP analytical database derived from Greenplum",
    "geaflow": "distributed streaming graph computing",
    "graphar": "columnar file format for graph data",
    "pegasus": "distributed key-value store",
    "resilientdb": "byzantine-fault-tolerant distributed ledger/database",
    "texera": "collaborative dataflow workflows over big data",
    "xtable": "cross-table interoperability of Iceberg/Delta/Hudi",
    "toree": "Jupyter kernel for Spark",
    "hamilton": "dataflow definition framework for data/ML pipelines",
    "otava": "change-point detection for performance time series",
}

# Doc-root paths to try under a project's own origin, most specific first.
DOC_PATHS = ("/docs/", "/documentation/", "/docs/latest/", "/docs/stable/", "/")
SITEMAP_PATHS = ("/sitemap.xml", "/docs/sitemap.xml", "/sitemap_index.xml",
                 "/sitemap-index.xml", "/sitemap-0.xml", "/en/sitemap.xml")
LLMS_PATHS = ("/llms-full.txt", "/llms.txt", "/docs/llms-full.txt",
              "/docs/llms.txt")

VERSION_SEG_RE = re.compile(r"/(?:v)?(\d+\.\d+(?:\.\d+)?)/")
DOCLIKE_RE = re.compile(
    r"/(docs?|documentation|manual|reference|guide|user-guide|userguide|"
    r"javadoc|api|spec|specification|latest|stable|current)(/|$)", re.I)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def refresh_registers(session) -> None:
    IMPORTS.mkdir(parents=True, exist_ok=True)
    for url, dest in ((PROJECTS_URL, PROJECTS_JSON), (PODLINGS_URL, PODLINGS_JSON)):
        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        dest.write_text(r.text, encoding="utf-8")
        print(f"  refreshed {dest.relative_to(DOCS_ROOT)} ({len(r.content)} bytes)")


def _load(path: Path, url: str, session) -> dict:
    if not path.exists():
        refresh_registers(session)
    return json.loads(path.read_text(encoding="utf-8"))


def select(session) -> list[dict]:
    """The data/cloud-area projects, with why each one is in the list."""
    projects = _load(PROJECTS_JSON, PROJECTS_URL, session)
    podlings = _load(PODLINGS_JSON, PODLINGS_URL, session)

    out: list[dict] = []
    no_category = uncategorised_in_area = 0
    for key, p in projects.items():
        cats = {c.strip() for c in (p.get("category") or "").split(",") if c.strip()}
        if "no-tlp-doap" in cats or not cats:
            no_category += 1
        if "retired" in cats:
            continue
        if key in SKIP:
            continue
        by_category = bool(cats & WANT_CATEGORIES)
        if not by_category and key not in EXTRA:
            continue
        if not by_category:
            uncategorised_in_area += 1
        repos = p.get("repository") or []
        out.append({
            "key": key,
            "name": p.get("name") or key,
            "kind": "tlp",
            "selected_by": "category" if by_category else "EXTRA",
            "why": EXTRA.get(key, ""),
            "categories": " ".join(sorted(cats)),
            "homepage": (p.get("homepage") or "").rstrip("/"),
            "repository": repos[0] if repos else "",
            "shortdesc": (p.get("shortdesc") or p.get("description") or "")
                         .strip().replace("\n", " ")[:200],
        })

    for key, why in PODLING_EXTRA.items():
        pod = podlings.get(key)
        if not pod:
            print(f"  ! podling '{key}' is no longer current — it graduated or "
                  f"retired; move it to EXTRA or drop it", file=sys.stderr)
            continue
        out.append({
            "key": key,
            "name": pod.get("name") or key,
            "kind": "podling",
            "selected_by": "PODLING_EXTRA",
            "why": why,
            "categories": "",
            "homepage": (pod.get("homepage") or "").rstrip("/"),
            "repository": f"https://github.com/apache/{key}",
            "shortdesc": (pod.get("description") or "").strip()
                         .replace("\n", " ")[:200],
        })

    out.sort(key=lambda r: r["key"])
    print(f"selected {len(out)} projects "
          f"({sum(1 for r in out if r['kind'] == 'podling')} incubating)")
    print(f"  {no_category} of {len(projects)} register entries carry no usable "
          f"category; {uncategorised_in_area} of them are in this area and are "
          f"named by EXTRA")
    print(f"  {len(SKIP)} in-area-by-category projects skipped as out of scope")
    return out


# --- probing ---------------------------------------------------------------

def _get(session, url, **kw):
    return session.get(url, timeout=TIMEOUT, allow_redirects=True, **kw)


def _sitemap_locs(session, url: str, depth: int = 0) -> list[str]:
    try:
        r = _get(session, url)
    except Exception:
        return []
    if r.status_code != 200 or "<loc" not in r.text[:20000]:
        return []
    locs = [l.strip() for l in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text)]
    locs = [("https:" + l if l.startswith("//") else l) for l in locs]
    if "<sitemapindex" in r.text[:2000] and depth < 2:
        nested: list[str] = []
        for child in locs[:12]:
            nested.extend(_sitemap_locs(session, child, depth + 1))
        return nested
    return locs


def _md_suffix_works(session, url: str) -> bool:
    try:
        r = _get(session, url.rstrip("/") + ".md")
    except Exception:
        return False
    if r.status_code != 200:
        return False
    body = r.text.lstrip()
    if "<html" in body[:400].lower():
        return False
    return len(body) > 400 and ("#" in body[:200] or "---" in body[:200])


def probe(session, rec: dict) -> dict:
    home = rec["homepage"] or f"https://{rec['key']}.apache.org"
    origin = f"{urlsplit(home).scheme or 'https'}://{urlsplit(home).netloc}"
    out = dict(rec, sitemap="", locs=0, doc_locs=0, versions="",
               llms="", md_suffix="", sample="", note="")

    locs: list[str] = []
    for path in SITEMAP_PATHS:
        locs = _sitemap_locs(session, origin + path)
        if locs:
            out["sitemap"] = origin + path
            break
    # Some projects publish their manual on a separate docs host.
    if not locs:
        for alt in (f"https://docs.{rec['key']}.apache.org",
                    f"{origin}/docs"):
            for path in ("/sitemap.xml",):
                locs = _sitemap_locs(session, alt + path)
                if locs:
                    out["sitemap"] = alt + path
                    break
            if locs:
                break

    if locs:
        out["locs"] = len(locs)
        doc = [u for u in locs if DOCLIKE_RE.search(u)] or locs
        out["doc_locs"] = len(doc)
        vers = sorted({m.group(1) for u in doc if (m := VERSION_SEG_RE.search(u))})
        out["versions"] = " ".join(vers[:8]) + (" …" if len(vers) > 8 else "")
        out["sample"] = doc[len(doc) // 2] if doc else ""
        out["md_suffix"] = "yes" if _md_suffix_works(session, out["sample"]) else ""

    for path in LLMS_PATHS:
        try:
            r = _get(session, origin + path)
        except Exception:
            continue
        if r.status_code == 200 and len(r.text) > 2000 and "<html" not in r.text[:400].lower():
            out["llms"] = origin + path
            break

    if not out["sitemap"] and not out["llms"]:
        out["note"] = "no sitemap and no llms export — needs crawl/toc/git"
    print(f"  {rec['key']:<18} sitemap={'yes' if out['sitemap'] else '-':<4} "
          f"locs={out['locs']:<6} doc={out['doc_locs']:<6} "
          f"md={'yes' if out['md_suffix'] else '-':<4} "
          f"llms={'yes' if out['llms'] else '-':<4} {out['note']}")
    return out


# Where an Apache project without a sitemap tends to keep its manual. Tried in
# this order; the first path that answers with a link-rich HTML page wins.
ROOT_PATHS = (
    "/docs/latest/", "/docs/current/", "/docs/stable/", "/docs/", "/doc/",
    "/documentation/", "/latest/", "/current/", "/manual/", "/user-guide/",
    "/guide/", "/quickstart/",
)


def probe_root(session, rec: dict) -> dict:
    """Find a crawlable documentation root for a project with no sitemap."""
    home = rec["homepage"] or f"https://{rec['key']}.apache.org"
    origin = f"{urlsplit(home).scheme or 'https'}://{urlsplit(home).netloc}"
    base = home.rstrip("/")
    out = dict(rec, root="", status=0, links=0, chars=0, note="")
    best: tuple[int, str, int, int] | None = None
    tried: list[str] = []
    for prefix in dict.fromkeys((base, origin)):
        for path in ROOT_PATHS:
            url = prefix + path
            if url in tried:
                continue
            tried.append(url)
            try:
                r = _get(session, url)
            except Exception:
                continue
            if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                continue
            final = r.url
            # A doc path that redirects to the site root is not a doc root.
            if final.rstrip("/") == origin.rstrip("/"):
                continue
            links = len(re.findall(r"<a\s[^>]*href=", r.text, re.I))
            chars = len(r.text)
            if links < 15:
                continue
            cand = (links, final, r.status_code, chars)
            if best is None or links > best[0]:
                best = cand
            # A dedicated docs path is preferred over a generic landing page,
            # so stop at the first one that looks like a manual index.
            if links >= 40:
                break
        if best and best[0] >= 40:
            break
    if best:
        out.update(links=best[0], root=best[1], status=best[2], chars=best[3])
    else:
        out["note"] = "no crawlable doc root found"
    print(f"  {rec['key']:<24} {out['root'] or '(none)':<58} "
          f"links={out['links']}")
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.relative_to(DOCS_ROOT)} ({len(rows)} rows)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["select", "probe", "roots", "all"])
    p.add_argument("--refresh", action="store_true",
                   help="re-download the projects/podlings registers first")
    p.add_argument("--only", nargs="*", metavar="KEY",
                   help="probe only these project keys")
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args(argv)

    session = _session()
    if args.refresh:
        refresh_registers(session)

    rows = select(session)
    write_csv(SELECTED_CSV, rows)
    if args.cmd == "select":
        return 0

    if args.only:
        keys = set(args.only)
        rows = [r for r in rows if r["key"] in keys]

    if args.cmd == "roots":
        if not PROBE_CSV.exists():
            print("run `probe` first — roots only looks at the projects it found "
                  "no sitemap for", file=sys.stderr)
            return 2
        with PROBE_CSV.open(encoding="utf-8") as fh:
            hard = {r["key"] for r in csv.DictReader(fh) if r["note"]}
        rows = [r for r in rows if r["key"] in hard]
        print(f"\nlooking for a doc root on {len(rows)} sitemap-less sites …")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            found = list(pool.map(lambda r: probe_root(session, r), rows))
        found.sort(key=lambda r: (-r["links"], r["key"]))
        write_csv(ROOTS_CSV, found)
        ok = [r for r in found if r["root"]]
        print(f"\n{len(ok)} of {len(found)} have a crawlable doc root; "
              f"{len(found) - len(ok)} have none (javadoc-only, single-page "
              f"manual, or docs kept in git)")
        return 0

    print(f"\nprobing {len(rows)} doc sites …")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        probed = list(pool.map(lambda r: probe(session, r), rows))
    probed.sort(key=lambda r: (-r["doc_locs"], r["key"]))
    write_csv(PROBE_CSV, probed)

    hard = [r for r in probed if r["note"]]
    print(f"\n{len(probed) - len(hard)} projects are readable from a sitemap or "
          f"llms export; {len(hard)} need a crawl/toc/git method:")
    for r in hard:
        print(f"  - {r['key']} ({r['homepage']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
