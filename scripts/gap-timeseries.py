#!/usr/bin/env python3
"""Gap-closing harvest: **time-series data mining**, and its intersection with
process mining.

The round starts from two Google Scholar profiles and ends at a gap the audit
(``gap-audit.py --topic timeseries-process-mining``) states in one line: the
collection holds *both banks of the river and no bridge*. The systems half is
strong (713 documents mention data-series similarity search, 111 the storage
engines) and the process-mining half is strong (237 on concept drift, 161 on
predictive monitoring), while ``event log to time series`` matches **one**
document, ``synthetic control`` **one**, and ``latent source model`` **one**.
That asymmetry is what this harvest is aimed at, not the two authors' output as
such.

Four passes, deliberately different in kind:

1. ``keogh`` — **Eamonn Keogh's self-hosted archive** (UC Riverside;
   `scholar.google.com/citations?user=slVcOQIAAAAJ`). His publications page and
   the Matrix Profile page carry ~120 PDFs of the founding literature on
   time-series representation (SAX, PAA/APCA), indexing (LB_Keogh, the UCR
   Suite), motif and discord discovery (the Matrix Profile series), shapelets,
   and the benchmark critiques. No filter is applied: his image-mining papers
   look off-topic and are not — petroglyphs and historical manuscripts are
   *converted to time series* and mined with the same primitives, which is the
   clearest demonstration in the corpus that the representation is the point.

2. ``shah`` — **Devavrat Shah's** time-series subset (MIT;
   `scholar.google.com/citations?user=3qPiYJoAAAAJ`). Here a filter *is*
   required and the reason is structural: his corpus is majority networking and
   information theory (OpenFlow at 13,875 citations, gossip algorithms, network
   coding), and the ~60 works relevant here are a minority thread running from
   latent-source models through matrix estimation to synthetic control and
   tspDB. Enumeration comes from Scholar rather than from his page, because
   **his publications page stops at 2018** — every year heading from 1999 to
   2018 and nothing after — so the whole line this round wants (mSSA 2020,
   tspDB 2021, synthetic interventions, causal matrix completion) is invisible
   there. The page is still consulted first for what it does hold.

3. ``gaps`` — the curated cohort closing what the audit found ``mention-only``
   or ``thin``: the benchmark critique and the evaluation-protocol argument, the
   anomaly-detection evaluations, singular spectrum analysis, hierarchical
   forecast reconciliation, the synthetic-control and causal-panel literature,
   the data-series index line, and — the one that matters most for this
   repository — the **performance spectrum**, which is the existing
   process-mining answer to "turn an event log into a signal".

4. ``scholar`` — a **coverage cross-check** rather than a fetch. It enumerates
   both profiles and reports, per work, whether the corpus holds it. A profile
   is the only complete and current statement of an author's output; a
   self-hosted page is a partial archive of it, and the difference between the
   two is the honest measure of what a round like this leaves behind.

Why both authors and not one: they answer the same question from opposite ends,
and the internal requirement needs both. The Supply Chain / Ontology / AI summit
asks for time series held as a first-class object type, every node and link
attribute time-versioned, and one query interface over ``Inventory(now)``,
``Inventory(yesterday)`` and ``Inventory(future)`` "leveraging different models
for projection". Keogh's line answers *what happened and what is unlike
anything else* over an observed series; Shah's answers *what is missing, what
comes next and what would have happened otherwise* — and states it as one
problem (matrix estimation over a page matrix), with tspDB arguing that it
belongs inside the database rather than in a pipeline beside it. That is the
same unification the summit's three-tense query interface asks for.

Resolution goes through ``paperfetch`` (own-site → arXiv → OpenAlex →
Unpaywall-by-DOI → Semantic Scholar) with explicit overrides where a work is
open in exactly one place. Output lands in ``Inbox/gap-timeseries/`` for
``import-downloads.py`` to file (via ``COHORT_FOLDERS``) and the indexer to
pick up.

Usage:
  scripts/.venv/bin/python scripts/gap-timeseries.py keogh
  scripts/.venv/bin/python scripts/gap-timeseries.py shah
  scripts/.venv/bin/python scripts/gap-timeseries.py gaps
  scripts/.venv/bin/python scripts/gap-timeseries.py scholar    # report only
  scripts/.venv/bin/python scripts/gap-timeseries.py all
  scripts/.venv/bin/python scripts/gap-timeseries.py all --dry-run
"""

from __future__ import annotations

import argparse
import csv
import difflib
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Inbox" / "gap-timeseries"
STATE = OUT / "_gap-timeseries.json"
REPORT = OUT / "_gap-timeseries-report.csv"
SCHOLAR_REPORT = ROOT / "imports" / "gap-timeseries-scholar-coverage.csv"
SCHOLAR_CACHE = ROOT / "imports"

# Keogh self-hosts everything, across a handful of hand-maintained pages. The
# publications page is the bibliography; the others are topic pages that carry
# papers the bibliography omits (the later Matrix Profile numbers in
# particular, which is where the anomaly-detection work lives).
KEOGH_PAGES = [
    "https://www.cs.ucr.edu/~eamonn/selected_publications.htm",
    "https://www.cs.ucr.edu/~eamonn/MatrixProfile.html",
    "https://www.cs.ucr.edu/~eamonn/SAX.htm",
    "https://www.cs.ucr.edu/~eamonn/UCRsuite.html",
    "https://www.cs.ucr.edu/~eamonn/LB_Keogh.htm",
    "https://www.cs.ucr.edu/~eamonn/TimeSeriesMotifs/",
]
SHAH_PUBS = "https://devavrat.mit.edu/publication/"
SCHOLAR = "https://scholar.google.com/citations"
KEOGH_SCHOLAR = "slVcOQIAAAAJ"
SHAH_SCHOLAR = "3qPiYJoAAAAJ"

# (topic, title, authors, direct-url-or-None, doi-or-None)
Paper = tuple[str, str, list[str], str | None, str | None]


