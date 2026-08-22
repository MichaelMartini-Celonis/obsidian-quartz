#!/usr/bin/env python3
"""One-off gap-closing harvest: object-centric case notions / cohorts.

Two bodies of prior art turned out to be absent from `Literature/` while
writing the Context Model draft on object-centric case notions:

1. **Event-case correlation** — inferring a case identifier when the log does
   not carry one. This is the pre-object-centric ancestor of "which entities
   belong to the same case?" and the garden only held the *uncertain case
   identifier* branch of it.
2. **Cohort definition in clinical informatics** — OHDSI/OMOP, i2b2 and the
   computable-phenotype literature. The most mature declarative,
   rule-authored, materialised cohort tooling in existence, and the closest
   external analogue to rule-based cohort discovery over an entity graph.

Resolution goes through `paperfetch` (arXiv → DBLP/Unpaywall → OpenAlex →
Semantic Scholar) with explicit URL overrides where a paper is only available
from a known repository. Output lands in `Inbox/gap-cohorts/` for
`import-downloads.py` to file and the indexer to pick up.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Inbox" / "gap-cohorts"
REPORT = OUT / "_gap-cohorts-report.csv"

# (topic, title, authors, direct-url-or-None, doi-or-None)
PAPERS: list[tuple[str, str, list[str], str | None, str | None]] = [
    # --- 1. Event-case correlation / case-id inference -------------------
    (
        "event-case-correlation",
        "Event correlation for process discovery from web service interaction logs",
        ["Motahari-Nezhad", "Saint-Paul", "Casati", "Benatallah"],
        None,
        "10.1007/s00778-010-0203-9",
    ),
    (
        "event-case-correlation",
        "Correlation Miner: Mining Business Process Models and Event "
        "Correlations without Case Identifier",
        ["Pourmirza", "Dijkman", "Grefen"],
        None,
        "10.1142/S0218843017400019",
    ),
    (
        "event-case-correlation",
        "Deducing Case IDs for Unlabeled Event Logs",
        ["Bayomie", "Awad", "Ezat"],
        None,
        "10.1007/978-3-319-42887-1_20",
    ),
    (
        "event-case-correlation",
        "Event-Case Correlation for Process Mining Using Probabilistic Optimization",
        ["Bayomie", "Di Ciccio", "Mendling"],
        None,
        "10.1016/j.is.2022.102064",
    ),
    (
        "event-case-correlation",
        "Discovering Process Models from Uncertain Event Data",
        ["Pegoraro", "Uysal", "van der Aalst"],
        None,
        None,
    ),
    # --- 2. Clinical cohort definition -----------------------------------
    (
        "clinical-cohorts",
        "Serving the enterprise and beyond with informatics for integrating "
        "biology and the bedside (i2b2)",
        ["Murphy", "Weber", "Mendis", "Gainer", "Chueh", "Churchill", "Kohane"],
        "https://europepmc.org/articles/PMC2732232?pdf=render",
        "10.1197/jamia.M3191",
    ),
    (
        "clinical-cohorts",
        "Observational Health Data Sciences and Informatics (OHDSI): "
        "Opportunities for Observational Researchers",
        ["Hripcsak", "Duke", "Shah", "Reich", "Huser", "Schuemie", "Suchard"],
        "https://europepmc.org/articles/PMC4815923?pdf=render",
        "10.3233/978-1-61499-564-7-574",
    ),
    (
        "clinical-cohorts",
        "PheKB: a catalog and workflow for creating electronic phenotype "
        "algorithms for transportability",
        ["Kirby", "Speltz", "Rasmussen", "Basford", "Gottesman", "Peissig"],
        "https://europepmc.org/articles/PMC5013887?pdf=render",
        "10.1093/jamia/ocv202",
    ),
    (
        "clinical-cohorts",
        "Desiderata for the development of next-generation electronic health "
        "record phenotype libraries",
        ["Chapman", "Mumtaz", "Rasmussen", "Karwath", "Gkoutos"],
        None,
        "10.1093/gigascience/giab059",
    ),
    (
        "clinical-cohorts",
        "Evaluating the impact of database heterogeneity on observational "
        "study results",
        ["Madigan", "Ryan", "Schuemie", "Stang", "Overhage", "Hartzema"],
        "https://europepmc.org/articles/PMC3966715?pdf=render",
        "10.1093/aje/kwt010",
    ),
    (
        "clinical-cohorts",
        "A standardized analytics pipeline for reliable and rapid development "
        "and validation of prediction models using observational health data",
        ["Reps", "Williams", "You", "Cepeda", "Han", "Ryan"],
        "https://europepmc.org/articles/PMC7082848?pdf=render",
        "10.1016/j.cmpb.2020.105331",
    ),
]

# Papers whose only open copy is a landing page that `download_pdf` can follow.
FALLBACKS: dict[str, list[str]] = {
    "Event correlation for process discovery from web service interaction logs": [
        "https://web.archive.org/web/2019/https://www.cse.unsw.edu.au/~boualem/paper/vldbj2011.pdf",
        "https://api.semanticscholar.org/graph/v1/paper/search?query="
        "Event+correlation+for+process+discovery",
    ],
    "Deducing Case IDs for Unlabeled Event Logs": [
        "https://diciccio.net/claudio/preprints/Bayomie2016-DeducingCaseIDs.pdf",
    ],
}


def resolve(sess, title: str, authors: list[str], url: str | None,
            doi: str | None) -> tuple[str | None, str]:
    """Return (url, how) for the best open copy we can find."""
    if url:
        return url, "override"
    for fn, how in (
        (lambda: pf.arxiv_pdf(title, authors), "arxiv"),
        (lambda: pf.openalex_pdf(title, authors), "openalex"),
        (lambda: pf.semanticscholar_pdf(title, authors), "semanticscholar"),
    ):
        try:
            got = fn()
        except Exception:
            got = None
        if got:
            return got, how
    if doi:
        try:
            for loc in pf.unpaywall_locations(doi, pf.git_email()):
                return loc, "unpaywall"
        except Exception:
            pass
    for loc in FALLBACKS.get(title, []):
        return loc, "fallback"
    return None, "unresolved"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    rows = []
    for topic, title, authors, url, doi in PAPERS:
        found, how = resolve(sess, title, authors, url, doi)
        status = "no-open-copy"
        dest = ""
        if found:
            stem = pf.safe_stem(authors[:1], title)
            path = OUT / f"{stem}.pdf"
            ok, detail = pf.download_pdf(sess, found, path)
            status = "downloaded" if ok else f"failed: {detail}"
            dest = str(path.relative_to(ROOT)) if ok else ""
        print(f"[{status:>28}] ({how}) {title[:70]}")
        rows.append({
            "topic": topic, "title": title, "how": how,
            "url": found or "", "status": status, "file": dest,
        })

    with REPORT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    got = sum(1 for r in rows if r["status"] == "downloaded")
    print(f"\n{got}/{len(rows)} downloaded → {OUT}")
    print(f"report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
