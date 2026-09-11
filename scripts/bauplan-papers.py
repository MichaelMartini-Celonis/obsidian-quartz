#!/usr/bin/env python3
"""Harvest recent Bauplan Labs papers (arXiv, 2025–2026) into Inbox/.

The blog and product docs are already registered in ``import-blogs.py`` /
``import-docs.py``. This is the citation half: the lakehouse / FaaS / data-contract
/ agent-skill papers the company has put on arXiv. Output lands in
``Inbox/bauplan-papers/``; ``import-downloads.py`` files the cohort under
``Literature/Data Platforms/Bauplan/`` via ``COHORT_FOLDERS``.

**Shelf role (vs ``gap-agentic-sql.py``):** Bauplan is *safe agent execution*
(branch → verify → merge, data contracts, plan-first validation) — not a
Text-to-SQL accuracy claim. Enterprise Text-to-SQL realism (Stonebraker/Wenz,
BEAVER, RUBICON, Spider 2.0, repair agents) lives in ``gap-agentic-sql.py`` and
``Outbox/agentic-sql-reliability/``.

    scripts/.venv/bin/python scripts/bauplan-papers.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Inbox" / "bauplan-papers"
REPORT = OUT / "_bauplan-papers-report.csv"

# (arxiv-id, title, lead authors) — 2025–2026 only.
PAPERS: list[tuple[str, str, list[str]]] = [
    ("2607.13339", "Not Your Usual Type(s): Data contracts as types across languages and engines",
     ["Montana", "Marc", "Bigon", "Tagliabue"]),
    ("2607.08319", "GitLake: Git-for-data for the agentic lakehouse",
     ["Sheng", "Wang", "Barros", "Montana", "Tagliabue", "Bigon"]),
    ("2606.01185", "Skill Issues: Data-Centric Optimization of Lakehouse Agents",
     ["Schneider", "Ghilardi", "Piccinini", "Tagliabue"]),
    ("2603.13380", "Querying Everything Everywhere All at Once: Supervaluationism for the Agentic Lakehouse",
     ["Tagliabue"]),
    ("2602.10387", "Test-Time Optimization of Physical Query Plans with LLMs",
     ["Erol", "Hao", "Bianchi", "Greco", "Tagliabue", "Zou"]),
    ("2602.02335", "Building a Correct-by-Design Lakehouse. Data Contracts, Versioning, and Transactional Pipelines for Humans and Agents",
     ["Sheng", "Wang", "Barros", "Montana", "Tagliabue", "Bigon"]),
    ("2511.16402", "Trustworthy AI in the Agentic Lakehouse: from Concurrency to Governance",
     ["Tagliabue", "Bianchi", "Greco"]),
    ("2510.18897", "AI for Distributed Systems Design: Scalable Cloud Optimization Through Repeated LLMs Sampling and Simulators",
     ["Tagliabue"]),
    ("2510.09567", "Safe, Untrusted, Proof-Carrying AI Agents: toward the agentic lakehouse",
     ["Tagliabue", "Greco"]),
    ("2505.13750", "Eudoxia: a FaaS scheduling simulator for the composable lakehouse",
     ["Srivastava", "Tagliabue", "Greco"]),
    ("2504.06151", "Zerrow: True Zero-Copy Arrow Pipelines in Bauplan",
     ["Dai", "Tagliabue", "Arpaci-Dusseau", "Caraza-Harter"]),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    held = pf.IndexDedup()
    rows = []
    for arxiv_id, title, authors in PAPERS:
        if held.contains(title):
            print(f"[                    held] {title[:70]}")
            rows.append({"arxiv": arxiv_id, "title": title, "status": "held", "file": ""})
            continue
        url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        stem = pf.safe_stem(authors[:1], title)
        path = OUT / f"{stem}.pdf"
        ok, detail = pf.download_pdf(sess, url, path)
        status = "downloaded" if ok else f"failed: {detail}"
        print(f"[{status:>28}] {title[:70]}")
        rows.append({
            "arxiv": arxiv_id, "title": title, "status": status,
            "file": str(path.relative_to(ROOT)) if ok else "",
        })
    with REPORT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