# ---------------------------------------------------------------------------
# 3. The curated gap cohort
# ---------------------------------------------------------------------------
# Grouped by the audit verdict each entry answers, so a later re-audit can be
# read against this list. Where a DOI is given the work is closed at the
# publisher and the DOI is only a route into Unpaywall; where a URL is given it
# is because the resolvers demonstrably do not find the open copy.
GAP_PAPERS: list[Paper] = [
    # --- 3a. Representation and the empirical comparisons (mention-only) ------
    # The pre-Keogh foundations. Faloutsos/Agrawal are the papers every
    # representation paper since 1994 measures itself against, and neither is
    # on Keogh's page because they are not his.
    ("representation", "Efficient Similarity Search In Sequence Databases",
     ["Agrawal", "Faloutsos", "Swami"], None, "10.1007/3-540-57301-1_5"),
    ("representation", "Fast Subsequence Matching in Time-Series Databases",
     ["Faloutsos", "Ranganathan", "Manolopoulos"], None, "10.1145/191839.191925"),
    ("representation", "Efficient Time Series Matching by Wavelets",
     ["Chan", "Fu"], None, "10.1109/ICDE.1999.754915"),
    ("representation", "Using Dynamic Time Warping to Find Patterns in Time Series",
     ["Berndt", "Clifford"], None, None),
    ("representation", "The great time series classification bake off: a review "
     "and experimental evaluation of recent algorithmic advances",
     ["Bagnall", "Lines", "Bostrom", "Large", "Keogh"], None,
     "10.1007/s10618-016-0483-9"),
    ("representation", "Bake off redux: a review and experimental evaluation of "
     "recent time series classification algorithms",
     ["Middlehurst", "Schafer", "Bagnall"], None, None),
    ("representation", "The UCR Time Series Archive",
     ["Dau", "Bagnall", "Kamgar", "Yeh", "Zhu", "Gharghabi", "Ratanamahatana",
      "Keogh"], None, None),
    ("representation", "The UEA multivariate time series classification archive, 2018",
     ["Bagnall", "Dau", "Lines", "Flynn", "Large", "Bostrom", "Southam",
      "Keogh"], None, None),
    ("representation", "Time Series Management Systems: A Survey",
     ["Jensen", "Pedersen", "Thomsen"], None, None),

    # --- 3b. The benchmark critique and the evaluation protocol ---------------
    # The audit's sharpest finding in this theme: 17 documents mention the
    # critique, none is substantively about it. A platform team that intends to
    # ship anomaly detection needs the argument, not the citation.
    ("anomaly-critique", "Current Time Series Anomaly Detection Benchmarks are "
     "Flawed and are Creating the Illusion of Progress",
     ["Wu", "Keogh"], None, None),
    ("anomaly-critique", "Towards a Rigorous Evaluation of Time-series Anomaly "
     "Detection", ["Kim", "Choi", "Choi", "Choi", "Yoon"], None, None),
    ("anomaly-critique", "Precision and Recall for Time Series",
     ["Tatbul", "Lee", "Zdonik", "Alam", "Gottschlich"], None, None),
    ("anomaly-critique", "Volume Under the Surface: A New Accuracy Evaluation "
     "Measure for Time-Series Anomaly Detection",
     ["Paparrizos", "Boniol", "Palpanas", "Tsay", "Elmore", "Franklin"], None,
     "10.14778/3551793.3551830"),
    ("anomaly-critique", "TSB-UAD: An End-to-End Benchmark Suite for Univariate "
     "Time-Series Anomaly Detection",
     ["Paparrizos", "Kang", "Boniol", "Tsay", "Palpanas", "Franklin"], None,
     "10.14778/3529337.3529354"),
    ("anomaly-critique", "Anomaly Detection in Time Series: A Comprehensive "
     "Evaluation", ["Schmidl", "Wenig", "Papenbrock"], None,
     "10.14778/3538598.3538602"),
    ("anomaly-critique", "Revisiting Time Series Outlier Detection: Definitions "
     "and Benchmarks", ["Lai", "Zha", "Xu", "Zhao", "Wang", "Hu"], None, None),

    # --- 3c. Anomaly detection methods (thin) --------------------------------
    ("anomaly", "A review on outlier/anomaly detection in time series data",
     ["Blazquez-Garcia", "Conde", "Mori", "Lozano"], None, None),
    ("anomaly", "Series2Graph: Graph-based Subsequence Anomaly Detection for "
     "Time Series", ["Boniol", "Palpanas"], None, "10.14778/3407790.3407792"),
    ("anomaly", "SAND: Streaming Subsequence Anomaly Detection",
     ["Boniol", "Paparrizos", "Palpanas", "Franklin"], None,
     "10.14778/3477132.3483537"),
    ("anomaly", "Deep Learning for Anomaly Detection: A Review",
     ["Pang", "Shen", "Cao", "Hengel"], None, None),
    ("anomaly", "USAD: UnSupervised Anomaly Detection on Multivariate Time Series",
     ["Audibert", "Michiardi", "Guyard", "Marti", "Zuluaga"], None,
     "10.1145/3394486.3403392"),

    # --- 3d. Change point detection (covered but unheld) ---------------------
    ("change-point", "Selective review of offline change point detection methods",
     ["Truong", "Oudre", "Vayatis"], None, None),
    ("change-point", "A Survey of Methods for Time Series Change Point Detection",
     ["Aminikhanghahi", "Cook"], None, "10.1007/s10115-016-0987-z"),
    ("change-point", "Optimal detection of changepoints with a linear "
     "computational cost", ["Killick", "Fearnhead", "Eckley"], None, None),

    # --- 3e. Matrix estimation, SSA and in-database prediction ---------------
    # Shah's post-2018 line, which his own page does not list. `mSSA` and
    # `tspDB` are the two the audit reported as mention-only at 3 and 37
    # mentions with nothing held.
    ("matrix-estimation", "On Multivariate Singular Spectrum Analysis and its "
     "Variants", ["Agarwal", "Alomar", "Shah"], None, None),
    ("matrix-estimation", "tspDB: Time Series Predict DB",
     ["Agarwal", "Alomar", "Shah"], None, None),
    ("matrix-estimation", "On Robustness of Principal Component Regression",
     ["Agarwal", "Shah", "Shen", "Song"], None, None),
    ("matrix-estimation", "Model Agnostic Time Series Analysis via Matrix Estimation",
     ["Agarwal", "Amjad", "Shah", "Shen"], None, None),
    ("matrix-estimation", "Causal Matrix Completion",
     ["Agarwal", "Dahleh", "Shah", "Shen"], None, None),
    ("matrix-estimation", "Change Point Detection via Multivariate Singular "
     "Spectrum Analysis", ["Alomar", "Hamadanian", "Nambiar", "Shah"], None, None),

    # --- 3f. Counterfactuals: synthetic control and causal panels -----------
    # The audit's largest single hole: `synthetic control` matched **one**
    # document in 13,434. This is the literature the summit's Scenario Layer
    # and Sensitivity Propagation Engine are asking for without naming it.
    ("counterfactual", "Synthetic Control Methods for Comparative Case Studies: "
     "Estimating the Effect of California's Tobacco Control Program",
     ["Abadie", "Diamond", "Hainmueller"], None, "10.1198/jasa.2009.ap08746"),
    ("counterfactual", "Using Synthetic Controls: Feasibility, Data Requirements, "
     "and Methodological Aspects", ["Abadie"], None, None),
    ("counterfactual", "The Economic Costs of Conflict: A Case Study of the "
     "Basque Country", ["Abadie", "Gardeazabal"], None, None),
    ("counterfactual", "Robust Synthetic Control",
     ["Amjad", "Shah", "Shen"], None, None),
    ("counterfactual", "Synthetic Interventions",
     ["Agarwal", "Dahleh", "Shah", "Shen"], None, None),
    ("counterfactual", "Matrix Completion Methods for Causal Panel Data Models",
     ["Athey", "Bayati", "Doudchenko", "Imbens", "Khosravi"], None, None),
    ("counterfactual", "Synthetic Difference-in-Differences",
     ["Arkhangelsky", "Athey", "Hirshberg", "Imbens", "Wager"], None, None),
    ("counterfactual", "Inferring causal impact using Bayesian structural "
     "time-series models",
     ["Brodersen", "Gallusser", "Koehler", "Remy", "Scott"], None,
     "10.1214/14-AOAS788"),
    ("counterfactual", "Detecting and quantifying causal associations in large "
     "nonlinear time series datasets",
     ["Runge", "Nowack", "Kretschmer", "Flaxman", "Sejdinovic"], None,
     "10.1126/sciadv.aau4996"),
    ("counterfactual", "Survey and Evaluation of Causal Discovery Methods for "
     "Time Series", ["Assaad", "Devijver", "Gaussier"], None, None),
    ("counterfactual", "Causal inference for time series analysis: problems, "
     "methods and evaluation", ["Moraffah", "Sheth", "Karami", "Bhattacharya",
                                "Wang", "Tahir", "Raglin", "Liu"], None, None),

    # --- 3g. Forecasting: deep models, foundation models, reconciliation -----
    ("forecasting", "N-BEATS: Neural basis expansion analysis for interpretable "
     "time series forecasting",
     ["Oreshkin", "Carpov", "Chapados", "Bengio"], None, None),
    ("forecasting", "Are Transformers Effective for Time Series Forecasting?",
     ["Zeng", "Chen", "Zhang", "Xu"], None, None),
    ("forecasting", "A Time Series is Worth 64 Words: Long-term Forecasting "
     "with Transformers", ["Nie", "Nguyen", "Sinthong", "Kalagnanam"], None, None),
    ("forecasting", "Informer: Beyond Efficient Transformer for Long Sequence "
     "Time-Series Forecasting",
     ["Zhou", "Zhang", "Peng", "Zhang", "Li", "Xiong", "Zhang"], None, None),
    ("forecasting", "Chronos: Learning the Language of Time Series",
     ["Ansari", "Stella", "Turkmen", "Zhang", "Mercado", "Shen"], None, None),
    ("forecasting", "A decoder-only foundation model for time-series forecasting",
     ["Das", "Kong", "Sen", "Zhou"], None, None),
    ("forecasting", "DeepAR: Probabilistic Forecasting with Autoregressive "
     "Recurrent Networks",
     ["Salinas", "Flunkert", "Gasthaus", "Januschowski"], None, None),
    ("forecasting", "The M4 Competition: 100,000 time series and 61 forecasting "
     "methods", ["Makridakis", "Spiliotis", "Assimakopoulos"], None,
     "10.1016/j.ijforecast.2019.04.014"),
    ("forecasting", "The M5 competition: Background, organization, and "
     "implementation", ["Makridakis", "Spiliotis", "Assimakopoulos"], None,
     "10.1016/j.ijforecast.2021.07.007"),
    ("forecasting", "Optimal combination forecasts for hierarchical time series",
     ["Hyndman", "Ahmed", "Athanasopoulos", "Shang"], None, None),
    ("forecasting", "Optimal Forecast Reconciliation for Hierarchical and "
     "Grouped Time Series Through Trace Minimization",
     ["Wickramasuriya", "Athanasopoulos", "Hyndman"], None, None),
    ("forecasting", "Forecast reconciliation: A review",
     ["Athanasopoulos", "Hyndman", "Kourentzes", "Panagiotelis"], None, None),
    ("forecasting", "Strictly Proper Scoring Rules, Prediction, and Estimation",
     ["Gneiting", "Raftery"], None, "10.1198/016214506000001437"),
    ("forecasting", "Another look at measures of forecast accuracy",
     ["Hyndman", "Koehler"], None, "10.1016/j.ijforecast.2006.03.001"),
    ("forecasting", "Forecasting with Exponential Smoothing: The State Space "
     "Approach", ["Hyndman", "Koehler", "Ord", "Snyder"], None, None),
    ("forecasting", "Automatic Time Series Forecasting: The forecast Package for R",
     ["Hyndman", "Khandakar"], None, None),
    ("forecasting", "Forecasting intermittent demand: a comparative study",
     ["Syntetos", "Boylan"], None, None),

    # --- 3h. Systems: storage engines and data-series indexes ----------------
    ("systems", "Gorilla: A Fast, Scalable, In-Memory Time Series Database",
     ["Pelkonen", "Franklin", "Teller", "Cavallaro", "Huang", "Meza",
      "Veeraraghavan"], None, "10.14778/2824032.2824078"),
    ("systems", "Monarch: Google's Planet-Scale In-Memory Time Series Database",
     ["Adams", "Alonso", "Atkin", "Banning", "Bhola", "Buskens"], None,
     "10.14778/3415478.3415529"),
    ("systems", "ADS: the adaptive data series index",
     ["Zoumpatianos", "Idreos", "Palpanas"], None,
     "10.1007/s00778-016-0442-5"),
    ("systems", "The Lernaean Hydra of Data Series Similarity Search: An "
     "Experimental Evaluation of the State of the Art",
     ["Echihabi", "Zoumpatianos", "Palpanas", "Benbrahim"], None,
     "10.14778/3236187.3236200"),
    ("systems", "Return of the Lernaean Hydra: Experimental Evaluation of Data "
     "Series Approximate Similarity Search",
     ["Echihabi", "Zoumpatianos", "Palpanas", "Benbrahim"], None,
     "10.14778/3329772.3329781"),
    ("systems", "Data Series Management: The Road to Big Sequence Analytics",
     ["Palpanas"], None, "10.1145/2814710.2814719"),
    ("systems", "Temporal features in SQL:2011",
     ["Kulkarni", "Michels"], None, "10.1145/2380776.2380786"),
    ("systems", "An Improved Data Stream Summary: The Count-Min Sketch and its "
     "Applications", ["Cormode", "Muthukrishnan"], None,
     "10.1016/j.jalgor.2003.12.001"),

    # --- 3i. The bridge: event logs as signals ------------------------------
    # The performance spectrum is the existing process-mining answer to the
    # question this whole round is about — it turns an event log into a dense
    # numeric signal per handover and reads patterns off it (batching, FIFO
    # violations, queueing) without leaving the log. `event log to time series`
    # matched one document before this cohort.
    ("bridge", "Unbiased, Fine-Grained Description of Processes Performance "
     "from Event Data", ["Denisov", "Fahland", "van der Aalst"], None,
     "10.1007/978-3-319-98648-7_9"),
    ("bridge", "The Performance Spectrum Miner: Visual Analytics for Fine-Grained "
     "Performance Analysis of Processes",
     ["Denisov", "Belkina", "Fahland"], None, None),
    ("bridge", "Predictive Performance Monitoring of Material Handling Systems "
     "Using the Performance Spectrum",
     ["Denisov", "Fahland", "van der Aalst"], None,
     "10.1109/ICPM.2019.00028"),
    ("bridge", "Performance mining for batch processing using the performance "
     "spectrum", ["Klijn", "Fahland"], None, "10.1007/978-3-030-37453-2_15"),
    ("bridge", "Identifying and Reducing Errors in Remaining Time Prediction "
     "due to Inter-Case Dynamics",
     ["Klijn", "Fahland"], None, None),
    ("bridge", "Dealing With Concept Drifts in Process Mining",
     ["Bose", "van der Aalst", "Zliobaite", "Pechenizkiy"], None,
     "10.1109/TNNLS.2013.2278313"),
    ("bridge", "Fast and Accurate Business Process Drift Detection",
     ["Maaradji", "Dumas", "La Rosa", "Ostovar"], None,
     "10.1007/978-3-319-23063-4_27"),
    ("bridge", "Queue Mining for Delay Prediction in Multi-Class Service Processes",
     ["Senderovich", "Weidlich", "Gal", "Mandelbaum"], None,
     "10.1016/j.is.2015.03.010"),
    ("bridge", "Time and Activity Sequence Prediction of Business Process Instances",
     ["Polato", "Sperduti", "Burattin", "de Leoni"], None, None),
    ("bridge", "Outcome-Oriented Predictive Process Monitoring: Review and "
     "Benchmark", ["Teinemaa", "Dumas", "La Rosa", "Maggi"], None, None),

    # --- 3j. The supply-chain application ------------------------------------
    ("supply-chain", "Information Distortion in a Supply Chain: The Bullwhip Effect",
     ["Lee", "Padmanabhan", "Whang"], None, "10.1287/mnsc.43.4.546"),
    ("supply-chain", "Quantifying the Bullwhip Effect in a Simple Supply Chain: "
     "The Impact of Forecasting, Lead Times, and Information",
     ["Chen", "Drezner", "Ryan", "Simchi-Levi"], None,
     "10.1287/mnsc.46.3.436.12069"),
    ("supply-chain", "Modeling Managerial Behavior: Misperceptions of Feedback "
     "in a Dynamic Decision Making Experiment",
     ["Sterman"], None, "10.1287/mnsc.35.3.321"),
    ("supply-chain", "The Bullwhip Effect in Supply Chains",
     ["Lee", "Padmanabhan", "Whang"], None, None),
]


