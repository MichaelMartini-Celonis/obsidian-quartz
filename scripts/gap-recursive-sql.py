#!/usr/bin/env python3
"""Harvest the iterative-SQL / Halloween / fixpoint lineage around CIDR 2025
*Trampoline-Style Queries for SQL* (Lambrecht, Grust, Birler, Neumann).

The paper's own §3.2 (cascading deletes) and §5 (WITH ITERATIVE, DBSpinner,
RaSQL, Datalog°) are the reading list; the Halloween Problem is the update-
vs-scan scheduling issue that paper cites via Tandem NonStop SQL (1987) and
that Wikipedia attributes to Chamberlin/Selinger/Astrahan on System R.

Output lands in ``Inbox/gap-recursive-sql/``; ``import-downloads.py`` files
the cohort under ``Literature/Process Querying/`` via ``COHORT_FOLDERS``.

    scripts/.venv/bin/python scripts/gap-recursive-sql.py
    scripts/.venv/bin/python scripts/gap-recursive-sql.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Inbox" / "gap-recursive-sql"
REPORT = OUT / "_gap-recursive-sql-report.csv"

# (title, authors, override-url-or-None, doi-or-None)
Paper = tuple[str, list[str], str | None, str | None]

PAPERS: list[Paper] = [
    # Seed. Also the cidr-papers.py seed page; this copy is the one the
    # design-doc discussion is actually about.
    ("Trampoline-Style Queries for SQL",
     ["Lambrecht", "Grust", "Birler", "Neumann"],
     "https://vldb.org/cidrdb/papers/2025/p1-lambrecht.pdf", None),
    # Immediate predecessor: WITH ITERATIVE / KEY / TTL — fixpoint without
    # monotonicity, the scheduling of what the union table remembers.
    ("A Fix for the Fixation on Fixpoints",
     ["Hirn", "Grust"],
     "https://vldb.org/cidrdb/papers/2023/p14-hirn.pdf", None),
    # SIGMOD 2020 predecessor of the GOTOs paper: compile PL/SQL iteration
    # into WITH RECURSIVE. The 2021 GOTOs PDF is only on a JS-rendered
    # Tübingen page; this arXiv copy is the same compilation line.
    ("Compiling PL/SQL Away",
     ["Hirn", "Grust"],
     "https://arxiv.org/pdf/1909.03291", "10.1145/3318464.3389703"),
    # Trampolined-style compilation of PL/SQL iteration into WITH RECURSIVE.
    ("One WITH RECURSIVE is Worth Many GOTOs",
     ["Hirn", "Grust"],
     None, "10.1145/3448016.3457272"),
    ("To Iterate Is Human, to Recurse Is Divine — Mapping Iterative Python "
     "to Recursive SQL",
     ["Fischer"], None, "10.18420/BTW2023-73"),
    ("Another Way to Implement Complex Computations: Functional-Style SQL UDFs",
     ["Duta"], None, "10.1145/3511265.3531272"),
    ("Snakes on a Plan: Compiling Python Functions into Plain SQL Queries",
     ["Fischer", "Hirn", "Grust"], None, "10.1145/3514221.3520175"),
    # Original PL trampoline — the compilation technique WITH TRAMPOLINE
    # adapts to SQL.
    ("Trampolined Style",
     ["Ganz", "Friedman", "Wand"],
     "https://legacy.cs.indiana.edu/~dfried/tstyle.pdf",
     "10.1145/317636.317779"),
    # Semi-naive evaluation and the classic recursive-query survey. The
    # trampoline paper's q∞ / working-table loop is this algorithm.
    ("Naive Evaluation of Recursively Defined Relations",
     ["Bancilhon"], None, "10.1007/978-1-4612-4980-1_17"),
    ("An Amateur's Introduction to Recursive Query Processing Strategies",
     ["Bancilhon", "Ramakrishnan"], None, "10.1145/16856.16859"),
    ("Magic Sets and Other Strange Ways to Implement Logic Programs",
     ["Bancilhon", "Maier", "Sagiv", "Ullman"], None, "10.1145/28659.28689"),
    ("On the Power of Magic",
     ["Beeri", "Ramakrishnan"], None, "10.1145/28659.28690"),
    ("Implementation of Logical Query Languages for Databases",
     ["Ullman"], None, "10.1145/3979.3980"),
    # Iterative CTEs that upsert into the union table — the other escape from
    # SQL:1999's all-or-nothing UNION vs UNION ALL.
    ("DBSpinner: Making a Case for Iterative Processing in Databases",
     ["Floratos", "Ghazal", "Sun", "Chen", "Zhang"],
     "https://xiaodongzhang1911.github.io/Zhang-papers/TR-21-2.pdf",
     "10.1109/ICDE51399.2021.00272"),
    ("RaSQL: Greater Power and Performance for Big Data Analytics with "
     "Recursive-aggregate-SQL on Spark",
     ["Gu", "Watanabe", "Mazza", "Shkapsky", "Yang", "Ding", "Zaniolo"],
     None, "10.1145/3299869.3324959"),
    ("Datalog in Wonderland",
     ["Khamis", "Ngo", "Pichler", "Suciu", "Wang"],
     None, "10.1145/3549932.3549935"),
    # Fixpoint over semirings — the modern theory behind whether iteration
    # converges, which WITH RECURSIVE's syntactic restrictions try to enforce.
    ("Convergence of Datalog over (Pre-) Semirings",
     ["Khamis", "Ngo", "Pichler", "Suciu", "Wang"],
     "https://arxiv.org/pdf/2105.14435", "10.1145/3654999"),
    ("Implementation of Recursive Queries",
     ["Zaniolo"],
     "https://web.cs.ucla.edu/~zaniolo/papers/implemention%20of%20recursive%20queries.pdf",
     None),
    # Halloween Problem: the Tandem paper is the trampoline paper's [20];
    # Frana is the IEEE Annals reconstruction; Chamberlin's oral history is
    # the primary System R account Wikipedia cites.
    ("NonStop SQL: A Distributed, High-Performance, High-Availability "
     "Implementation of SQL",
     ["Tandem Database Group"],
     "https://jimgray.azurewebsites.net/papers/tes.pdf", None),
    ("A Well-Intentioned Query and the Halloween Problem",
     ["Frana"], None, "10.1109/MAHC.2002.1010071"),
    ("Oral History Interview with Donald D. Chamberlin",
     ["Chamberlin"],
     "https://commons.lib.jmu.edu/cgi/viewcontent.cgi?article=1212&context=selectedworks",
     None),
]


def candidates(title: str, authors: list[str], url: str | None,
               doi: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(u: str | None, how: str) -> None:
        if u and u not in seen:
            seen.add(u)
            out.append((u, how))

    add(url, "override")
    try:
        add(pf.arxiv_pdf(title, authors), "arxiv")
    except Exception:  # noqa: BLE001
        pass
    try:
        add(pf.openalex_pdf(title, authors, email=pf.git_email()), "openalex")
    except Exception:  # noqa: BLE001
        pass
    dois = [doi] if doi else []
    try:
        hit = pf.dblp_best(title, authors)
    except Exception:  # noqa: BLE001
        hit = None
    if hit:
        for ee in hit.get("ee") or []:
            if str(ee).lower().endswith(".pdf") and not pf.is_bot_walled(ee):
                add(ee, "dblp-ee")
        if hit.get("doi") and hit["doi"] not in dois:
            dois.append(hit["doi"])
    for d in dois:
        try:
            for loc in pf.unpaywall_locations(d, pf.git_email()):
                add(loc, "unpaywall")
        except Exception:  # noqa: BLE001
            pass
    return out


def held_pdf(title: str) -> bool:
    """True only if the index has a *PDF* of this title.

    A YouTube transcript of the CIDR talk must not block fetching the paper.
    """
    try:
        import duckdb
        con = duckdb.connect(str(pf.INDEX_DB), read_only=True)
        rows = con.execute(
            "SELECT rel_path FROM documents WHERE title ILIKE ?",
            [f"%{title[:60]}%"],
        ).fetchall()
        con.close()
    except Exception:  # noqa: BLE001
        return False
    return any((p or "").lower().endswith(".pdf") for (p,) in rows)


def extra_gotos_urls() -> list[tuple[str, str]]:
    """Tübingen has used more than one path for the SIGMOD 2021 PDF."""
    base = "https://db.cs.uni-tuebingen.de"
    return [
        (f"{base}/publications/2021/one-with-recursive-is-worth-many-gotos/"
         "one-with-recursive-is-worth-many-gotos.pdf", "tuebingen"),
        (f"{base}/publications/2021/one-with-recursive-is-worth-many-gotos/"
         "one-with-recursive-is-worth-many-gotos-sigmod.pdf", "tuebingen"),
        (f"{base}/static/papers/one-with-recursive-is-worth-many-gotos.pdf",
         "tuebingen"),
    ]


CHAMBERLIN_URLS = [
    "https://conservancy.umn.edu/bitstream/handle/11299/107215/oh329dc.pdf",
    "https://hdl.handle.net/11299/107215",
]


def run(dry_run: bool) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    held = pf.IndexDedup()
    rows = []
    for title, authors, url, doi in PAPERS:
        if held.contains(title) and held_pdf(title):
            print(f"[{'held':>22}] {title[:74]}", flush=True)
            rows.append({"title": title, "status": "held", "how": "", "file": ""})
            continue
        first: list[tuple[str, str]] = []
        if url:
            first.append((url, "override"))
        if title.startswith("One WITH RECURSIVE"):
            first.extend(extra_gotos_urls())
        if title.startswith("Oral History"):
            first.extend((u, "umn-conservancy") for u in CHAMBERLIN_URLS)
        if title.startswith("A Fix for the Fixation"):
            first.append((
                "https://db.cs.uni-tuebingen.de/publications/2023/"
                "a-fix-for-the-fixation-on-fixpoints/"
                "a-fix-for-the-fixation-on-fixpoints.pdf", "tuebingen"))
        stem = pf.safe_stem(authors[:2], title)
        dest = OUT / f"{stem}.pdf"
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"[{'cached':>22}] {title[:74]}", flush=True)
            rows.append({"title": title, "status": "cached", "how": "disk",
                         "file": str(dest.relative_to(ROOT))})
            continue
        if dry_run:
            print(f"[{'would-fetch':>22}] {title[:60]}", flush=True)
            rows.append({"title": title, "status": "dry-run", "how": "", "file": ""})
            continue
        got = False
        last = "no locations"
        how_used = ""
        for loc, how in first:
            print(f"  trying {how}: {loc[:90]}", flush=True)
            ok, detail = pf.download_pdf(sess, loc, dest, timeout=45)
            if ok:
                got, how_used, last = True, how, detail
                break
            last = f"{how}: {detail}"
        if not got:
            print(f"  resolving OA backends for: {title[:50]}", flush=True)
            locs = candidates(title, authors, None, doi)
            for loc, how in locs:
                print(f"  trying {how}: {loc[:90]}", flush=True)
                ok, detail = pf.download_pdf(sess, loc, dest, timeout=45)
                if ok:
                    got, how_used, last = True, how, detail
                    break
                last = f"{how}: {detail}"
        status = "downloaded" if got else f"failed: {last}"
        print(f"[{status:>22}] {title[:74]}", flush=True)
        rows.append({
            "title": title,
            "status": status,
            "how": how_used,
            "file": str(dest.relative_to(ROOT)) if got else "",
        })
    with REPORT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["title", "status", "how", "file"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {REPORT.relative_to(ROOT)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
