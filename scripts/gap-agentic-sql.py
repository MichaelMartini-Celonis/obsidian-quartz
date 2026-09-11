#!/usr/bin/env python3
"""Harvest the **agentic SQL / PQL reliability** cohort into Inbox/.

Closes the ``agentic-sql-reliability`` topic in ``scripts/gap-topics.json``:
Stonebraker/Wenz enterprise Text-to-SQL (RUBICON and related), Spider 2.0 and
agent repair baselines, human SQL HCI classics, ambiguity/abstention work, and
cited schema-linking papers. BEAVER, BenchPress, QueryVis and the CIDR
benchmark critiques are already held — IndexDedup skips them.

Bauplan lakehouse / safe-execution papers stay in ``scripts/bauplan-papers.py``
(orthogonal shelf: branch → verify → publish, not Text-to-SQL SOTA).

Stonebraker's CACM Blog@CACM piece is imported via ``scripts/import-blogs.py``
(source key ``stonebraker-cacm``), not here.

Output: ``Inbox/gap-agentic-sql/``; ``import-downloads.py`` files the cohort
under ``Literature/Process Mining/AI/`` via ``COHORT_FOLDERS``.

    scripts/.venv/bin/python scripts/gap-agentic-sql.py
    scripts/.venv/bin/python scripts/gap-agentic-sql.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Inbox" / "gap-agentic-sql"
REPORT = OUT / "_gap-agentic-sql-report.csv"

# (title, authors, override-url-or-None, doi-or-None)
Paper = tuple[str, list[str], str | None, str | None]

PAPERS: list[Paper] = [
    # --- Stonebraker / Wenz lineage (BEAVER + BenchPress already held) -------
    ("RUBICON: Agentic AI for Messy Enterprise Data",
     ["Wenz", "Treutwein", "Demiralp", "Stonebraker"],
     "https://arxiv.org/pdf/2604.21413", "10.48550/arXiv.2604.21413"),
    # Alternate / earlier framing of the same arXiv family (dedup if identical).
    ("An Alternate Agentic AI Architecture (It's About the Data)",
     ["Wenz", "Treutwein", "Demiralp", "Stonebraker"],
     "https://arxiv.org/pdf/2604.21413", None),

    # --- Enterprise / hard Text-to-SQL benchmarks & agents -------------------
    ("Spider 2.0: Evaluating Language Models on Real-World Enterprise "
     "Text-to-SQL Workflows",
     ["Lei", "Yu"],
     "https://arxiv.org/pdf/2411.07763", "10.48550/arXiv.2411.07763"),
    ("Can LLM Already Serve as A Database Interface? A BIg Bench for "
     "Large-Scale Database Grounded Text-to-SQLs",
     ["Li"],
     "https://arxiv.org/pdf/2305.03111", "10.48550/arXiv.2305.03111"),

    # --- Decomposition / schema linking / multi-agent repair -----------------
    ("DIN-SQL: Decomposed In-Context Learning of Text-to-SQL with Self-Correction",
     ["Pourreza", "Rafiei"],
     "https://arxiv.org/pdf/2304.11015", "10.48550/arXiv.2304.11015"),
    ("MAC-SQL: A Multi-Agent Collaborative Framework for Text-to-SQL",
     ["Wang"],
     "https://arxiv.org/pdf/2312.11242", "10.48550/arXiv.2312.11242"),
    ("CHASE-SQL: Multi-Path Reasoning and Preference Optimized Candidate "
     "Selection in Text-to-SQL",
     ["Pourreza"],
     "https://arxiv.org/pdf/2410.01943", "10.48550/arXiv.2410.01943"),
    ("CHESS: Contextual Harnessing for Efficient SQL Synthesis",
     ["Talaei"],
     "https://arxiv.org/pdf/2405.16755", "10.48550/arXiv.2405.16755"),
    ("Re-examining the Role of Schema Linking in Text-to-SQL",
     ["Lei"],
     "https://arxiv.org/pdf/2010.09117", None),

    # --- Ambiguity / abstention / reliability --------------------------------
    ("AmbiSQL: Interactive Ambiguity Detection and Resolution for Text-to-SQL",
     ["Ding"],
     "https://arxiv.org/pdf/2508.15276", "10.48550/arXiv.2508.15276"),
    ("Reliable Text-to-SQL with Adaptive Abstention",
     ["Chen"],
     "https://arxiv.org/pdf/2501.10858", "10.48550/arXiv.2501.10858"),

    # --- Surveys / SOTA context ----------------------------------------------
    ("A Survey of Text-to-SQL in the Era of LLMs: Techniques, Advances, "
     "Challenges, and Future Directions",
     ["Liu"],
     "https://arxiv.org/pdf/2408.05109", "10.48550/arXiv.2408.05109"),

    # --- Human SQL HCI (open copies where they exist) ------------------------
    ("Human Factors Studies of Database Query Languages: A Survey and Assessment",
     ["Reisner"],
     None, "10.1145/356835.356837"),
    ("User Errors in Database Query Composition",
     ["Smelcer"],
     None, "10.1006/ijhc.1995.1017"),
    ("Errors and Complications in SQL Query Formulation",
     ["Taipalus", "Siponen", "Vartiainen"],
     None, "10.1145/3231712"),
    ("Explaining Causes Behind SQL Query Formulation Errors",
     ["Taipalus"],
     "https://jyx.jyu.fi/bitstreams/c64cad6d-9c84-439e-b2ff-4fb16c545481/download",
     "10.1109/FIE44824.2020.9274114"),
    ("Identifying SQL Misconceptions of Novices: Findings from a Think-Aloud Study",
     ["Miedema"],
     None, "10.1145/3446871.3469759"),
    ("The effects of information request ambiguity and construct incongruence "
     "on query development",
     ["Borthick"],
     None, "10.1016/S0167-9236(01)00097-5"),

    # --- Process-query language design (Celonis PQL — not HCI, but primary) --
    ("Celonis PQL: A Query Language for Process Mining",
     ["Vogelgesang"],
     "https://opus.bibliothek.uni-augsburg.de/opus4/frontdoor/deliver/index/"
     "docId/95909/file/95909.pdf",
     "10.1007/978-3-030-92875-9_13"),
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
        try:
            add(pf.unpaywall_pdf(d, pf.git_email()), "unpaywall")
        except Exception:  # noqa: BLE001
            pass
    return out


def held_pdf(title: str) -> bool:
    """True only if the index has a *PDF* of this title."""
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


def run(dry_run: bool) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    held = pf.IndexDedup()
    rows: list[dict] = []
    seen_titles: set[str] = set()
    for title, authors, url, doi in PAPERS:
        key = pf.norm(title)
        if key in seen_titles:
            rows.append({"title": title, "status": "duplicate-in-list",
                         "how": "", "file": ""})
            continue
        seen_titles.add(key)
        if held.contains(title) and held_pdf(title):
            print(f"[{'held':>22}] {title[:74]}", flush=True)
            rows.append({"title": title, "status": "held", "how": "", "file": ""})
            continue
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
        first: list[tuple[str, str]] = []
        if url:
            first.append((url, "override"))
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
            for loc, how in candidates(title, authors, None, doi):
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
    n_ok = sum(1 for r in rows if r["status"] in ("downloaded", "cached", "held"))
    n_fail = sum(1 for r in rows if str(r["status"]).startswith("failed"))
    print(f"summary: ok={n_ok} failed={n_fail} total={len(rows)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