# ---------------------------------------------------------------------------
# Verified open locations the resolvers do not reach
# ---------------------------------------------------------------------------
# Same mechanism and same justification as ``apache-papers.py``'s ``MIRRORS``:
# a free PDF has sat on an author's or a society's page for years while
# OpenAlex and Unpaywall report the work as closed, because nothing links the
# copy to the DOI. Consulted **last**, so a work that later becomes properly
# open is still taken from its canonical home.
#
# Every URL here was checked by fetching it and confirming a ``%PDF`` header
# rather than trusting it to look plausible. That is not a formality: of 23
# plausible-looking guesses tried for this round, **12 returned an HTML error
# page** — four 404s from author pages that have been reorganised, SIGMOD
# Record's 2015 volume under a filename that does not follow its own
# convention, and three bot walls answering 200/403 with a challenge
# (openreview.net, PubMed Central, dspace.mit.edu answering 405 to a plain
# GET). A `dl_failed` line in the report means re-verifying the entry, not that
# the paper has vanished.
MIRRORS: dict[str, str] = {
    # Faloutsos self-hosts the whole pre-2000 CMU output; this is the paper
    # every subsequence-matching paper since 1994 measures itself against.
    "fast subsequence matching in time series databases":
        "https://www.cs.cmu.edu/~christos/PUBLICATIONS/sigmod94.pdf",
    # KDD-94 was an AAAI *workshop*, so the founding DTW-for-data-mining paper
    # is in the AAAI technical-report series and absent from every DB index.
    "using dynamic time warping to find patterns in time series":
        "https://cdn.aaai.org/Workshops/1994/WS-94-03/WS94-03-031.pdf",
    "the great time series classification bake off a review and experimental "
    "evaluation of recent algorithmic advances":
        "https://arxiv.org/pdf/1602.01711",
    # PVLDB is open by volume; Unpaywall does not index vol. 8.
    "gorilla a fast scalable in memory time series database":
        "https://www.vldb.org/pvldb/vol8/p1816-teller.pdf",
    "ads the adaptive data series index":
        "http://helios2.mi.parisdescartes.fr/~themisp/publications/vldbj16-ads.pdf",
    # SIGMOD Record has been free since 1969 and is not in Unpaywall at all.
    "temporal features in sql 2011":
        "https://sigmodrecord.org/publications/sigmodRecord/1209/pdfs/"
        "07.industry.kulkarni.pdf",
    # Journal of Statistical Software is gold OA but serves PDFs under a
    # content type of "pb", which is why the generic resolvers decline it.
    "automatic time series forecasting the forecast package for r":
        "https://www.jstatsoft.org/article/view/v027i03/v27i03.pdf",
    # Hyndman self-hosts his whole bibliography under short internal names that
    # bear no relation to the published titles ("Hierarchical6", "mase",
    # "MinT"), so no title-driven resolver can find them.
    "optimal combination forecasts for hierarchical time series":
        "https://robjhyndman.com/papers/Hierarchical6.pdf",
    "another look at measures of forecast accuracy":
        "https://robjhyndman.com/papers/mase.pdf",
    "optimal forecast reconciliation for hierarchical and grouped time series "
    "through trace minimization":
        "https://robjhyndman.com/papers/MinT.pdf",
    "strictly proper scoring rules prediction and estimation":
        "https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf",
}


