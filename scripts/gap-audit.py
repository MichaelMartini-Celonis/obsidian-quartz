#!/usr/bin/env python3
"""Audit the corpus for **topical gaps** — concepts the library talks *around*
but does not actually hold a work about.

Motivation: a plain keyword count is a bad coverage signal. Searching the index
for "Whitehead" returns 15 documents — but every one is a *surname in a
reference list* (Spencer Whitehead, Jim Whitehead, Russell & Whitehead), not a
work about Alfred North Whitehead's process philosophy. Conversely "Anchor
Modeling" returns 126 documents *and* the library really does hold the paper and
the whole blog.

So this tool scores each concept on four independent axes and combines them:

  1. **mentions**  - documents whose text contains any probe term at all.
     Cheap, but dominated by incidental citations.
  2. **substantive** - documents where a term recurs at least ``--min-repeats``
     times. A passing citation appears once; a document *about* a topic repeats
     its central term. This is the axis that separates signal from surnames.
  3. **holdings**  - documents whose *title or path* matches a term, i.e. the
     library demonstrably holds a work on the concept.
  4. **focused**   - documents where a term recurs at least ``--focus`` times.
     Titles are a lossy index of content: an encyclopedia bundle and a
     monograph on persistence both treat *presentism* at length while neither
     filename says so. Sustained repetition establishes that the concept is
     genuinely treated somewhere in the collection even when no title admits it.

which yields a coverage verdict per concept:

  ``absent``       nothing at all — a true hole in the collection.
  ``mention-only`` cited in passing, but no work about it. The subtle gap:
                   the library knows the word and not the literature.
  ``thin``         discussed in passing depth, but no work is *about* it —
                   neither a matching title nor any sustained treatment.
  ``covered``      substantive discussion plus either a held work (title/path
                   match) or a document that treats the concept at length.

Topic maps live in ``scripts/gap-topics.json`` (themes -> concepts -> probe
terms), so the same tool can audit any subject area later. Reports are written
to ``imports/gap-audit-<topic>.{md,csv}``.

Usage:
  scripts/.venv/bin/python scripts/gap-audit.py list
  scripts/.venv/bin/python scripts/gap-audit.py audit --topic temporality-ontology
  scripts/.venv/bin/python scripts/gap-audit.py audit --topic temporality-ontology --semantic
  scripts/.venv/bin/python scripts/gap-audit.py audit --all --min-repeats 8

``--semantic`` additionally runs each concept's ``probe`` sentence through the
hybrid (vector + BM25) search engine and records the best-scoring document, so
you can eyeball *what the library offers instead*. It needs the embedding model
and is much slower, so it is opt-in.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
TOPIC_MAP = Path(__file__).resolve().parent / "gap-topics.json"
INDEX_DB = DOCS_ROOT / "search" / "index.duckdb"
REPORT_DIR = DOCS_ROOT / "imports"

VERDICTS = ("absent", "mention-only", "thin", "covered")


# ---------------------------------------------------------------------------
# topic map
# ---------------------------------------------------------------------------

@dataclass
class Concept:
    label: str
    terms: list[str]
    probe: str = ""
    canonical: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Theme:
    name: str
    concepts: list[Concept]
    note: str = ""


@dataclass
class Topic:
    key: str
    title: str
    question: str
    themes: list[Theme]


def load_topics(path: Path = TOPIC_MAP) -> dict[str, Topic]:
    if not path.exists():
        sys.exit(f"topic map not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    topics: dict[str, Topic] = {}
    for key, t in raw.get("topics", {}).items():
        themes = []
        for th in t.get("themes", []):
            concepts = [
                Concept(label=c["label"], terms=list(c["terms"]),
                        probe=c.get("probe", ""), canonical=list(c.get("canonical", [])),
                        note=c.get("note", ""))
                for c in th.get("concepts", [])
            ]
            themes.append(Theme(name=th["name"], concepts=concepts,
                                note=th.get("note", "")))
        topics[key] = Topic(key=key, title=t.get("title", key),
                            question=t.get("question", ""), themes=themes)
    return topics


# ---------------------------------------------------------------------------
# index access
# ---------------------------------------------------------------------------

def connect():
    try:
        import duckdb
    except ImportError:
        sys.exit("duckdb not installed in this venv")
    if not INDEX_DB.exists():
        sys.exit(f"search index not found: {INDEX_DB}\n"
                 "build it with: scripts/.venv/bin/python -m search.cli index")
    con = duckdb.connect(str(INDEX_DB), read_only=True)
    # One pass over chunks; every probe then runs against this materialised view.
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE doctext AS
        SELECT d.doc_id, d.rel_path, d.title, d.topic, t.txt
        FROM documents d
        JOIN (SELECT doc_id, string_agg(text, ' ') AS txt FROM chunks GROUP BY doc_id) t
          USING (doc_id)
        """
    )
    return con


