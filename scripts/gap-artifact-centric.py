#!/usr/bin/env python3
"""Gap-closing harvest: **can artifact-centric / declarative process models be
simulated the way BPMN models are?**

The question this round answers is narrow and the audit
(``gap-audit.py audit --topic artifact-centric-simulation``) is what makes it
answerable. Business process simulation is an *imperative*-model discipline: a
BPS model is a BPMN model or a Petri net plus branching probabilities, activity
durations and an arrival process, and the engine plays the token game. Hull's
artifact-centric models and the Guard-Stage-Milestone lifecycle have no token
game — behaviour is whatever the guards, milestones and constraints admit. So
the question is not only whether the library holds the answer, but whether an
answer exists.

The audit says it mostly does not, and it locates the boundary precisely: the
collection is strong on artifact-centric **verification** (DCDS, hierarchical
artifact systems, decidability) and on the **object-centric** simulation that
came later, and holds essentially nothing on the four things in between. This
harvest is organised by those findings rather than by author or venue, which is
why the cohorts are named after the audit's themes.

Five cohorts, each closing a specific verdict:

``foundations``
    The primary sources for the models being asked about. The audit found
    Guard-Stage-Milestone *thin* with **zero holdings** — 42 mentions, all of
    them inside papers about verifying or monitoring GSM, none of them the
    papers that define it. A library cannot be asked whether GSM is simulable
    when it does not hold Nigam & Caswell, the two 2010-11 GSM papers, or the
    operational semantics they refer to.

``enactment``
    Engines, not simulators — Barcelona, E-GSM, PHILharmonicFlows, the DCR
    execution semantics. This distinction is the crux of the whole question and
    it is invisible without the engine papers: an engine answers *what happens
    next given this event*, a simulator answers *what is the mean cycle time at
    this arrival rate*. The artifact-centric community built the former.

``declarative-simulation``
    What "simulating a declarative model" actually means in the literature:
    **log generation**. Since a constraint model cannot be played forward
    token-by-token, one samples from the set of traces satisfying it — via
    automata (Di Ciccio's MINERful), via SAT/Alloy (Ackermann's MuDePS, the
    RuM log generators), via ASP. The audit's `simulating declarative` and
    `declarative simulation` probes both returned **zero documents**, which is
    the single largest hole. Note what these tools do *not* emit: timestamps
    drawn from distributions, resources, queues. They generate behaviour, not
    performance — which is the answer to the user's question, and it is only
    demonstrable with the papers in hand.

``paradigm-comparison``
    The one theme the audit returned **MISSING outright**. There is a real
    declarative-vs-imperative comparative literature and it is about *humans* —
    understandability, maintainability, cognitive dimensions, hierarchy,
    hybrid notations. Nobody in it compares the paradigms on analysability.
    Holding it is what turns "nobody simulated GSM" from an absence of evidence
    into a documented choice.

``object-centric-bps``
    Where the quantitative question actually got answered — by changing the
    formalism. Object-centric Petri nets and data-aware BPMN keep the token
    game and add objects and data, so the discrete-event machinery still
    applies. The library holds van der Aalst's object-centric simulation paper
    but not the data-aware BPS line or the stochastic object-centric work.

Resolution is the usual ``paperfetch`` ladder (override → arXiv → OpenAlex →
Unpaywall-by-DOI → Semantic Scholar → DBLP ``ee``) with **four title-indexed
archives** added, because a first dry run resolved only 3 of the 15
``foundations`` targets: this material is from 2003-2013, and old means either
paywalled or self-hosted.

* **CEUR-WS** — the demo and workshop tracks are where the *tools* were
  published (MuDePS, RuM, the ACSI Hub, SIMPDA's declarative-to-imperative
  translation). CEUR is fully open but Unpaywall indexes it patchily, and a
  volume's index page gives title → PDF directly.
* **Hajo Reijers' publication page** — self-hosts the BPMDS/BPM-workshop papers
  of the ``paradigm-comparison`` cohort, which are Springer LNBIP and otherwise
  closed. It alone resolved three of that cohort's five closed items.
* **Jianwen Su's page at UCSB** — the Hull/Su artifact-centric corpus. It stops
  in 2009, so it carries the pre-GSM foundations (ICDT/ICSOC 2009, the BPM
  handbook chapter) and not the GSM papers themselves.
* **Ulm's DBIS EPrints** — Reichert's group deposits everything, which is the
  only open route to the PHILharmonicFlows and object-aware-process line.
  Implemented against the EPrints *search* interface rather than a static page,
  since that is what an institutional repository offers.

Two overrides are worth knowing about because they are archives in their own
right and nothing in the resolver ladder reaches either:

* **bitsavers** mirrors the complete *IBM Systems Journal*, which is where
  Nigam & Caswell's founding artifact paper is — IBM's own copy is behind IEEE,
  Unpaywall reports the DOI closed, and the only other free copies are
  bot-walled aggregators.
* **IBM's research object store** serves the 2011 GSM operational-semantics
  technical report. That report, not the BPM/Inf.Syst. papers, is the
  authoritative rule system: the published versions present the abstract
  setting and defer to it for the full PAC rules.

What remains closed after all of that is recorded rather than retried, and the
pattern in it is the finding: the three **GSM meta-model papers themselves**
(WS-FM 2010, DEBS 2011, Inf. Syst. 2013) have no open copy anywhere the
resolvers reach. See ``SOURCES.md`` → *Known-gated sources*.

Output lands in ``Inbox/gap-artifact-centric/`` for ``import-downloads.py`` to
file; the cohort folder is routed by ``COHORT_FOLDERS`` so these do not scatter
across six topic folders on incidental vocabulary the way the Apache papers did.

Usage:
  scripts/.venv/bin/python scripts/gap-artifact-centric.py all --dry-run
  scripts/.venv/bin/python scripts/gap-artifact-centric.py all
  scripts/.venv/bin/python scripts/gap-artifact-centric.py declarative-simulation
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Inbox" / "gap-artifact-centric"
STATE = OUT / "_gap-artifact-centric.json"
REPORT = OUT / "_gap-artifact-centric-report.csv"

# Self-hosting pages whose markup is `<a href="….pdf">Title</a>`, which is the
# one shape that makes a title lookup exact rather than fuzzy.
ANCHOR_PAGES = {
    "hreijers.win.tue.nl": "https://hreijers.win.tue.nl/publications.html",
    "cs.ucsb.edu/~su": "https://sites.cs.ucsb.edu/~su/papers/",
    "vdaalst.com": "https://www.vdaalst.com/publications/publications.html",
    # De Masellis is a co-author on the DEBS 2011 GSM paper and self-hosts it,
    # which makes his page the only reachable copy of a GSM meta-model paper.
    # Its hrefs are relative to `/pages/`, so the page URL must keep that
    # segment for urljoin to land on the file rather than a 404 at the root.
    "demasellis.x10host.com":
        "http://demasellis.x10host.com/pages/publications.php",
}

# EPrints repositories, queried through their own search rather than crawled.
EPRINTS = {"dbis.eprints.uni-ulm.de": "https://dbis.eprints.uni-ulm.de"}

# CEUR volumes this literature is actually in. Enumerated rather than searched:
# CEUR has no cross-volume title index, and a volume page is one cheap fetch
# that yields every paper in it.
CEUR_VOLUMES = [
    "1789",  # BPM 2016 Demo Track — MuDePS
    "2196",  # BPM 2018 Demo Track — MP-Declare log generator
    "2673",  # BPM 2020 Demos
    "2703",  # ICPM 2020 Doctoral Consortium / Tool Demos — RuM
    "1293",  # SIMPDA 2014 — from declarative processes to imperative models
    "1295",  # BPM 2014 Demos — the ACSI Hub
    "3783",  # ICPM 2024 Doctoral Consortium — stochastic object-centric
    "2938",  # ICPM 2021 Demos
]

# (cohort, title, authors, direct-url-or-None, doi-or-None)
Paper = tuple[str, str, list[str], str | None, str | None]


# --------------------------------------------------------------------------
# 1. Foundations — the models the question is about
# --------------------------------------------------------------------------
# The audit's verdict here was the surprise: `artifact-centric` reads *covered*
# (194 mentions, 9 holdings) while `Guard-Stage-Milestone` reads *thin* with
# zero holdings. The library absorbed the artifact-centric idea through the
# verification and process-mining papers that cite it and never acquired the
# meta-model papers themselves.
FOUNDATIONS: list[Paper] = [
    # The founding paper of the whole line, and the hardest single item to get:
    # IBM Systems Journal is on IEEE, Unpaywall reports the DOI closed, and the
    # free copies are on bot-walled aggregators. bitsavers mirrors the complete
    # journal by volume/issue, one PDF per article, named after the first author.
    ("foundations",
     "Business artifacts: An approach to operational specification",
     ["Nigam", "Caswell"],
     "https://bitsavers.trailing-edge.com/pdf/ibm/IBM_Systems_Journal/423/"
     "nigam.pdf", "10.1147/sj.423.0428"),
    ("foundations",
     "Towards Formal Analysis of Artifact-Centric Business Process Models",
     ["Bhattacharya", "Gerede", "Hull", "Liu", "Su"], None,
     "10.1007/978-3-540-75183-0_21"),
    ("foundations",
     "Artifact-Centric Business Process Models: Brief Survey of Research "
     "Results and Challenges", ["Hull"], None, "10.1007/978-3-540-88873-4_17"),
    # The IEEE Data Engineering Bulletin has been free since 1977 and is not in
    # Unpaywall, so the direct path is the only open copy — but the path is not
    # guessable: DEBull names each file after the first author's *given* name,
    # so Cohn & Hull is `david.pdf`, not `hull.pdf` or `cohn.pdf` (both 404).
    # The September 2009 issue is Su's special issue on data-centric business
    # processes, which is why its neighbour below is worth taking too.
    ("foundations",
     "Business Artifacts: A Data-centric Approach to Modeling Business "
     "Operations and Processes", ["Cohn", "Hull"],
     "http://sites.computer.org/debull/A09sept/david.pdf", None),
    ("foundations",
     "Modeling and Verifying Active XML Artifacts",
     ["Abiteboul", "Bourhis", "Galland", "Marinoiu"],
     "http://sites.computer.org/debull/A09sept/serge.pdf", None),
    ("foundations",
     "Introducing the Guard-Stage-Milestone Approach for Specifying Business "
     "Entity Lifecycles",
     ["Hull", "Damaggio", "De Masellis", "Fournier", "Gupta", "Heath",
      "Hobson", "Linehan", "Maradugu", "Nigam", "Sukaviriya", "Vaculin"],
     None, "10.1007/978-3-642-19589-1_1"),
    ("foundations",
     "Business artifacts with guard-stage-milestone lifecycles: managing "
     "artifact interactions with conditions and events",
     ["Hull", "Damaggio", "Fournier", "Gupta", "Heath", "Hobson", "Linehan",
      "Maradugu", "Nigam", "Sukaviriya", "Vaculin"],
     "http://demasellis.x10host.com/pages/contents/publications-pdf/"
     "DEBS-11.pdf", "10.1145/2002259.2002270"),
    ("foundations",
     "On the equivalence of incremental and fixpoint semantics for business "
     "artifacts with Guard-Stage-Milestone lifecycles",
     ["Damaggio", "Hull", "Vaculin"], None, "10.1016/j.is.2012.05.011"),
    # The authoritative statement of the GSM operational semantics is a 2011
    # IBM technical report, not a paper: the BPM/Inf.Syst. versions are the
    # abstract setting and refer to this for the full rule system. IBM's own
    # object store is the only place it is served from.
    ("foundations",
     "A Formal Introduction to Business Artifacts with Guard-Stage-Milestone "
     "Lifecycles",
     ["Damaggio", "Hull", "Vaculin"],
     "https://s3.us.cloud-object-storage.appdomain.cloud/res-files/"
     "145-2011-05-16-almost-v0.8-GSM-operational-semantics.pdf", None),
    ("foundations",
     "Facilitating Workflow Interoperation Using Artifact-Centric Hubs",
     ["Hull", "Narendra", "Nigam"], None, "10.1007/978-3-642-10383-4_1"),
    ("foundations",
     "Declarative business artifact centric modeling of decision and "
     "knowledge intensive business processes",
     ["Vaculin", "Hull", "Heath", "Cochran", "Nigam", "Sukaviriya"], None,
     "10.1109/EDOC.2011.36"),
    ("foundations",
     "On the Duality of Information-Centric and Activity-Centric Models of "
     "Business Processes", ["Kumaran", "Liu", "Wu"], None,
     "10.1007/978-3-540-69534-9_3"),
    # The GSM-to-CMMN lineage in one place: this is the paper that explains why
    # a standards body adopted a declarative artifact lifecycle, and the OMG
    # CMMN spec (already held) never says.
    ("foundations",
     "Data Centric BPM and the Emerging Case Management Standard: A Short Survey",
     ["Marin", "Hull", "Vaculin"], None, "10.1007/978-3-642-36285-9_4"),
    ("foundations",
     "Object-aware Business Processes: Fundamental Requirements and their "
     "Support in Existing Approaches",
     ["Kunzle", "Weber", "Reichert"], None, "10.4018/jismd.2011040102"),
    ("foundations",
     "Verification and Validation of UML Artifact-Centric Business Process Models",
     ["Estanol", "Sancho", "Teniente"], None, "10.1007/978-3-319-19069-3_3"),
    # Reachable only because Su's page is in the resolver ladder; both are the
    # pre-GSM formal treatment that the GSM papers assume and never restate.
    ("foundations",
     "Automatic Construction of Simple Artifact-based Business Processes",
     ["Fritz", "Hull", "Su"], None, "10.1145/1514894.1514917"),
    ("foundations",
     "Artifact-Centric Workflow Dominance",
     ["Calvanese", "De Giacomo", "Hull", "Su"], None,
     "10.1007/978-3-642-10383-4_10"),
    # The BALSA framework's own paper. It is a handbook chapter, so it has no
    # DOI the resolvers can follow, and the audit's `BALSA` probe had to be
    # rewritten to the expansion precisely because the library held nothing
    # under the acronym. Su's page is the only open copy.
    ("foundations",
     "A Data-Centric Design Methodology for Business Processes",
     ["Bhattacharya", "Hull", "Su"],
     "https://www.cs.ucsb.edu/~su/papers/2008/BPM-handbook-chapter.pdf", None),
]


# --------------------------------------------------------------------------
# 1b. Verification of GSM specifically — thin, with zero holdings
# --------------------------------------------------------------------------
# The library holds the *database-theory* half of artifact verification (DCDS,
# hierarchical artifact systems) and nothing on GSM in particular. Lomuscio's
# group is the one that did GSM, and self-hosts it.
VERIFICATION: list[Paper] = [
    ("verification",
     "Verifying GSM-based Business Artifacts",
     ["Belardinelli", "Lomuscio", "Patrizi"],
     "https://www.doc.ic.ac.uk/~alessio/papers/12/ICWS-PG+.pdf", None),
    ("verification",
     "Verification of GSM-based Artifact-centric Systems by Predicate Abstraction",
     ["Gonzalez", "Griesmayer", "Lomuscio"],
     "https://www.doc.ic.ac.uk/~alessio/papers/15/ICSOC15-PG+.pdf", None),
    ("verification",
     "Verification of Agent-Based Artifact Systems",
     ["Belardinelli", "Lomuscio", "Patrizi"],
     "https://arxiv.org/pdf/1301.2678", None),
    # The other half of GSM verification: Montali's group mapped GSM onto DCDS
    # rather than onto interpreted systems, and the two papers disagree about
    # which restrictions buy decidability. Both self-hosted by De Masellis.
    ("verification",
     "Verification of Artifact-Centric Systems: Decidability and Modeling Issues",
     ["Solomakhin", "Montali", "Tessaris", "De Masellis"],
     "http://demasellis.x10host.com/pages/contents/publications-pdf/"
     "ICSOC-13-gsm-dcds.pdf", "10.1007/978-3-642-45005-1_18"),
    ("verification",
     "Semantic enrichment of GSM-based artifact-centric models",
     ["De Masellis", "Lembo", "Montali", "Solomakhin"],
     "http://demasellis.x10host.com/pages/contents/publications-pdf/"
     "JODS-15.pdf", "10.1007/s13740-014-0038-4"),
    ("verification",
     "Foundations of relational artifacts verification",
     ["Bagheri Hariri", "Calvanese", "De Giacomo", "De Masellis", "Felli"],
     "http://demasellis.x10host.com/pages/contents/publications-pdf/"
     "BPM-11.pdf", "10.1007/978-3-642-23059-2_17"),
    ("verification",
     "Verification of conjunctive artifact-centric services",
     ["De Giacomo", "De Masellis", "Rosati"],
     "http://demasellis.x10host.com/pages/contents/publications-pdf/"
     "IJCIS-12.pdf", "10.1142/S0218843012500049"),
]


# --------------------------------------------------------------------------
# 2. Enactment — engines, which is what the community built instead
# --------------------------------------------------------------------------
ENACTMENT: list[Paper] = [
    ("enactment",
     "Barcelona: A Design and Runtime Environment for Declarative "
     "Artifact-Centric BPM",
     ["Heath", "Boaz", "Gupta", "Vaculin", "Sun", "Hull", "Limonad"], None,
     "10.1007/978-3-642-45005-1_65"),
    ("enactment",
     "The ACSI Hub: A Data-centric Environment for Service Interoperation",
     ["Sun", "Xu", "Su", "Hull", "Vaculin", "Heath", "Boaz", "Limonad"],
     "https://ceur-ws.org/Vol-1295/paper16.pdf", None),
    ("enactment",
     "Using the Guard-Stage-Milestone Notation for Monitoring BPMN-based Processes",
     ["Baresi", "Meroni", "Plebani"],
     "https://re.public.polimi.it/retrieve/e0c31c09-cb2d-4599-e053-1705fe0aef77/"
     "paper.pdf", None),
    ("enactment",
     "PHILharmonicFlows: towards a framework for object-aware process management",
     ["Kunzle", "Reichert"], None, "10.1002/smr.524"),
    ("enactment",
     "The Relational Process Structure",
     ["Steinau", "Andrews", "Reichert"], None, "10.1007/978-3-319-91563-0_4"),
    ("enactment",
     "Declarative Event-Based Workflow as Distributed Dynamic Condition "
     "Response Graphs", ["Hildebrandt", "Mukkamala"], None,
     "10.4204/EPTCS.69.5"),
    ("enactment",
     "Nested Dynamic Condition Response Graphs",
     ["Hildebrandt", "Mukkamala", "Slaats"], None,
     "10.1007/978-3-642-29320-7_23"),
    ("enactment",
     "Replication, refinement & reachability: complexity in dynamic "
     "condition-response graphs",
     ["Debois", "Hildebrandt", "Slaats"], None, "10.1007/s00236-017-0303-8"),
    ("enactment",
     "Contracts for cross-organizational workflows as timed Dynamic Condition "
     "Response Graphs",
     ["Hildebrandt", "Mukkamala", "Slaats", "Zanitti"], None,
     "10.1016/j.jlap.2012.05.007"),
    ("enactment",
     "Exformatics Declarative Case Management Workflows as DCR Graphs",
     ["Slaats", "Mukkamala", "Hildebrandt", "Marquard"], None,
     "10.1007/978-3-642-40176-3_28"),
    ("enactment",
     "The DCR Workbench: Declarative Choreographies for Collaborative Processes",
     ["Debois", "Hildebrandt"], None, None),
]


# --------------------------------------------------------------------------
# 3. Simulating a declarative model — log generation is the operative form
# --------------------------------------------------------------------------
# The crux. `simulating declarative` and `declarative simulation` both returned
# zero documents in the audit, which is not a vocabulary artefact: the papers
# exist and say exactly those words in their titles.
DECLARATIVE_SIMULATION: list[Paper] = [
    ("declarative-simulation",
     "Generating Event Logs Through the Simulation of Declare Models",
     ["Di Ciccio", "Bernardi", "Cimitile", "Maggi"],
     "https://www.diciccio.net/claudio/preprints/"
     "DiCiccio-etal-EOMAS2015-GeneratingEventLogs.pdf",
     "10.1007/978-3-319-24626-0_2"),
    ("declarative-simulation",
     "Simulation of Multi-Perspective Declarative Process Models",
     ["Ackermann", "Schonig", "Jablonski"], None,
     "10.1007/978-3-319-58457-7_5"),
    ("declarative-simulation",
     "MuDePS: Multi-perspective Declarative Process Simulation",
     ["Ackermann", "Schonig", "Jablonski"],
     "https://ceur-ws.org/Vol-1789/bpm-demo-2016-paper3.pdf", None),
    ("declarative-simulation",
     "A Tool for Generating Event Logs from Multi-Perspective Declare Models",
     ["Skydanienko", "Di Francescomarino", "Ghidini", "Maggi"], None, None),
    ("declarative-simulation",
     "Language-independent look-ahead for checking multi-perspective "
     "declarative process models",
     ["Ackermann", "Kappel", "Schonig", "Jablonski"],
     "https://d-nb.info/1226836852/34", "10.1007/s10270-021-00937-3"),
    ("declarative-simulation",
     "Data-Aware Declarative Process Mining with SAT",
     ["Chiariello", "Maggi", "Patrizi"],
     "http://www.diag.uniroma1.it/~patrizi/docs/papers/MMPS_TIST2023.pdf",
     "10.1145/3600106"),
    ("declarative-simulation",
     "ASP-Based Declarative Process Mining",
     ["Chiariello", "Maggi", "Patrizi"], None, "10.1609/aaai.v36i5.20472"),
    ("declarative-simulation",
     "Rule Mining in Action: The RuM Toolkit",
     ["Alman", "Di Ciccio", "Maggi", "Mendling", "van der Aa"],
     "https://ceur-ws.org/Vol-2703/paperTD9.pdf", None),
    ("declarative-simulation",
     "RuM: Declarative Process Mining, Distilled",
     ["Alman", "Di Ciccio", "Maggi", "Mendling", "van der Aa"], None,
     "10.1007/978-3-030-58666-9_2"),
    ("declarative-simulation",
     "Monitoring Business Constraints with Linear Temporal Logic: An Approach "
     "Based on Colored Automata",
     ["Maggi", "Montali", "Westergaard", "van der Aalst"], None,
     "10.1007/978-3-642-23059-2_13"),
    # IJCAI serves its proceedings free but by paper number, not by title, and
    # the number is not derivable from the citation — 141 is a different paper
    # entirely. The 2013 index page is the only way to get from one to the other.
    ("declarative-simulation",
     "Linear Temporal Logic and Linear Dynamic Logic on Finite Traces",
     ["De Giacomo", "Vardi"],
     "https://www.ijcai.org/Proceedings/13/Papers/132.pdf", None),
    ("declarative-simulation",
     "Looking into the Future: Using Timed Automata to Provide A Priori Advice "
     "about Timed Declarative Process Models",
     ["Westergaard", "Maggi"], None, "10.1007/978-3-642-33606-5_16"),
    ("declarative-simulation",
     "From Declarative Processes to Imperative Models",
     ["Prescher", "Di Ciccio", "Mendling"],
     "https://ceur-ws.org/Vol-1293/paper11.pdf", None),
    ("declarative-simulation",
     "The Effect of Noise on Mined Declarative Constraints",
     ["Di Ciccio", "Mecella", "Mendling"], None,
     "10.1007/978-3-662-46436-6_1"),
    ("declarative-simulation",
     "Probabilistic Conformance Checking Based on Declarative Process Models",
     ["Maggi", "Montali", "Penaloza"], None, "10.1007/978-3-030-58135-0_9"),
    ("declarative-simulation",
     "Probabilistic Trace Alignment",
     ["Bergami", "Maggi", "Montali", "Penaloza"], None, None),
    ("declarative-simulation",
     "A Declarative Approach for Flexible Business Processes Management",
     ["Pesic", "van der Aalst"], None, "10.1007/11837862_18"),
    ("declarative-simulation",
     "DECLARE: Full Support for Loosely-Structured Processes",
     ["Pesic", "Schonenberg", "van der Aalst"], None, "10.1109/EDOC.2007.14"),
    ("declarative-simulation",
     "Declarative workflows: Balancing between flexibility and support",
     ["van der Aalst", "Pesic", "Schonenberg"], None,
     "10.1007/s00450-009-0057-9"),
]


# --------------------------------------------------------------------------
# 4. Paradigm comparison — the theme the audit returned MISSING
# --------------------------------------------------------------------------
PARADIGM_COMPARISON: list[Paper] = [
    ("paradigm-comparison",
     "Declarative versus Imperative Process Modeling Languages: The Issue of "
     "Understandability",
     ["Fahland", "Lubke", "Mendling", "Reijers", "Weber", "Weidlich", "Zugal"],
     None, "10.1007/978-3-642-01862-6_29"),
    ("paradigm-comparison",
     "Declarative versus Imperative Process Modeling Languages: The Issue of "
     "Maintainability",
     ["Fahland", "Mendling", "Reijers", "Weber", "Weidlich", "Zugal"], None,
     "10.1007/978-3-642-12186-9_45"),
    ("paradigm-comparison",
     "Imperative versus Declarative Process Modeling Languages: An Empirical "
     "Investigation",
     ["Pichler", "Weber", "Zugal", "Pinggera", "Mendling", "Reijers"],
     "https://hreijers.win.tue.nl/H.A.%20Reijers%20Bestanden/pich_er_bpm_2011.pdf",
     None),
    # The BPM-workshop version above and this ER-POIS 2010 paper are the two
    # halves of the same experiment; CEUR has the earlier one open.
    ("paradigm-comparison",
     "The Impact of Sequential and Circumstantial Changes on Process Models",
     ["Weber", "Pinggera", "Zugal", "Reijers"],
     "https://ceur-ws.org/Vol-603/ER-POIS10_Paper5.pdf", None),
    # Stahl's Pure record at ITU serves the accepted version, but the Pure
    # *search* endpoint is bot-walled, so only the direct `/ws/files/` path
    # works and the id has to be pinned rather than looked up.
    ("paradigm-comparison",
     "Declarative Modeling - An Academic Dream or the Future for BPM?",
     ["Reijers", "Slaats", "Stahl"],
     "https://pure.itu.dk/ws/files/78918062/declare_bpm_review.pdf",
     "10.1007/978-3-642-40176-3_26"),
    ("paradigm-comparison",
     "Understanding Declare models: strategies, pitfalls, empirical results",
     ["Haisjackl", "Barba", "Zugal", "Soffer", "Hadar", "Reichert",
      "Pinggera", "Weber"], None, "10.1007/s10270-014-0435-z"),
    ("paradigm-comparison",
     "Investigating Differences between Graphical and Textual Declarative "
     "Process Models", ["Haisjackl", "Zugal"], None, None),
    ("paradigm-comparison",
     "Investigating expressiveness and understandability of hierarchy in "
     "declarative business process models",
     ["Zugal", "Soffer", "Haisjackl", "Pinggera", "Reichert", "Weber"], None,
     "10.1007/s10270-013-0356-2"),
    ("paradigm-comparison",
     "The Impact of Testcases on the Maintainability of Declarative Process "
     "Models", ["Zugal", "Pinggera", "Weber"], None,
     "10.1007/978-3-642-21759-3_11"),
    # The one paper in this theme that measures *execution* rather than reading:
    # practitioners were given a Declare model and a procedural one and set to
    # work, which is as close as the comparison literature comes to asking what
    # a declarative model is good for once it is running.
    ("paradigm-comparison",
     "The Declarative Approach to Business Process Execution: An Empirical Test",
     ["Mulyar", "Pesic", "van der Aalst", "Peleg"],
     "https://hreijers.win.tue.nl/H.A.%20Reijers%20Bestanden/55650470.pdf",
     None),
    ("paradigm-comparison",
     "Process Flexibility: A Survey of Contemporary Approaches",
     ["Schonenberg", "Mans", "Russell", "Mulyar", "van der Aalst"], None,
     "10.1007/978-3-540-68644-6_2"),
    # The hybrid line is the closest anyone comes to comparing the paradigms on
    # something other than comprehension: an intertwined state space is a
    # statement about analysability, which is what a simulator needs.
    ("paradigm-comparison",
     "Mixing Paradigms for More Comprehensible Models",
     ["Westergaard", "Slaats"], None, "10.1007/978-3-642-40176-3_3"),
    ("paradigm-comparison",
     "Mixed-Paradigm Process Modeling with Intertwined State Spaces",
     ["De Smedt", "De Weerdt", "Vanthienen", "Poels"], None,
     "10.1007/s12599-015-0416-y"),
    ("paradigm-comparison",
     "Discovering hidden dependencies in constraint-based declarative process "
     "models for improving understandability",
     ["De Smedt", "De Weerdt", "Serral", "Vanthienen"], None,
     "10.1016/j.is.2018.01.001"),
    ("paradigm-comparison",
     "On the declarative paradigm in hybrid business process representations: "
     "A conceptual framework and a systematic literature study",
     ["Andaloussi", "Burattin", "Slaats", "Kindler", "Weber"], None,
     "10.1016/j.is.2020.101505"),
    ("paradigm-comparison",
     "Declarative and Hybrid Process Discovery: Recent Advances and Open "
     "Challenges", ["Slaats"], None, "10.1007/s13740-020-00112-9"),
]


# --------------------------------------------------------------------------
# 5. Object-centric / data-aware BPS — where the quantitative question went
# --------------------------------------------------------------------------
OBJECT_CENTRIC_BPS: list[Paper] = [
    ("object-centric-bps",
     "Discovering Object-Centric Process Simulation Models",
     ["Adams", "van der Aalst"],
     "https://vdaalst.com/publications/p1420.pdf",
     "10.1109/ICPM60904.2023.10271944"),
    ("object-centric-bps",
     "Discovery and Simulation of Data-Aware Business Processes",
     ["Lopez-Pintado", "Dumas"], "https://arxiv.org/pdf/2408.13666", None),
    ("object-centric-bps",
     "Stochastic Object-Centric Process Mining: Analysing Object Interaction "
     "Patterns", ["Adams"],
     "https://ceur-ws.org/Vol-3783/paper_199.pdf", None),
    ("object-centric-bps",
     "Discovering Object-centric Petri Nets",
     ["van der Aalst", "Berti"], None, "10.3233/FI-2020-1946"),
    ("object-centric-bps",
     "Object-centric process predictive analytics",
     ["Galanti", "de Leoni", "Navarin", "Marazzi"], None,
     "10.1016/j.eswa.2023.119908"),
    ("object-centric-bps",
     "Discovering and Exploring State-based Models for Multi-perspective "
     "Processes", ["van Eck", "Sidorova", "van der Aalst"], None,
     "10.1007/978-3-319-45348-4_9"),
    ("object-centric-bps",
     "Multi-Instance Mining: Discovering Synchronisation in Artifact-Centric "
     "Processes", ["Lu", "Nagelkerke", "van de Wetering", "van der Aalst"],
     None, None),
    ("object-centric-bps",
     "Constructing Digital Twins for Accurate and Reliable What-If Business "
     "Process Analysis", ["Dumas"], None, None),
    ("object-centric-bps",
     "Enhancing Business Process Simulation Models with Extraneous Activity "
     "Delays", ["Chapela-Campa", "Dumas"], None,
     "10.1016/j.is.2023.102229"),
]


ALL_COHORTS = {
    "foundations": FOUNDATIONS,
    "verification": VERIFICATION,
    "enactment": ENACTMENT,
    "declarative-simulation": DECLARATIVE_SIMULATION,
    "paradigm-comparison": PARADIGM_COMPARISON,
    "object-centric-bps": OBJECT_CENTRIC_BPS,
}


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:  # noqa: BLE001
            pass
    return {"done": {}}


def save_state(state: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Title-indexed archives
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>',
                      re.I | re.S)


def anchor_pdf_index(sess, page_url: str, label: str) -> list[dict]:
    """Title -> PDF for a self-hosted publication list.

    Three of the pages this round needs share one shape — the anchor text *is*
    the title and its href is the file — so they share one parser rather than
    three. What differs is only tidiness: Su's page writes its hrefs with a
    leading tab (``href="\t./2009/ICDT2009.pdf"``), which resolves to a 404 if
    passed to ``urljoin`` as-is, so the href is stripped before joining and the
    anchor text before comparing.
    """
    try:
        html = sess.get(page_url, timeout=90).text
    except Exception as exc:  # noqa: BLE001
        print(f"  [{label}] page unreachable ({type(exc).__name__}); skipping")
        return []
    import requests
    out: list[dict] = []
    for href, anchor in _LINK_RE.findall(html):
        title = pf.clean(anchor).strip(" .")
        if len(title) < 12:
            continue
        out.append({"title": title,
                    "url": requests.compat.urljoin(page_url, href.strip())})
    print(f"  [{label}] {len(out)} linked PDFs")
    return out


def eprints_search(sess, base: str, title: str, label: str) -> str | None:
    """Look one title up in an EPrints repository and return its PDF.

    Queried rather than indexed, because an institutional repository holds tens
    of thousands of records and offers a search endpoint precisely so nobody has
    to crawl it. EPrints' result rows are regular in the two ways needed: each
    ``<tr class="ep_search_result">`` carries the record's title inside
    ``<em>`` within the link to its abstract page, and the row's own document
    link is the PDF. Parsing per row is what keeps a title from being paired
    with the neighbouring record's file.
    """
    import requests
    url = f"{base}/cgi/search?q={requests.utils.quote(title)}"
    try:
        html = sess.get(url, timeout=90).text
    except Exception as exc:  # noqa: BLE001
        print(f"  [{label}] search unreachable ({type(exc).__name__})")
        return None
    rows = re.split(r'<tr\s+class=["\']ep_search_result["\']', html)[1:]
    entries: list[dict] = []
    for row in rows:
        tm = re.search(r'/id/eprint/\d+/["\'][^>]*>\s*<em>(.*?)</em>', row, re.S)
        um = re.search(r'href=["\']([^"\']+\.pdf)["\']', row, re.I)
        if not tm or not um:
            continue
        entries.append({"title": pf.clean(tm.group(1)).strip(" ."),
                        "url": um.group(1)})
    return index_match(entries, title)


def ceur_index(sess, volumes: list[str]) -> list[dict]:
    """Title -> PDF across the enumerated CEUR-WS volumes.

    CEUR volume pages are hand-rolled per editor, so the one structural
    invariant is used instead of a layout: every paper is a link to a ``.pdf``
    in the same directory, and the **title is the nearest preceding
    ``<span class="CEURTITLE">``** where the editors used the recommended
    markup, falling back to the anchor's own text where they did not. That
    fallback matters — several older volumes label the link merely "PDF", in
    which case the anchor text is useless and the surrounding list item holds
    the title, so a link with no usable title is dropped rather than guessed.
    """
    import requests
    out: list[dict] = []
    title_re = re.compile(
        r'<span\s+class=["\']?CEURTITLE["\']?[^>]*>(.*?)</span>', re.I | re.S)
    for vol in volumes:
        url = f"https://ceur-ws.org/Vol-{vol}/"
        try:
            page = sess.get(url, timeout=60).text
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r'<a\s[^>]*href=["\']([^"\':]+\.pdf)["\'][^>]*>(.*?)</a>',
                             page, re.I | re.S):
            anchor = pf.clean(m.group(2)).strip(" .")
            titles = [pf.clean(t.group(1)).strip(" .")
                      for t in title_re.finditer(page, 0, m.start())]
            title = titles[-1] if titles else anchor
            if len(title) < 12 or title.lower() in {"pdf", "full paper", "paper"}:
                continue
            out.append({"title": title,
                        "url": requests.compat.urljoin(url, m.group(1))})
    print(f"  [ceur] {len(out)} papers indexed from {len(volumes)} volumes")
    return out


def content_tokens(title: str) -> set[str]:
    """The words of a title long enough to distinguish it from another title."""
    return {w for w in re.findall(r"[a-z]+", pf.norm(title)) if len(w) >= 6}


def index_match(entries: list[dict], title: str, cutoff: float = 0.90) -> str | None:
    """Best PDF in a title-indexed archive, by fuzzy title agreement.

    Same shape as the resolver in ``gap-simulation.py`` and for the same
    reason: a cited title and a page's rendering of it differ in case,
    punctuation and subtitle. Containment is accepted in either direction only
    when the two titles are within a quarter of each other in length, so a
    short title cannot match an unrelated longer one that embeds it.

    **A character ratio alone is not enough, and this round proved it.** Fahland
    et al. published *Declarative versus Imperative Process Modeling Languages:
    The Issue of Understandability* and, a year later, *… The Issue of
    Maintainability*. The two titles share a 47-character prefix, so they sit at
    ratio 0.91 — comfortably over any cutoff loose enough to absorb ordinary
    punctuation drift — and Reijers' page, which hosts only the first, answered
    for both. Nothing downstream could catch it: the file downloaded, the name
    came from the *requested* title, and the two were byte-identical only
    because both were fetched, so the importer's duplicate check was the sole
    reason it surfaced at all. A pure-ratio match therefore has to additionally
    agree on every word of six characters or more; the exact and containment
    paths are exempt, because a page that truncates a subtitle legitimately
    drops words the citation has.
    """
    want = pf.norm(title)
    if len(want) < 12:
        return None
    want_tokens = content_tokens(title)
    best, best_score = None, 0.0
    for e in entries:
        hay = pf.norm(e["title"])
        if hay == want:
            return e["url"]
        ratio = difflib.SequenceMatcher(None, want, hay).ratio()
        contained = (want in hay or hay in want) and \
            min(len(want), len(hay)) / max(len(want), len(hay)) > 0.75
        if contained:
            ratio = max(ratio, 0.95)
        elif want_tokens - content_tokens(e["title"]):
            continue
        if ratio >= cutoff and ratio > best_score:
            best, best_score = e["url"], ratio
    return best


class Archives:
    """The title-indexed archives, each built lazily on first miss.

    Laziness is not premature here: CEUR costs eight page fetches and the three
    author pages one each, and none of it is paid for unless a title actually
    falls through the cheap resolvers.
    """

    def __init__(self, sess):
        self.sess = sess
        self._pages: dict[str, list[dict]] = {}
        self._ceur: list[dict] | None = None

    def page(self, label: str) -> list[dict]:
        if label not in self._pages:
            self._pages[label] = anchor_pdf_index(
                self.sess, ANCHOR_PAGES[label], label)
        return self._pages[label]

    @property
    def ceur(self) -> list[dict]:
        if self._ceur is None:
            self._ceur = ceur_index(self.sess, CEUR_VOLUMES)
        return self._ceur


def candidates(sess, arc: Archives, title: str, authors: list[str],
               url: str | None, doi: str | None) -> list[tuple[str, str]]:
    """Every open location for one work, best first, as ``(url, how)``.

    Returning a *list* rather than the first hit is the one change that mattered
    in this round. The sibling harvesters stop at the first resolver that
    answers, so a work is reported ``failed`` when that answer happens to be
    unfetchable even though a later archive holds it — and here that was not
    hypothetical: OpenAlex and Unpaywall confidently returned a `dl.acm.org`
    403 and two publisher landing pages for three Hull/Su papers that were
    sitting as plain PDFs on Su's own page, which the ladder never reached.
    "Resolvable" and "downloadable" are different properties, and the caller is
    the only place that knows which one it got.

    Ordering still encodes preference — an explicit override first, then the
    cheap metadata backends, then the self-hosting archives — but every source
    is now consulted before anything is declared missing.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(u: str | None, how: str) -> None:
        if u and u not in seen:
            seen.add(u)
            out.append((u, how))

    add(url, "override")
    for fn, how in (
        (lambda: pf.arxiv_pdf(title, authors), "arxiv"),
        (lambda: pf.openalex_pdf(title, authors, email=pf.git_email()), "openalex"),
    ):
        try:
            add(fn(), how)
        except Exception:  # noqa: BLE001
            pass
    if doi:
        try:
            for loc in pf.unpaywall_locations(doi, pf.git_email()):
                add(loc, "unpaywall")
        except Exception:  # noqa: BLE001
            pass
    try:
        add(pf.semanticscholar_pdf(title, authors), "semanticscholar")
    except Exception:  # noqa: BLE001
        pass
    add(index_match(arc.ceur, title), "ceur-ws.org")
    for label in ANCHOR_PAGES:
        add(index_match(arc.page(label), title), label)
    for label, base in EPRINTS.items():
        add(eprints_search(sess, base, title, label), label)
    try:
        hit = pf.dblp_best(title, authors)
    except Exception:  # noqa: BLE001
        hit = None
    if hit:
        for ee in hit.get("ee") or []:
            if ee.lower().endswith(".pdf") and not pf.is_bot_walled(ee):
                add(ee, "dblp-ee")
        if hit.get("doi") and not doi:
            try:
                for loc in pf.unpaywall_locations(hit["doi"], pf.git_email()):
                    add(loc, "unpaywall-via-dblp")
            except Exception:  # noqa: BLE001
                pass
    return out