def mirror_for(title: str) -> str | None:
    want = pf.norm(title)
    if want in MIRRORS:
        return MIRRORS[want]
    for key, url in MIRRORS.items():
        if want and (want in key or key in want) and \
                min(len(want), len(key)) / max(len(want), len(key)) > 0.85:
            return url
    return None


# ---------------------------------------------------------------------------
# Keogh's self-hosted archive
# ---------------------------------------------------------------------------
# His pages are hand-written HTML from the late 1990s onward, so there is no
# per-entry container to parse: an entry is a run of text inside a <p> or <li>
# with the title *colour-marked* (maroon, or the same colour written as
# rgb(153,0,0) or #990000 by whichever editor last touched the page) and the
# file linked as `[<a href="...pdf">pdf</a>]`. There is no markup relating the
# two, so each PDF link is attributed to the **nearest preceding colour-marked
# title** — the same positional treatment `gap-simulation.py` uses for the
# Winter Simulation Conference archive, and for the same reason.
#
# Measured on the current pages this attributes 113 of 114 links on the
# publications page. The one it misses is a link that precedes any title, which
# is correct behaviour: there is nothing to attribute it to.
_KEOGH_TITLE_RE = re.compile(
    r'<span[^>]*color:\s*(?:maroon|rgb\(153,\s*0,\s*0\)|#990000)[^>]*>(.*?)</span>'
    r'|<font[^>]*color="#99000[06]"[^>]*>(.*?)</font>',
    re.S | re.I,
)
# Colour is also used for *quotations from other people's papers* praising the
# work ("We observe that UCR-Suite wins in exact query answering", teal) — those
# use a different colour and so never match, but the year-in-parentheses that
# follows a real entry is a useful sanity signal and is used for the stem.
_YEAR_RE = re.compile(r"\((19|20)\d{2}\)")