def term_regex(term: str) -> str:
    r"""Case-insensitive, word-bounded RE2 pattern for a probe term.

    Word boundaries matter more than they look: a plain substring search for
    "Heidegger" also matches *Scheidegger*, and "BORO" matches *borough* — which
    is exactly how a keyword count fabricates coverage that isn't there. The
    ``\b`` anchors are dropped at an end that already begins/ends with a
    non-word character, where they would never match.
    """
    esc = re.escape(term)
    left = r"\b" if re.match(r"\w", term) else ""
    right = r"\b" if re.search(r"\w$", term) else ""
    return f"(?i){left}{esc}{right}"


def audit_concept(con, c: Concept, min_repeats: int, focus: int) -> dict:
    """Score one concept in a single pass over the candidate documents.

    A cheap ``LIKE`` prefilter narrows the corpus to documents containing any
    term as a substring; the (much more expensive) word-bounded regex counting
    then runs only on those survivors.
    """
    terms = c.terms
    per_term: dict[str, dict] = {}
    agg = {"mentions": 0, "substantive": 0, "holdings": 0, "focused": 0}
    examples: list[tuple[str, int]] = []

    if terms:
        n_exprs = ["len(regexp_extract_all(txt, ?))" for _ in terms]
        t_exprs = ["(regexp_matches(coalesce(title,'') || ' ' || rel_path, ?))"
                   for _ in terms]
        select_cols = ", ".join(
            [f"{e} AS n{i}" for i, e in enumerate(n_exprs)]
            + [f"{e} AS t{i}" for i, e in enumerate(t_exprs)]
        )
        prefilter = " OR ".join(["lower(txt) LIKE lower(?)"] * len(terms))
        # Parameters bind in order of appearance in the SQL text: the prefilter
        # sits in the first CTE, then the text regexes, then the title regexes.
        regexes = [term_regex(t) for t in terms]
        params = [f"%{t}%" for t in terms] + regexes + regexes

        aggs = []
        for i in range(len(terms)):
            aggs += [
                f"count(*) FILTER (WHERE n{i} > 0)",
                f"count(*) FILTER (WHERE n{i} >= {int(min_repeats)})",
                f"count(*) FILTER (WHERE t{i} AND n{i} > 0)",
                f"count(*) FILTER (WHERE n{i} >= {int(focus)})",
            ]
        total_n = " + ".join(f"n{i}" for i in range(len(terms)))

        sql = f"""
            WITH cand AS (
                SELECT rel_path, title, txt FROM doctext WHERE {prefilter}
            ), scored AS (
                SELECT rel_path, {select_cols} FROM cand
            )
            SELECT {', '.join(aggs)},
                   list(rel_path ORDER BY ({total_n}) DESC)[1:4],
                   list(({total_n}) ORDER BY ({total_n}) DESC)[1:4]
            FROM scored
        """
        row = con.execute(sql, params).fetchone()
        for i, t in enumerate(terms):
            r = {"mentions": row[4 * i] or 0, "substantive": row[4 * i + 1] or 0,
                 "holdings": row[4 * i + 2] or 0, "focused": row[4 * i + 3] or 0}
            per_term[t] = r
            # Documents can match several terms; take the max rather than the sum
            # so a concept with many synonyms is not inflated.
            for k in agg:
                agg[k] = max(agg[k], r[k])
        paths, counts = row[-2] or [], row[-1] or []
        examples = [(p, int(n or 0)) for p, n in zip(paths, counts)]

    if agg["mentions"] == 0:
        verdict = "absent"
    elif agg["substantive"] == 0:
        verdict = "mention-only"
    elif agg["holdings"] > 0 or agg["focused"] > 0:
        verdict = "covered"
    else:
        verdict = "thin"
    return {
        "label": c.label, "terms": c.terms, "note": c.note,
        "canonical": c.canonical, "verdict": verdict,
        **agg, "per_term": per_term, "examples": examples,
    }


def add_semantic(con, results: list[dict], concepts: list[Concept]) -> None:
    """Attach the best hybrid-search hit for each concept's probe sentence."""
    sys.path.insert(0, str(DOCS_ROOT))
    from search import query as querymod
    from search.embeddings import get_embedder

    embedder = get_embedder()
    for res, c in zip(results, concepts):
        if not c.probe:
            continue
        try:
            hits = querymod.search(con, embedder, c.probe, k=3)
        except Exception as exc:  # noqa: BLE001
            res["semantic"] = f"(error: {type(exc).__name__})"
            continue
        res["semantic"] = "; ".join(f"{h.rel_path} ({h.score:.4f})" for h in hits) or "(none)"


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

MARK = {"absent": "MISSING", "mention-only": "mention only",
        "thin": "thin", "covered": "covered"}


