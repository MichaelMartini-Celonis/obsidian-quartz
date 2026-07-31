"""Command-line interface for the search engine.

Run from ~/docs, e.g.:

    scripts/.venv/bin/python -m search.cli index --limit 20
    scripts/.venv/bin/python -m search.cli search "object-centric process discovery"
    scripts/.venv/bin/python -m search.cli stats
"""

from __future__ import annotations

import argparse
import sys

from . import config
from . import db as dbmod
from . import graph as graphmod
from . import index as indexmod
from . import query as querymod
from .embeddings import get_embedder


def _roots(names: list[str] | None):
    mapping = {
        "literature": config.LITERATURE_DIR,
        "transcripts": config.TRANSCRIPTS_DIR,
        "notebooks": config.NOTEBOOKS_DIR,
        "db_systems": config.DB_SYSTEMS_DIR,
        "outbox": config.OUTBOX_DIR,
        "inbox": config.INBOX_DIR,
    }
    if not names:
        return [config.LITERATURE_DIR, config.TRANSCRIPTS_DIR,
                config.NOTEBOOKS_DIR, config.DB_SYSTEMS_DIR, config.OUTBOX_DIR]
    return [mapping[n] for n in names]


def cmd_index(args) -> int:
    embedder = get_embedder()
    con = dbmod.connect()
    try:
        stats = indexmod.build_index(
            con, embedder, _roots(args.roots), limit=args.limit, reset=args.reset
        )
    finally:
        con.close()
    print(
        f"\nindexed={stats.get('indexed', 0)} "
        f"skipped={stats.get('skip', 0)} empty={stats.get('empty', 0)}"
    )
    return 0


def cmd_search(args) -> int:
    internal = True if args.internal_only else (False if args.external_only else None)
    embedder = get_embedder()
    con = dbmod.connect(read_only=True)
    try:
        results = querymod.search(
            con, embedder, args.query, k=args.k, expand=args.expand, internal=internal
        )
    finally:
        con.close()
    if not results:
        print("no results")
        return 0
    for i, r in enumerate(results, 1):
        loc = f"p.{r.page}" if r.page else ""
        tags = []
        if r.internal:
            tags.append("internal")
        if r.via == "graph":
            tags.append("via graph")
        tag = f"  ({', '.join(tags)})" if tags else ""
        print(f"\n{i}. {r.title}  [{r.topic}] {loc}{tag}")
        print(f"   {r.rel_path}")
        print(f"   {r.snippet}")
    return 0


def cmd_enrich(args) -> int:
    from . import enrich as enrichmod

    con = dbmod.connect()
    try:
        stats = enrichmod.enrich(
            con, only_review=args.only_review, limit=args.limit, redo=args.redo
        )
    finally:
        con.close()
    print(f"\nenriched={stats['enriched']} failed={stats['failed']} "
          f"total={stats['total']}")
    return 0


def cmd_graph(args) -> int:
    con = dbmod.connect(graph=True)
    try:
        if args.build:
            stats = graphmod.build_graph(con, similar_k=args.similar_k)
            print("graph built:", stats)
            return 0
        if args.author:
            print(f"Papers by '{args.author}':")
            for title, rel_path, year in graphmod.papers_by_author(con, args.author):
                print(f"  ({year or '????'}) {title}\n      {rel_path}")
            print(f"\nFrequent co-authors of '{args.author}':")
            for name, n in graphmod.coauthors(con, args.author):
                print(f"  {n:3d}  {name}")
            return 0
        if args.company is not None:
            if args.company == "":
                print("Companies / tools (by document count):")
                for name, n in graphmod.companies(con):
                    print(f"  {n:4d}  {name}")
                return 0
            print(f"Documents for company '{args.company}':")
            for title, topic, rel_path in graphmod.docs_by_company(con, args.company):
                print(f"  [{topic}] {title}\n      {rel_path}")
            return 0
        # Default: summary counts.
        for label, table in (("documents", "documents"), ("authors", "authors"),
                             ("keywords", "keywords"), ("topics", "topics"),
                             ("companies", "companies"),
                             ("author edges", "doc_authors"),
                             ("keyword edges", "doc_keywords"),
                             ("company edges", "doc_companies"),
                             ("similar edges", "doc_similar")):
            try:
                n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except Exception:
                n = "-"
            print(f"  {label:14s} {n}")
    finally:
        con.close()
    return 0


def cmd_stats(args) -> int:
    con = dbmod.connect(read_only=True)
    try:
        docs = con.execute("SELECT count(*) FROM documents").fetchone()[0]
        chunks = con.execute("SELECT count(*) FROM chunks").fetchone()[0]
        review = con.execute(
            "SELECT count(*) FROM documents WHERE needs_review"
        ).fetchone()[0]
        internal = con.execute(
            "SELECT count(*) FROM documents WHERE internal"
        ).fetchone()[0]
        by_topic = con.execute(
            "SELECT topic, count(*) FROM documents GROUP BY topic ORDER BY 2 DESC LIMIT 15"
        ).fetchall()
        model = con.execute("SELECT value FROM meta WHERE key='embedder_model'").fetchone()
        dim = con.execute("SELECT value FROM meta WHERE key='embedding_dim'").fetchone()
    finally:
        con.close()
    print(f"documents: {docs}")
    print(f"chunks:    {chunks}")
    print(f"needs_review: {review}")
    print(f"internal (Celonis): {internal}")
    print(f"embedder:  {model[0] if model else '?'} (dim {dim[0] if dim else '?'})")
    print("top topics:")
    for topic, n in by_topic:
        print(f"  {n:5d}  {topic}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="search", description="Graph-RAG search over ~/docs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="ingest files into the index")
    p_index.add_argument("--roots", nargs="*",
                         choices=["literature", "transcripts", "notebooks", "db_systems",
                                  "outbox", "inbox"])
    p_index.add_argument("--limit", type=int, default=None, help="max files to process")
    p_index.add_argument("--reset", action="store_true", help="drop and rebuild the index")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="hybrid vector+BM25 search")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=10)
    p_search.add_argument("--expand", action="store_true",
                          help="add graph-expanded (related) results")
    g_internal = p_search.add_mutually_exclusive_group()
    g_internal.add_argument("--internal-only", action="store_true",
                            help="only Celonis-internal documents")
    g_internal.add_argument("--external-only", action="store_true",
                            help="exclude Celonis-internal documents")
    p_search.set_defaults(func=cmd_search)

    p_enrich = sub.add_parser("enrich", help="LLM-clean metadata via the AI Gateway")
    p_enrich.add_argument("--only-review", action="store_true",
                          help="only docs flagged needs_review")
    p_enrich.add_argument("--limit", type=int, default=None)
    p_enrich.add_argument("--redo", action="store_true", help="re-enrich already-done docs")
    p_enrich.set_defaults(func=cmd_enrich)

    p_graph = sub.add_parser("graph", help="build/query the knowledge graph (duckpgq)")
    p_graph.add_argument("--build", action="store_true", help="(re)build graph tables + property graph")
    p_graph.add_argument("--similar-k", type=int, default=8, help="SIMILAR_TO neighbours per doc")
    p_graph.add_argument("--author", help="show papers and co-authors for an author")
    p_graph.add_argument("--company", nargs="?", const="", default=None,
                         help="list companies (no value) or documents for a company/tool")
    p_graph.set_defaults(func=cmd_graph)

    p_stats = sub.add_parser("stats", help="index statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