# His pages are decades of pasted-in word-processor output, so titles arrive
# with typographic ligatures: "Matrix Proﬁle XI" carries U+FB01, not "fi". Left
# alone that breaks everything downstream at once — the `IndexDedup` title check
# cannot match the copy already held, `index_match` cannot match the requested
# title, and the filename records a word no search will ever find.
_LIGATURES = str.maketrans({
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u00a0": " ",
})


def _text(fragment: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", fragment)).translate(_LIGATURES)
    return re.sub(r"\s+", " ", plain).strip()


def _looks_like_authors(title: str) -> bool:
    """True when a colour-marked run is an author list rather than a title.

    The colour convention is applied by hand and occasionally lands on the
    wrong run — "Yan Zhu, Chin-Chia Michael Yeh, Zachary Zimmerman, Eamonn J.
    Keogh" is marked as a title on the Matrix Profile page. An author list is
    recognisable without a name database: it is mostly comma-separated groups of
    one to four capitalised words, with no lowercase connective words.
    """
    parts = [p.strip() for p in title.split(",") if p.strip()]
    if len(parts) < 3:
        return False
    namelike = sum(
        1 for p in parts
        if 1 <= len(p.split()) <= 4
        and all(re.fullmatch(r"[A-Z][\w.'\-]*", w) for w in p.split())
    )
    return namelike / len(parts) >= 0.6


def _keogh_authors(page: str, start: int, end: int) -> list[str]:
    """Best-effort author surnames for one entry on Keogh's page.

    Authors sit either immediately *before* the title (bolded, "Abdullah Mueen,
    Eamonn Keogh and Nima Bigdely-Shamlo (2009). <title>") or immediately
    *after* it ("<title>. Chin-Chia Michael Yeh, Yan Zhu, ... Eamonn Keogh
    (2016)"), with no markup distinguishing the two cases. Both windows are
    tried and the first that yields a plausible name list wins.

    This only decides the *Inbox* filename. ``import-downloads.py`` re-derives
    author and title from the PDF itself when it files the paper, so a miss
    here costs a slightly worse temporary handle and nothing else — which is
    why this is a heuristic rather than a parser.
    """
    for window in (_text(page[end:end + 320]), _text(page[max(0, start - 320):start])):
        # Cut at the year, which terminates the author list in both layouts.
        m = _YEAR_RE.search(window)
        chunk = window[:m.start()] if m else window
        chunk = re.split(r"[.;]\s|\[", chunk)[0]
        names = [n.strip() for n in re.split(r",| and | & ", chunk) if n.strip()]
        surnames = []
        for n in names:
            parts = [p for p in re.split(r"\s+", n) if re.fullmatch(r"[A-Z][\w'’\-]+", p)]
            if parts:
                surnames.append(parts[-1])
        if surnames:
            return surnames[:8]
    return ["Keogh"]


def keogh_index(sess) -> list[dict]:
    """Title → PDF across Keogh's self-hosted pages."""
    seen: set[str] = set()
    out: list[dict] = []
    for page_url in KEOGH_PAGES:
        try:
            page = sess.get(page_url, timeout=90).text
        except Exception as exc:  # noqa: BLE001
            print(f"  [keogh] {page_url} unreachable ({type(exc).__name__})")
            continue
        # Empty colour spans (`<span style="color: rgb(153, 0, 0);"></span>`)
        # are left behind wherever the page was edited, and they matter more
        # than they look: an empty span sitting *between* a real title and its
        # PDF link becomes the nearest preceding title, so the entry is skipped
        # for having a blank title. That silently cost Matrix Profile II, IX, X
        # and XV–XVIII — the sequence looks complete until the numbers are read.
        # Blanks are therefore discarded before attribution, not after.
        titles = [(m.start(), m.end(), _text(next((g for g in m.groups() if g), "")))
                  for m in _KEOGH_TITLE_RE.finditer(page)]
        titles = [t for t in titles if len(t[2].strip(" .,")) >= 15
                  and not _looks_like_authors(t[2])]
        n_page = 0
        for m in re.finditer(r'href=["\']([^"\']+\.pdf)["\']', page, re.I):
            before = [t for t in titles if t[1] <= m.start()]
            if not before:
                continue
            start, end, raw = before[-1]
            title = raw.strip(" .,")
            url = urljoin(page_url, html.unescape(m.group(1)))
            key = pf.norm(title)
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "url": url,
                        "authors": _keogh_authors(page, start, end)})
            n_page += 1
        print(f"  [keogh] {n_page:3d} new from {page_url.rsplit('/', 1)[-1] or 'TimeSeriesMotifs/'}")
    print(f"  [keogh] {len(out)} distinct self-hosted papers")
    return out