def write_report(topic: Topic, audited: list[tuple[Theme, list[dict]]],
                 min_repeats: int, focus: int) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORT_DIR / f"gap-audit-{topic.key}.md"
    csv_path = REPORT_DIR / f"gap-audit-{topic.key}.csv"

    counts = {v: 0 for v in VERDICTS}
    for _, results in audited:
        for r in results:
            counts[r["verdict"]] += 1

    lines = [f"# Gap audit — {topic.title}", ""]
    if topic.question:
        lines += [f"> {topic.question}", ""]
    lines += [
        f"Audited against `search/index.duckdb`; a document counts as "
        f"*substantive* when a probe term recurs at least **{min_repeats}** times, "
        f"and as *focused* on the concept at **{focus}** or more.",
        "",
        "| verdict | concepts |",
        "|---|---|",
    ]
    for v in VERDICTS:
        lines.append(f"| {MARK[v]} | {counts[v]} |")
    lines.append("")

    for theme, results in audited:
        lines += [f"## {theme.name}", ""]
        if theme.note:
            lines += [theme.note, ""]
        lines += ["| concept | verdict | mentions | substantive | focused | held | closest holding |",
                  "|---|---|---|---|---|---|---|"]
        for r in results:
            ex = r["examples"][0][0] if r["examples"] else "—"
            ex = ex.replace("|", "/")
            lines.append(
                f"| {r['label']} | **{MARK[r['verdict']]}** | {r['mentions']} | "
                f"{r['substantive']} | {r['focused']} | {r['holdings']} | `{ex}` |"
            )
        lines.append("")
        missing = [r for r in results if r["verdict"] in ("absent", "mention-only")]
        if missing:
            lines += ["<details><summary>Acquisition targets</summary>", ""]
            for r in missing:
                for w in r["canonical"]:
                    lines.append(f"- **{r['label']}** — {w}")
            lines += ["", "</details>", ""]

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["theme", "concept", "verdict", "mentions", "substantive",
                    "focused", "holdings", "terms", "canonical_works",
                    "top_document", "top_occurrences", "semantic_best"])
        for theme, results in audited:
            for r in results:
                ex, n = (r["examples"][0] if r["examples"] else ("", 0))
                w.writerow([theme.name, r["label"], r["verdict"], r["mentions"],
                            r["substantive"], r["focused"], r["holdings"],
                            "; ".join(r["terms"]), "; ".join(r["canonical"]),
                            ex, n, r.get("semantic", "")])
    return md_path, csv_path


def print_console(topic: Topic, audited: list[tuple[Theme, list[dict]]]) -> None:
    print(f"\n=== {topic.title} ===")
    for theme, results in audited:
        print(f"\n{theme.name}")
        for r in results:
            print(f"  {MARK[r['verdict']]:13s} {r['label'][:46]:46s} "
                  f"mentions={r['mentions']:4d} substantive={r['substantive']:4d} "
                  f"focused={r['focused']:3d} held={r['holdings']:3d}")
    counts = {v: 0 for v in VERDICTS}
    for _, results in audited:
        for r in results:
            counts[r["verdict"]] += 1
    total = sum(counts.values())
    print(f"\nsummary over {total} concepts: " +
          ", ".join(f"{MARK[v]}={counts[v]}" for v in VERDICTS))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_list(topics: dict[str, Topic]) -> int:
    print("topics in", TOPIC_MAP.relative_to(DOCS_ROOT))
    for key, t in topics.items():
        n = sum(len(th.concepts) for th in t.themes)
        print(f"  {key:26s} {n:3d} concepts / {len(t.themes)} themes — {t.title}")
    return 0


def run_audit(topic: Topic, min_repeats: int, focus: int, semantic: bool) -> None:
    con = connect()
    try:
        audited: list[tuple[Theme, list[dict]]] = []
        for theme in topic.themes:
            results = [audit_concept(con, c, min_repeats, focus)
                       for c in theme.concepts]
            if semantic:
                add_semantic(con, results, theme.concepts)
            audited.append((theme, results))
    finally:
        con.close()
    print_console(topic, audited)
    md, csvp = write_report(topic, audited, min_repeats, focus)
    print(f"\nwrote {md.relative_to(DOCS_ROOT)}")
    print(f"wrote {csvp.relative_to(DOCS_ROOT)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=False)
    sub.add_parser("list", help="list the topic maps available")
    pa = sub.add_parser("audit", help="audit a topic against the index")
    pa.add_argument("--topic", help="topic key (see `list`)")
    pa.add_argument("--all", action="store_true", help="audit every topic")
    pa.add_argument("--min-repeats", type=int, default=5,
                    help="term occurrences for a document to count as substantive")
    pa.add_argument("--focus", type=int, default=20,
                    help="term occurrences for a document to count as a work "
                         "focused on the concept, whatever its title says")
    pa.add_argument("--semantic", action="store_true",
                    help="also record the best hybrid-search hit per concept (slow)")
    args = p.parse_args(argv)

    topics = load_topics()
    if args.cmd in (None, "list"):
        return cmd_list(topics)

    if args.all:
        selected = list(topics.values())
    elif args.topic:
        if args.topic not in topics:
            sys.exit(f"unknown topic {args.topic!r}; known: {', '.join(topics)}")
        selected = [topics[args.topic]]
    else:
        return cmd_list(topics)

    for t in selected:
        run_audit(t, args.min_repeats, args.focus, args.semantic)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