def run(what: str, dry_run: bool, skip_held: bool) -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    arc = Archives(sess)

    if what == "all":
        papers = [p for cohort in ALL_COHORTS.values() for p in cohort]
    else:
        papers = list(ALL_COHORTS[what])

    dedup = pf.IndexDedup() if skip_held else None
    state = load_state()
    rows: list[dict] = []

    for cohort, title, authors, url, doi in papers:
        key = pf.norm(title)
        prev = state["done"].get(key)
        if prev and prev.get("status") == "downloaded" and \
                Path(ROOT / prev["file"]).exists():
            print(f"[{'cached':>22}] {title[:74]}")
            rows.append(prev)
            continue
        if dedup and dedup.contains(title):
            row = {"cohort": cohort, "title": title, "how": "held",
                   "url": "", "status": "already-in-library", "file": ""}
            print(f"[{'already in library':>22}] {title[:74]}")
            rows.append(row)
            state["done"][key] = row
            continue

        cands = candidates(sess, arc, title, authors, url, doi)
        found, how, status, dest, detail = "", "unresolved", "no-open-copy", "", ""
        if cands and dry_run:
            found, how = cands[0]
            status = f"would-download ({len(cands)} candidates)"
        elif cands:
            path = OUT / f"{pf.safe_stem(authors, title)}.pdf"
            for cand, cand_how in cands:
                ok, detail = pf.download_pdf(sess, cand, path)
                found, how = cand, cand_how
                if ok:
                    status, dest = "downloaded", str(path.relative_to(ROOT))
                    break
            else:
                # Every location refused; report the last reason, and how many
                # were tried, so a single 403 is not mistaken for absence.
                status = f"failed after {len(cands)}: {detail}"
        print(f"[{status:>22}] ({how}) {title[:70]}")
        row = {"cohort": cohort, "title": title, "how": how,
               "url": found, "status": status, "file": dest}
        rows.append(row)
        state["done"][key] = row
        save_state(state)

    return rows


def write_report(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["cohort", "title", "how", "url",
                                           "status", "file"])
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    c = Counter(r["status"].split(":")[0] for r in rows)
    print(f"\n{len(rows)} works: " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    by_cohort = Counter(r["cohort"] for r in rows
                        if r["status"] in ("downloaded", "would-download"))
    if by_cohort:
        print("obtained per cohort: " +
              ", ".join(f"{k}={v}" for k, v in by_cohort.most_common()))
    print(f"report: {REPORT.relative_to(ROOT)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", nargs="?", default="all",
                   choices=["all", *ALL_COHORTS])
    p.add_argument("--dry-run", action="store_true",
                   help="resolve only; do not download")
    p.add_argument("--no-dedup", action="store_true",
                   help="fetch even works the index already holds")
    args = p.parse_args(argv)

    rows = run(args.what, args.dry_run, skip_held=not args.no_dedup)
    write_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