# ---------------------------------------------------------------------------
# Shah's page, and the Scholar profiles
# ---------------------------------------------------------------------------
# His listing is one WordPress paragraph per work — "Title, by A. Author and
# B. Author, venue, year (link)" — grouped under year headings, with the anchor
# text a bare "link" pointing at a per-work page that carries the actual PDF or
# arXiv URL. So the listing gives title+year cheaply and the detail page is
# fetched only for works that survive the topical filter.
_SHAH_PARA_RE = re.compile(r'<p class="wp-block-paragraph">(.*?)</p>', re.S)
_SHAH_YEAR_RE = re.compile(r"<h4[^>]*>\s*((?:19|20)\d{2})\s*</h4>", re.I)

# Which of his output belongs to this round. His corpus is majority networking
# and information theory, so this is a keep-list rather than a drop-list.
SHAH_KEEP = re.compile(
    r"time series|time-series|forecast|matrix estimation|matrix completion|"
    r"matrix factorization|synthetic control|synthetic intervention|"
    r"singular spectrum|imputation|tspdb|latent source|latent variable|"
    r"nearest neighbo|blind regression|collaborative filtering|"
    r"counterfactual|causal|panel data|difference-in-differences|"
    r"principal component regression|change point|changepoint|anomaly|"
    r"bitcoin|demand|inventory|recommendation|sequential|"
    r"robustness of|prediction|predict",
    re.I,
)
# ... minus the places those words appear in the networking half. "Prediction"
# and "sequential" are the two that need this: they occur in the scheduling and
# information-theory work as often as in the estimation work.
SHAH_DROP = re.compile(
    r"gossip|network coding|\bTCP\b|switch|packet|routing|wireless|"
    r"OpenFlow|datacenter|data center|queueing network|throughput|"
    r"scheduling algorithm|medium access|\bMAC\b|multi-?hop|broadcast|"
    r"rumor|epidemic|belief propagation|message passing|cache|"
    r"spectrum sharing|interference|capacity region|input-queued|"
    r"crossbar|fastpass|circuit|\bARQ\b|erasure|coding meets",
    re.I,
)
# The filter above reads titles, and titles are the wrong place to separate a
# method paper from an application of it: "Forecasting optimal treatments in
# relapsed/refractory mature T-cell lymphoma" is a forecasting paper by every
# word in its title and belongs in a haematology library, not this one. The
# venue says so and the title cannot, which is the same structural signal the
# Databricks blog source uses (see `README.md` → `Blogs/<Company>/`): where a
# publisher already classifies its own output, use that classification.
SHAH_DROP_VENUE = re.compile(
    r"US Patent|patent app|"                       # 19 patents on the profile
    r"\bBlood\b|Blood Advances|haematolog|hematolog|Lancet|"  # clinical trials
    r"Biomedical Engineering|medRxiv|bioRxiv|TURCOMAT|"
    r"Smart Grid",                                 # utility-load case studies
    re.I,
)
# Scholar profile rows are occasionally scraped from a mangled record: an author
# block glued onto the title, a page's own URL, or a Python repr that leaked
# into the citation. None can be resolved and each would be filed under a title
# no reader would recognise.
SHAH_JUNK_TITLE = re.compile(r"@[\w.]+\.\w+|https?://|www\.\s|bound method", re.I)


def shah_index(sess) -> list[dict]:
    """Title → detail page for Devavrat Shah's self-hosted listing.

    Note what this cannot supply: the page's year headings run 1999–2018 and
    stop, so his post-2018 work — mSSA, tspDB, synthetic interventions, causal
    matrix completion, i.e. exactly the line this round is after — is not here
    at all. That is why enumeration for `shah` comes from Scholar and this
    index is consulted as a *resolver*, not as the bibliography.
    """
    try:
        page = sess.get(SHAH_PUBS, timeout=90).text
    except Exception as exc:  # noqa: BLE001
        print(f"  [shah] page unreachable ({type(exc).__name__}); skipping")
        return []
    years = [(m.start(), int(m.group(1))) for m in _SHAH_YEAR_RE.finditer(page)]
    out: list[dict] = []
    for m in _SHAH_PARA_RE.finditer(page):
        body = m.group(1)
        link = re.search(r'href=["\'](https://devavrat\.mit\.edu/publication/[^"\']+)["\']',
                         body)
        text = _text(body)
        title = re.split(r",\s*by\s+", text)[0].strip(" .")
        if len(title) < 12:
            continue
        prior = [y for pos, y in years if pos < m.start()]
        arx = re.search(r"arXiv[:\s]*((?:\d{4}\.\d{4,5})|(?:[a-z\-]+/\d{7}))", text, re.I)
        out.append({"title": title, "year": prior[-1] if prior else None,
                    "detail": link.group(1) if link else None,
                    "arxiv": arx.group(1) if arx else None})
    print(f"  [shah] {len(out)} entries on his publications page "
          f"({min((e['year'] for e in out if e['year']), default='?')}"
          f"–{max((e['year'] for e in out if e['year']), default='?')})")
    return out


