"""Command-line interface for the search engine.

Run from ~/docs, e.g.:

    scripts/.venv/bin/python -m search.cli index --limit 20
    scripts/.venv/bin/python -m search.cli search "object-centric process discovery"
    scripts/.venv/bin/python -m search.cli --db meet search "event handling"
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


def _roots(names: list[str] | None, db_alias: str | None = None):
    mapping = {
        "literature": config.LITERATURE_DIR,
        "transcripts": config.TRANSCRIPTS_DIR,
        "notebooks": config.NOTEBOOKS_DIR,
        "db_systems": config.DB_SYSTEMS_DIR,
        "outbox": config.OUTBOX_DIR,
        "inbox": config.INBOX_DIR,
        "internal": config.INTERNAL_DIR,
        "personal": config.PERSONAL_DRIVE_DIR,
        "meet": config.MEET_NOTES_DIR,
    }
    if not names:
        if (db_alias or "") in ("meet", "meetings"):
            return [config.MEET_NOTES_DIR]
        return [
            config.LITERATURE_DIR, config.TRANSCRIPTS_DIR, config.NOTEBOOKS_DIR,
            config.DB_SYSTEMS_DIR, config.OUTBOX_DIR, config.INTERNAL_DIR,
            config.PERSONAL_DRIVE_DIR,
        ]
    return [mapping[n] for n in names]


def cmd_index(args) -> int:
    alias = args.db or ""
    roots = set(args.roots or [])
    meet_db = alias in ("meet", "meetings")
    if meet_db and roots - {"meet"}:
        print("error: --db meet only accepts --roots meet", file=sys.stderr)
        return 2
    if not meet_db and "meet" in roots:
        print("error: Personal/meet belongs in search/meet.duckdb; use --db meet",
              file=sys.stderr)
        return 2
    if meet_db:
        config.DB_PATH = config.MEET_DB_PATH
    embedder = get_embedder()
    con = dbmod.connect()
    try:
        stats = indexmod.build_index(
            con, embedder, _roots(args.roots, alias),
            limit=args.limit, reset=args.reset
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


def cmd_ocr(args) -> int:
    from . import ocr as ocrmod

    con = dbmod.connect()
    try:
        if args.status:
            for label, value in ocrmod.status(con):
                print(f"  {label:32s} {value:>12s}")
            return 0
        if args.list:
            for c in ocrmod.candidates(con, args.only_empty, args.low_density,
                                       args.front_matter, args.doc_id, args.limit):
                print(f"  {c.n_pages:>4} pg  {c.reason:14s} {c.rel_path[:78]}")
            return 0
        ocrmod.run(con, only_empty=args.only_empty, low_density=args.low_density,
                   front_matter=args.front_matter, doc_id=args.doc_id, mode=args.mode,
                   dpi=args.dpi, backend=args.backend, limit=args.limit,
                   max_pages=args.max_pages, redo=args.redo,
                   retry_failed=args.retry_failed)
        if args.promote:
            embedder = get_embedder()
            n = indexmod.reindex_ocr_documents(con, embedder)
            print(f"promoted {n} documents into the index")
    finally:
        con.close()
    return 0


def cmd_metadata(args) -> int:
    from . import metadata as metamod

    con = dbmod.connect()
    try:
        if args.status:
            for label, value in metamod.status(con):
                print(f"  {label:32s} {value}")
            return 0
        stats = metamod.backfill(con, limit=args.limit, redo=args.redo)
    finally:
        con.close()
    print(f"\nupdated={stats['updated']} abstracts={stats['abstracts']} "
          f"pdf_dates={stats['pdf_dates']} image_only={stats['image_only']} "
          f"missing_file={stats['missing_file']} total={stats['total']}")
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
    print(f"internal:  {internal}")
    print(f"embedder:  {model[0] if model else '?'} (dim {dim[0] if dim else '?'})")
    print("top topics:")
    for topic, n in by_topic:
        print(f"  {n:5d}  {topic}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="search", description="Graph-RAG search over ~/docs")
    parser.add_argument(
        "--db", default=None,
        help="DuckDB file, or alias: main (default, includes Internal + Personal/drive) | meet (Personal/meet only)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="ingest files into the index")
    p_index.add_argument("--roots", nargs="*",
                         choices=["literature", "transcripts", "notebooks", "db_systems",
                                  "outbox", "inbox", "internal", "personal", "meet"])
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
                            help="only Internal/ and Personal/ documents")
    g_internal.add_argument("--external-only", action="store_true",
                            help="exclude Internal/ and Personal/ documents")
    p_search.set_defaults(func=cmd_search)

    p_enrich = sub.add_parser("enrich", help="LLM-clean metadata via the AI Gateway")
    p_enrich.add_argument("--only-review", action="store_true",
                          help="only docs flagged needs_review")
    p_enrich.add_argument("--limit", type=int, default=None)
    p_enrich.add_argument("--redo", action="store_true", help="re-enrich already-done docs")
    p_enrich.set_defaults(func=cmd_enrich)

    p_meta = sub.add_parser(
        "metadata", help="backfill container metadata + abstracts (no model needed)")
    p_meta.add_argument("--limit", type=int, default=None)
    p_meta.add_argument("--redo", action="store_true",
                        help="recompute for documents already through the stage")
    p_meta.add_argument("--status", action="store_true", help="coverage report")
    p_meta.set_defaults(func=cmd_metadata)

    p_ocr = sub.add_parser("ocr", help="OCR image-only/thin PDFs with a local VLM")
    p_ocr.add_argument("--only-empty", action="store_true",
                       help="PDFs with no text layer at all (the default selection)")
    p_ocr.add_argument("--low-density", action="store_true",
                       help=f"also PDFs under {config.OCR_MIN_CHARS_PER_PAGE} chars/page")
    p_ocr.add_argument("--front-matter", action="store_true",
                       help="pages 1-2 of every PDF (the metadata pass; ~25h)")
    p_ocr.add_argument("--doc-id", help="one document, by content hash")
    p_ocr.add_argument("--mode", default="text", choices=["text", "layout", "table"],
                       help="text: reading order | layout: + box tokens")
    p_ocr.add_argument("--backend", default=None,
                       help=f"default {config.OCR_BACKEND}")
    p_ocr.add_argument("--dpi", type=int, default=None,
                       help=f"render resolution (default {config.OCR_DPI}; 300 for hard scans)")
    p_ocr.add_argument("--limit", type=int, default=None, help="max documents")
    p_ocr.add_argument("--max-pages", type=int, default=None, help="max pages per document")
    p_ocr.add_argument("--redo", action="store_true", help="re-OCR cached pages")
    p_ocr.add_argument("--retry-failed", action="store_true",
                       help="re-OCR only the pages that errored (e.g. GPU timeouts)")
    p_ocr.add_argument("--promote", action="store_true",
                       help="re-index the OCR'd documents so the text becomes searchable")
    p_ocr.add_argument("--list", action="store_true", help="show candidates and exit")
    p_ocr.add_argument("--status", action="store_true", help="coverage + failure report")
    p_ocr.set_defaults(func=cmd_ocr)

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
    config.DB_PATH = config.resolve_db_path(args.db)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