def shah_detail_pdf(sess, url: str) -> str | None:
    """The PDF or arXiv link on one of his per-work pages."""
    try:
        page = sess.get(url, timeout=60).text
    except Exception:  # noqa: BLE001
        return None
    for href in re.findall(r'href=["\']([^"\']+)["\']', page):
        low = href.lower()
        if "wp-content/plugins" in low or "wp-includes" in low:
            continue
        if low.endswith(".pdf") or "arxiv.org" in low:
            return html.unescape(href)
    return None


def scholar_profile(sess, user: str, pagesize: int = 100,
                    max_pages: int = 6) -> list[dict]:
    """Every publication on a Google Scholar profile, newest-cited first.

    Scholar is the only complete and current enumeration of an author's output,
    and it is also the source most likely to refuse. So the result is **cached
    to `imports/scholar-<user>.json`** and the cache is used whenever the fetch
    fails — a blocked run degrades to the last good enumeration instead of
    silently reporting an author with no publications.

    It is used for enumeration only. Scholar links to publisher landing pages,
    not to PDFs, so every title still goes through the normal resolver ladder.
    """
    cache = SCHOLAR_CACHE / f"scholar-{user}.json"
    rows: list[dict] = []
    blocked = False
    for start in range(0, pagesize * max_pages, pagesize):
        params = {"user": user, "hl": "en", "cstart": start, "pagesize": pagesize}
        try:
            resp = sess.get(SCHOLAR, params=params, timeout=60)
            body = resp.text
        except Exception as exc:  # noqa: BLE001
            print(f"  [scholar] {user} page {start} failed ({type(exc).__name__})")
            blocked = True
            break
        if "gsc_a_tr" not in body:
            if start == 0:
                print(f"  [scholar] {user} returned no publication rows "
                      "(rate-limited or profile changed)")
                blocked = True
            break
        page_rows = []
        for row in re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', body, re.S):
            tm = re.search(r'class="gsc_a_at"[^>]*>(.*?)</a>', row, re.S)
            grey = re.findall(r'class="gs_gray">(.*?)</div>', row, re.S)
            cm = re.search(r'class="gsc_a_ac[^"]*"[^>]*>(.*?)</a>', row, re.S)
            ym = re.search(r'class="gsc_a_h[^"]*"[^>]*>(.*?)</span>', row, re.S)
            title = _text(tm.group(1)) if tm else ""
            if not title:
                continue
            cites = _text(cm.group(1)) if cm else ""
            page_rows.append({
                "title": title,
                "authors": _text(grey[0]) if grey else "",
                "venue": _text(grey[1]) if len(grey) > 1 else "",
                "cites": int(cites) if cites.isdigit() else 0,
                "year": _text(ym.group(1)) if ym else "",
            })
        rows += page_rows
        if len(page_rows) < pagesize:
            break
        time.sleep(3.0)

    if rows:
        seen: set[str] = set()
        uniq = []
        for r in rows:
            k = pf.norm(r["title"])
            if k and k not in seen:
                seen.add(k)
                uniq.append(r)
        uniq.sort(key=lambda r: -r["cites"])
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(uniq, indent=1), encoding="utf-8")
        print(f"  [scholar] {user}: {len(uniq)} publications "
              f"({sum(r['cites'] for r in uniq)} citations)")
        return uniq
    if blocked and cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        print(f"  [scholar] {user}: using cached enumeration ({len(cached)} works)")
        return cached
    return []


def shah_papers(sess, profile: list[dict], page_index: list[dict]) -> list[Paper]:
    """The time-series subset of Shah's output, resolved page-first."""
    by_title = {pf.norm(e["title"]): e for e in page_index}
    out: list[Paper] = []
    seen: set[str] = set()
    dropped = {"topic": 0, "venue": 0, "junk": 0}
    for rec in profile:
        title = rec["title"]
        if not SHAH_KEEP.search(title) or SHAH_DROP.search(title):
            dropped["topic"] += 1
            continue
        if SHAH_DROP_VENUE.search(rec.get("venue", "")):
            dropped["venue"] += 1
            continue
        if SHAH_JUNK_TITLE.search(title):
            dropped["junk"] += 1
            continue
        key = pf.norm(title)
        if key in seen:
            continue
        seen.add(key)
        authors = [a.strip() for a in re.split(r",| and ", rec.get("authors", ""))
                   if a.strip()][:8] or ["Shah"]
        url = None
        hit = by_title.get(key) or _fuzzy(by_title, key)
        if hit:
            if hit.get("arxiv"):
                url = f"https://arxiv.org/pdf/{hit['arxiv']}"
            elif hit.get("detail"):
                url = shah_detail_pdf(sess, hit["detail"])
        out.append(("shah", title, authors, url, None))
    print(f"  [shah] dropped {dropped['topic']} off-topic, "
          f"{dropped['venue']} by venue (patents / clinical), "
          f"{dropped['junk']} malformed rows")
    return out


def _fuzzy(by_title: dict[str, dict], key: str, cutoff: float = 0.93):
    best, best_score = None, 0.0
    for hay, entry in by_title.items():
        ratio = difflib.SequenceMatcher(None, key, hay).ratio()
        if ratio >= cutoff and ratio > best_score:
            best, best_score = entry, ratio
    return best


def index_match(entries: list[dict], title: str, cutoff: float = 0.90) -> str | None:
    """Best PDF in a title-indexed archive, by fuzzy title agreement.

    Carries forward the guard `gap-simulation.py` documents: a pure ratio match
    must also agree on every word of six characters or more. Academic titles in
    a numbered series are engineered to look alike — "Matrix Profile XXII" and
    "Matrix Profile XXIII" sit far above any usable cutoff, and the
    distinguishing token is one word — so a ratio alone silently returns the
    wrong paper under the requested paper's name.
    """
    want = pf.norm(title)
    if len(want) < 12:
        return None
    long_words = {w for w in want.split() if len(w) >= 6}
    best, best_score = None, 0.0
    for e in entries:
        hay = pf.norm(e["title"])
        if hay == want:
            return e["url"]
        if want in hay or hay in want:
            if min(len(want), len(hay)) / max(len(want), len(hay)) > 0.75:
                return e["url"]
        ratio = difflib.SequenceMatcher(None, want, hay).ratio()
        if ratio >= cutoff and ratio > best_score:
            if long_words and not long_words <= set(hay.split()):
                continue
            best, best_score = e["url"], ratio
    return best


class Archives:
    """The self-hosted archives, built lazily on first use."""

    def __init__(self, sess):
        self.sess = sess
        self._keogh: list[dict] | None = None

    @property
    def keogh(self) -> list[dict]:
        if self._keogh is None:
            self._keogh = keogh_index(self.sess)
        return self._keogh


def resolve(sess, arc: Archives, title: str, authors: list[str],
            url: str | None, doi: str | None) -> tuple[str | None, str]:
    if url:
        return url, "override"
    own = index_match(arc.keogh, title)
    if own:
        return own, "cs.ucr.edu/~eamonn"
    for fn, how in (
        (lambda: pf.arxiv_pdf(title, authors), "arxiv"),
        (lambda: pf.openalex_pdf(title, authors, email=pf.git_email()), "openalex"),
    ):
        try:
            got = fn()
        except Exception:  # noqa: BLE001
            got = None
        if got:
            return got, how
    if doi:
        try:
            for loc in pf.unpaywall_locations(doi, pf.git_email()):
                return loc, "unpaywall"
        except Exception:  # noqa: BLE001
            pass
    try:
        got = pf.semanticscholar_pdf(title, authors)
    except Exception:  # noqa: BLE001
        got = None
    if got:
        return got, "semanticscholar"
    try:
        hit = pf.dblp_best(title, authors)
    except Exception:  # noqa: BLE001
        hit = None
    if hit:
        for ee in hit.get("ee") or []:
            if ee.lower().endswith(".pdf") and not pf.is_bot_walled(ee):
                return ee, "dblp-ee"
        if hit.get("doi") and not doi:
            try:
                for loc in pf.unpaywall_locations(hit["doi"], pf.git_email()):
                    return loc, "unpaywall-via-dblp"
            except Exception:  # noqa: BLE001
                pass
    if got := mirror_for(title):
        return got, "verified-mirror"
    return None, "unresolved"


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"done": {}}


def save_state(state: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# coverage cross-check
# ---------------------------------------------------------------------------

def cmd_scholar(sess) -> int:
    """Report, per profile publication, whether the corpus holds it."""
    dedup = pf.IndexDedup()
    SCHOLAR_REPORT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for user, who in ((KEOGH_SCHOLAR, "Keogh"), (SHAH_SCHOLAR, "Shah")):
        profile = scholar_profile(sess, user)
        held = 0
        for r in profile:
            has = dedup.contains(r["title"])
            held += bool(has)
            rows.append({"author": who, "year": r["year"], "cites": r["cites"],
                         "title": r["title"], "venue": r["venue"],
                         "in_corpus": "yes" if has else "no"})
        if profile:
            top = [r for r in profile[:50]]
            top_held = sum(1 for r in top if dedup.contains(r["title"]))
            print(f"  [{who}] {held}/{len(profile)} of the profile is in the corpus; "
                  f"{top_held}/{len(top)} of the 50 most-cited")
    with SCHOLAR_REPORT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["author", "year", "cites", "title",
                                           "venue", "in_corpus"])
        w.writeheader()
        w.writerows(rows)
    print(f"report: {SCHOLAR_REPORT.relative_to(ROOT)}")
    return 0


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def run(what: str, dry_run: bool, skip_held: bool, limit: int | None) -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    arc = Archives(sess)
    papers: list[Paper] = []

    if what in ("keogh", "all"):
        entries = arc.keogh
        papers += [("keogh", e["title"], e["authors"], e["url"], None)
                   for e in entries]
    if what in ("shah", "all"):
        profile = scholar_profile(sess, SHAH_SCHOLAR)
        page_index = shah_index(sess)
        picked = shah_papers(sess, profile, page_index)
        print(f"  [shah] {len(picked)} of {len(profile)} profile entries are "
              "time-series / estimation / causal work")
        papers += picked
    if what in ("gaps", "all"):
        papers += GAP_PAPERS

    if limit:
        papers = papers[:limit]

    dedup = pf.IndexDedup() if skip_held else None
    state = load_state()
    rows: list[dict] = []

    for topic, title, authors, url, doi in papers:
        key = pf.norm(title)
        prev = state["done"].get(key)
        if prev and prev.get("status") == "downloaded" and (ROOT / prev["file"]).exists():
            print(f"[{'cached':>22}] {title[:74]}")
            rows.append(prev)
            continue
        if dedup and dedup.contains(title):
            row = {"topic": topic, "title": title, "how": "held", "url": "",
                   "status": "already-in-library", "file": ""}
            print(f"[{'already in library':>22}] {title[:74]}")
            rows.append(row)
            state["done"][key] = row
            continue

        found, how = resolve(sess, arc, title, authors, url, doi)
        status, dest = ("no-open-copy" if not found else "pending"), ""
        if found and dry_run:
            status = "would-download"
        elif found:
            path = OUT / f"{pf.safe_stem(authors, title)}.pdf"
            ok, detail = pf.download_pdf(sess, found, path)
            status = "downloaded" if ok else f"failed: {detail}"
            dest = str(path.relative_to(ROOT)) if ok else ""
        print(f"[{status:>22}] ({how}) {title[:70]}")
        row = {"topic": topic, "title": title, "how": how, "url": found or "",
               "status": status, "file": dest}
        rows.append(row)
        state["done"][key] = row
        save_state(state)

    return rows


def write_report(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["topic", "title", "how", "url",
                                           "status", "file"])
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    c = Counter(r["status"].split(":")[0] for r in rows)
    print(f"\n{len(rows)} works: " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    print(f"report: {REPORT.relative_to(ROOT)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("what", nargs="?", default="all",
                   choices=["keogh", "shah", "gaps", "scholar", "all"])
    p.add_argument("--dry-run", action="store_true",
                   help="resolve only; do not download")
    p.add_argument("--no-dedup", action="store_true",
                   help="fetch even works the index already holds")
    p.add_argument("--limit", type=int, help="process at most N works (smoke test)")
    args = p.parse_args(argv)

    if args.what == "scholar":
        return cmd_scholar(pf.session())

    rows = run(args.what, args.dry_run, skip_held=not args.no_dedup,
               limit=args.limit)
    write_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
