#!/usr/bin/env python3
"""Gap-closing harvest: **business process simulation** and its foundations.

Three passes are worked here, and they are deliberately different in kind.

1. ``SLIDE_REFS`` — the 26 references van der Aalst appended to his 31-10-2025
   *Simulation — my take on it* slide deck (`Inbox/simulation-wvda-31-10-2025.pdf`).
   This is the author's own reading of his own line of work, running from the
   1988 ExSpect master's thesis to the 2022 system-dynamics papers, and the deck
   is only useful in the library if the things it cites are in there too.
   Resolution prefers **his own publications page**, which self-hosts PDFs for
   material no OA backend indexes at all: a Dutch master's thesis, a 1990
   European Simulation Multiconference paper, an Elsevier book chapter from 1991.

2. ``GAP_PAPERS`` — works the deck argues *about* but does not cite, grouped by
   the gap the audit (``gap-audit.py --topic simulation``) found. Three kinds:

   * **the neighbouring literature the deck names without citing** — Camargo's
     Simod / deep-learning generators, Senderovich's queue mining, the
     agent-based and object-centric simulators, comparative process mining;
   * **the foundations it presumes** — Little's law, Kingman's heavy-traffic
     formula, the Pollaczek-Khinchine formula, Lindley's recursion, Jackson
     networks, the M/G/∞ infinite-server model behind recommendation 6, plus
     the discrete-event simulation methodology (Nelson/Law-Kelton-style output
     analysis, common random numbers, steady-state initialisation bias);
   * **the *tooling* history it treats as common knowledge** — Simula, SIMSCRIPT,
     GPSS, SimPy, CPN Tools, Vensim/system-dynamics.

Why the foundations matter here and not elsewhere: slide 21 is an argument that
the M/M/1 sojourn-time formula is the wrong model for a business process, and
slide 11 that no process is in steady state. Neither claim is checkable from a
library that holds the process-mining papers and none of the queueing theory
they push back against.

3. ``own`` — a **scan of his publications page** for every simulation- or
   queue-related entry that self-hosts a PDF, minus what the library already
   holds. The deck's own reference list is explicitly "not intended to be
   complete and a bit outdated", and it is: it stops in 2022 and omits the queue
   mining (Senderovich/Fahland), the digital-twin line, the object-centric
   simulation work including the in-print ECMS 2026 paper, and — the largest
   single omission — his 1995 *Simulation Handbook* (`Handboek simulatie`,
   Computing Science Report 95/32), which is the foundational text behind
   everything the deck asserts about abstraction level and steady state. A
   keyword scan of the page finds these without anyone having to guess titles,
   and re-running it later picks up what he adds.

Resolution goes through ``paperfetch`` (own-site → arXiv → OpenAlex →
Unpaywall-by-DOI → Semantic Scholar) with explicit URL overrides where a work is
only available from one place. Output lands in ``Inbox/gap-simulation/`` for
``import-downloads.py`` to file and the indexer to pick up.

Usage:
  scripts/.venv/bin/python scripts/gap-simulation.py slides   # the 26 slide refs
  scripts/.venv/bin/python scripts/gap-simulation.py gaps     # the gap cohort
  scripts/.venv/bin/python scripts/gap-simulation.py own      # his own page
  scripts/.venv/bin/python scripts/gap-simulation.py all
  scripts/.venv/bin/python scripts/gap-simulation.py all --dry-run
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
OUT = ROOT / "Inbox" / "gap-simulation"
STATE = OUT / "_gap-simulation.json"
REPORT = OUT / "_gap-simulation-report.csv"

VDAALST_PUBS = "https://www.vdaalst.com/publications/publications.html"
WSC_ARCHIVE = "https://informs-sim.org/"
WHITT_PUBS = "http://www.columbia.edu/~ww2040/allpapers.html"

# (topic, title, authors, direct-url-or-None, doi-or-None)
Paper = tuple[str, str, list[str], str | None, str | None]

# --------------------------------------------------------------------------
# 1. The 26 references appended to the 31-10-2025 simulation deck.
#    Numbering follows the slide, which is how the deck refers to them.
# --------------------------------------------------------------------------
SLIDE_REFS: list[Paper] = [
    ("slide-ref", "Discovering System Dynamics Simulation Models Using Process Mining",
     ["Pourbafrani", "van der Aalst"], None, "10.1109/ACCESS.2022.3193507"),
    ("slide-ref", "Hybrid Business Process Simulation: Updating Detailed Process "
     "Simulation Models Using High-Level Simulations",
     ["Pourbafrani", "van der Aalst"], None, "10.1007/978-3-031-05760-1_11"),
    ("slide-ref", "Towards Reliable Business Process Simulation: A Framework to "
     "Integrate ERP Systems", ["Park", "van der Aalst"], None,
     "10.1007/978-3-030-79186-5_8"),
    ("slide-ref", "Extracting Process Features from Event Logs to Learn "
     "Coarse-Grained Simulation Models", ["Pourbafrani", "van der Aalst"], None,
     "10.1007/978-3-030-79382-1_8"),
    ("slide-ref", "Interactive Process Improvement Using Simulation of Enriched "
     "Process Trees", ["Pourbafrani", "van der Aalst"], None,
     "10.1007/978-3-031-14135-5_5"),
    ("slide-ref", "SIMPT: Process Improvement Using Interactive Simulation of "
     "Time-Aware Process Trees", ["Pourbafrani", "Jiao", "van der Aalst"], None,
     "10.1007/978-3-030-75018-3_39"),
    ("slide-ref", "Supporting Automatic System Dynamics Model Generation for "
     "Simulation in the Context of Process Mining",
     ["Pourbafrani", "van Zelst", "van der Aalst"], None,
     "10.1007/978-3-030-53337-3_19"),
    ("slide-ref", "PMSD: Data-Driven Simulation Using System Dynamics and Process Mining",
     ["Pourbafrani", "van der Aalst"], None, None),
    ("slide-ref", "Semi-automated Time-Granularity Detection for Data-Driven "
     "Simulation Using Process Mining and System Dynamics",
     ["Pourbafrani", "van Zelst", "van der Aalst"], None,
     "10.1007/978-3-030-62522-1_6"),
    ("slide-ref", "Conformance Checking Approximation Using Simulation",
     ["Fani Sani", "Garza Gonzalez", "van Zelst", "van der Aalst"], None,
     "10.1109/ICPM49681.2020.00025"),
    ("slide-ref", "Process mining and simulation: a match made in heaven!",
     ["van der Aalst"], None, None),
    ("slide-ref", "Business Process Simulation Survival Guide",
     ["van der Aalst"], None, "10.1007/978-3-642-45100-3_15"),
    ("slide-ref", "Liquid business process model collections",
     ["van der Aalst", "La Rosa", "ter Hofstede", "Wynn"], None, None),
    ("slide-ref", "Generating Event Logs with Workload-Dependent Speeds from "
     "Simulation Models", ["Nakatumba", "Westergaard", "van der Aalst"], None,
     "10.1007/978-3-642-31069-0_31"),
    ("slide-ref", "Simulation to Analyze the Impact of a Schedule-aware Workflow "
     "Management System", ["Mans", "Russell", "van der Aalst", "Bakker", "Moleman"],
     None, "10.1177/0037549709341022"),
    ("slide-ref", "Business Process Simulation Revisited", ["van der Aalst"], None,
     "10.1007/978-3-642-15723-3_1"),
    ("slide-ref", "Business Trend Analysis by Simulation",
     ["Schonenberg", "Jian", "Sidorova", "van der Aalst"], None,
     "10.1007/978-3-642-13094-6_38"),
    ("slide-ref", "Process Mining and Simulation",
     ["Wynn", "Rozinat", "van der Aalst", "ter Hofstede", "Fidge"], None, None),
    ("slide-ref", "Workflow simulation for operational decision support",
     ["Rozinat", "Wynn", "van der Aalst", "ter Hofstede", "Fidge"], None,
     "10.1016/j.datak.2009.02.014"),
    ("slide-ref", "Discovering simulation models",
     ["Rozinat", "Mans", "Song", "van der Aalst"], None,
     "10.1016/j.is.2008.09.002"),
    ("slide-ref", "Workflow Simulation for Operational Decision Support Using "
     "Design, Historic and State Information",
     ["Rozinat", "Wynn", "van der Aalst", "ter Hofstede", "Fidge"], None,
     "10.1007/978-3-540-85758-7_16"),
    ("slide-ref", "Business Process Simulation for Operational Decision Support",
     ["Wynn", "Dumas", "Fidge", "ter Hofstede", "van der Aalst"], None,
     "10.1007/978-3-540-78238-4_9"),
    ("slide-ref", "Timed coloured Petri nets and their application to logistics",
     ["van der Aalst"], None, None),
    ("slide-ref", "Modelling logistic systems with EXSPECT",
     ["van der Aalst", "Waltmans"], None, None),
    ("slide-ref", "Modelling Flexible Manufacturing Systems with EXSPECT",
     ["van der Aalst", "Waltmans"], None, None),
    ("slide-ref", "Specificatie en Simulatie met behulp van ExSpect",
     ["van der Aalst"], None, None),
]

# --------------------------------------------------------------------------
# 2. The gap cohort — what the deck argues about but does not cite.
# --------------------------------------------------------------------------
GAP_PAPERS: list[Paper] = [
    # --- 2a. Data-driven BPS: the generators the deck names (Camargo et al.) ---
    ("bps-discovery",
     "Automated discovery of business process simulation models from event logs",
     ["Camargo", "Dumas", "Gonzalez-Rojas"], None, "10.1016/j.dss.2020.113284"),
    ("bps-discovery",
     "Simod: A Tool for Automated Discovery of Business Process Simulation Models",
     ["Camargo", "Dumas", "Gonzalez-Rojas"], None, None),
    ("bps-discovery",
     "Learning Accurate Business Process Simulation Models from Event Logs via "
     "Automated Process Discovery",
     ["Camargo", "Barzola", "Dumas", "Rojas", "Weber"], None, None),
    ("bps-discovery",
     "Learning Accurate LSTM Models of Business Processes",
     ["Camargo", "Dumas", "Gonzalez-Rojas"], None, "10.1007/978-3-030-26619-6_19"),
    ("bps-discovery",
     "Discovering Generative Models from Event Logs: Data-driven Simulation vs "
     "Deep Learning", ["Camargo", "Dumas", "Gonzalez-Rojas"], None, None),
    ("bps-discovery",
     "Learning Business Process Simulation Models: A Hybrid Process Mining "
     "and Deep Learning Approach",
     ["Camargo", "Dumas", "Gonzalez-Rojas"], None, None),
    ("bps-discovery",
     "Discovering Business Process Simulation Models in the Presence of "
     "Multitasking and Availability Constraints",
     ["Lopez-Pintado", "Dumas"], None, "10.1016/j.datak.2022.102092"),
    # Springer's OA landing page serves HTML; the content/pdf mirror is the
    # only URL that yields the file.
    ("bps-discovery",
     "Prosimos: Discovering and Simulating Business Processes with "
     "Differentiated Resources", ["Lopez-Pintado", "Dumas"],
     "https://link.springer.com/content/pdf/10.1007/978-3-031-26886-1_23.pdf",
     None),
    ("bps-discovery",
     "Discovering Process Models with Long-Term Dependencies while Providing "
     "Guarantees and Filtering Infrequent Behavior Patterns",
     ["Mannhardt"], None, None),
    ("bps-discovery",
     "The Use of Process Mining in Business Process Simulation Model "
     "Construction: Structuring the Field",
     ["Martin", "Depaire", "Caris"], None, "10.1007/s12599-015-0410-4"),
    # --- 2b. Queue mining and resource behaviour ---------------------------
    ("queue-mining",
     "Queue Mining: Predicting Delays in Service Processes",
     ["Senderovich", "Weidlich", "Gal", "Mandelbaum"], None,
     "10.1007/978-3-319-07881-6_4"),
    ("queue-mining",
     "Queue mining for delay prediction in multi-class service processes",
     ["Senderovich", "Weidlich", "Gal", "Mandelbaum"], None,
     "10.1016/j.is.2015.03.010"),
    ("queue-mining",
     "Data-driven performance analysis of scheduled processes",
     ["Senderovich", "Rogge-Solti", "Gal", "Mendling", "Mandelbaum"], None,
     "10.1007/978-3-319-23063-4_3"),
    ("queue-mining",
     "The ROAD from sensor data to process instances via interaction mining",
     ["Senderovich", "Rogge-Solti", "Gal", "Mendling", "Mandelbaum", "Kadish"],
     None, "10.1007/978-3-319-39696-5_16"),
    ("queue-mining",
     "Congestion Graphs for Automated Time Predictions",
     ["Senderovich", "Beck", "Gal", "Weidlich"], None, None),
    ("queue-mining",
     "Conformance Checking and Performance Improvement in Scheduled Processes: "
     "A Queueing-Network Perspective",
     ["Senderovich", "Weidlich", "Gal"], None, "10.1016/j.is.2017.10.001"),
    ("queue-mining",
     "Analyzing Resource Behavior Using Process Mining",
     ["Nakatumba", "van der Aalst"], None, "10.1007/978-3-642-12186-9_8"),
    ("queue-mining",
     "The Impact of Workload on Process Performance",
     ["Nakatumba", "Westergaard", "van der Aalst"], None, None),
    ("queue-mining",
     "Discovering Queues from Event Logs with Varying Levels of Information",
     ["Senderovich", "Weidlich", "Gal", "Mandelbaum"], None,
     "10.1007/978-3-319-42887-1_13"),
    # --- 2c. Queueing theory: the foundations slide 21 argues against ------
    # The original papers (Little 1961, Kingman 1961, Lindley 1952, Jackson
    # 1957/1963) are INFORMS and Cambridge and have no open copy anywhere; a
    # probe run resolved none of them. What *is* open is Ward Whitt's complete
    # self-hosted bibliography, which contains the authoritative review of each
    # result plus the parts of the theory the deck actually leans on — the
    # infinite-server model behind recommendation 6 and the time-varying-arrival
    # work behind "no process is in steady state". Kept the closed originals in
    # the list anyway: they cost one lookup each and record the wall.
    ("queueing-theory",
     "A Proof for the Queuing Formula: L = lambda W",
     ["Little"], None, "10.1287/opre.9.3.383"),
    ("queueing-theory",
     "Little's Law as Viewed on its 50th Anniversary",
     ["Little"], None, "10.1287/opre.1110.0940"),
    ("queueing-theory",
     "A Review of L = W and Extensions", ["Whitt"], None, None),
    # Whitt's index links two Little's-Law files that his server no longer has
    # (LittlePredict081712.pdf, PLL_042917.pdf both 404). The supplementary
    # report and the time-varying paper are live and carry the same argument:
    # L = λW holds over a finite horizon without any steady-state assumption,
    # which is the version the deck needs.
    ("queueing-theory",
     "Statistical Analysis with Little's Law, Supplementary Material: "
     "Technical Report", ["Kim", "Whitt"],
     "http://www.columbia.edu/~ww2040/littledata032512.pdf", None),
    ("queueing-theory",
     "Estimating Waiting Times with the Time-Varying Little's Law",
     ["Kim", "Whitt"],
     "http://www.columbia.edu/~ww2040/PEIS_TVLL_Main061212.pdf", None),
    ("queueing-theory",
     "The single server queue in heavy traffic",
     ["Kingman"], None, "10.1017/S0305004100036094"),
    ("queueing-theory",
     "Heavy Traffic Limit Theorems for Queues: A Survey", ["Whitt"], None, None),
    ("queueing-theory",
     "An Interpolation Approximation for the Mean Workload in a GI/G/1 Queue",
     ["Whitt"], None, None),
    ("queueing-theory",
     "Refining Diffusion Approximations for Queues", ["Whitt"], None, None),
    ("queueing-theory",
     "The theory of queues with a single server", ["Lindley"], None,
     "10.1017/S0305004100027638"),
    ("queueing-theory",
     "Jobshop-Like Queueing Systems", ["Jackson"], None, "10.1287/mnsc.10.1.131"),
    ("queueing-theory",
     "Open and Closed Models for Networks of Queues", ["Whitt"], None, None),
    ("queueing-theory",
     "Open, Closed, and Mixed Networks of Queues with Different Classes of "
     "Customers", ["Baskett", "Chandy", "Muntz", "Palacios"], None,
     "10.1145/321879.321887"),
    ("queueing-theory",
     "The Heavy-Traffic Bottleneck Phenomenon in Open Queueing Networks",
     ["Suresh", "Whitt"], None, None),
    # The infinite-server model is the one concept the audit found *absent*,
    # and it is exactly what recommendation 6 proposes using.
    ("queueing-theory",
     "A New View of the Heavy-Traffic Limit for Infinite-Server Queues",
     ["Whitt"], None, None),
    ("queueing-theory",
     "Two-Parameter Heavy-Traffic Limits for Infinite-Server Queues",
     ["Pang", "Whitt"], None, None),
    ("queueing-theory",
     "Networks of Infinite-Server Queues with Nonstationary Poisson Input",
     ["Massey", "Whitt"], None, None),
    ("queueing-theory",
     "Infinite-Server Queues with Batch Arrivals and Dependent Service Times",
     ["Pang", "Whitt"], None, None),
    # "No process is in steady state" is a queueing-theory claim with a
    # queueing-theory literature behind it.
    ("queueing-theory",
     "The Asymptotic Behavior of Queues with Time-Varying Arrival Rates",
     ["Newell", "Whitt"], None, None),
    ("queueing-theory",
     "Server Staffing to Meet Time-Varying Demand",
     ["Jennings", "Mandelbaum", "Massey", "Whitt"], None, None),
    ("queueing-theory",
     "Coping with Time-Varying Demand when Setting Staffing Requirements for a "
     "Service System", ["Green", "Kolesar", "Whitt"], None, None),
    ("queueing-theory",
     "What You Should Know About Queueing Models to Set Staffing Requirements "
     "in Service Systems", ["Whitt"], None, None),
    ("queueing-theory",
     "Are Call Center and Hospital Arrivals Well Modeled by Nonhomogeneous "
     "Poisson Processes?", ["Kim", "Whitt"], None, None),
    ("queueing-theory",
     "Fluid Models for Multiserver Queues with Abandonments",
     ["Whitt"], None, "10.1287/opre.1050.0227"),
    ("queueing-theory",
     "Efficiency-Driven Heavy-Traffic Approximations for Many-Server Queues "
     "with Abandonments", ["Whitt"], None, None),
    ("queueing-theory",
     "Engineering Solution of a Basic Call-Center Model",
     ["Whitt"], None, "10.1287/mnsc.1040.0302"),
    ("queueing-theory",
     "The Erlang B and C Formulas: Problems and Solutions", ["Whitt"], None, None),
    ("queueing-theory",
     "Sensitivity of Performance in the Erlang A Model to Changes in the Model "
     "Parameters", ["Whitt"], None, None),
    ("queueing-theory",
     "Explicit M/G/1 Waiting-Time Distributions for a Class of Long-Tail "
     "Service-Time Distributions", ["Abate", "Whitt"], None, None),
    ("queueing-theory",
     "Telephone Call Centers: Tutorial, Review, and Research Prospects",
     ["Gans", "Koole", "Mandelbaum"], None, "10.1287/msom.5.2.79.16071"),
    ("queueing-theory",
     "Evaluating the Fit of the Erlang A Model in High Traffic Call Centers",
     ["Bassamboo", "Ibrahim"], None, None),
    # --- 2d. Discrete-event simulation methodology -------------------------
    # These are all Winter Simulation Conference papers, which is the point:
    # the journal versions (JORS, J. Simulation, Management Science) are
    # paywalled while WSC has published its whole proceedings free since 1968,
    # and for tutorials the WSC paper *is* the canonical statement.
    ("des-methodology",
     "A History of Discrete Event Simulation Programming Languages",
     ["Nance"], "https://eprints.cs.vt.edu/archive/00000363/01/TR-93-21.pdf",
     "10.1145/234286.1057822"),
    ("des-methodology",
     "The History of Simulation Modeling", ["Nance", "Sargent"], None, None),
    ("des-methodology",
     "A Brief History of Simulation", ["Goldsman", "Nance", "Wilson"], None, None),
    ("des-methodology",
     "SIMULA: an ALGOL-based simulation language",
     ["Dahl", "Nygaard"], None, "10.1145/365813.365819"),
    ("des-methodology",
     "The SIMSCRIPT III Programming Language for Modular Object-Oriented "
     "Simulation", ["Rice", "Markowitz", "Marjanski", "Bailey"], None, None),
    ("des-methodology",
     "GPSS 50 Years Old, but Still Young", ["Ståhl", "Henriksen", "Born",
     "Herper"], None, None),
    ("des-methodology",
     "GPSS/H: A 23-Year Retrospective View", ["Henriksen"], None, None),
    ("des-methodology",
     "SimPy: Discrete Event Simulation for Python", ["Matloff"],
     "https://heather.cs.ucdavis.edu/~matloff/156/PLN/DESimIntro.pdf", None),
    ("des-methodology",
     "Verification and Validation of Simulation Models", ["Sargent"], None, None),
    ("des-methodology",
     "Verification and Validation of Simulation Models: An Advanced Tutorial",
     ["Sargent"], None, None),
    ("des-methodology",
     "History of Verification and Validation of Simulation Models",
     ["Sargent", "Balci"], None, None),
    ("des-methodology",
     "A Concise History of Simulation Output Analysis", ["Alexopoulos",
     "Goldsman", "Wilson"], None, None),
    ("des-methodology",
     "Simulation Output Analysis: A Tutorial Based on One Research Thread",
     ["Wilson"], None, None),
    ("des-methodology",
     "Automating D.E.S. Output Analysis: How Many Replications to Run",
     ["Hoad", "Robinson", "Davies"], None, None),
    ("des-methodology",
     "The Initial Transient in Steady-State Point Estimation: Contexts, A "
     "Bibliography, The MSE Criterion, and The MSER Statistic",
     ["Mahajan", "Ingalls"], None, None),
    ("des-methodology",
     "Automating Warm-Up Length Estimation", ["Hoad", "Robinson", "Davies"],
     None, None),
    ("des-methodology",
     "A Statistical Process Control Approach for Estimating the Warm-Up Period",
     ["Robinson"], None, None),
    ("des-methodology",
     "Comparing Two Systems: Beyond Common Random Numbers", ["Chick",
     "Inoue"], None, None),
    ("des-methodology",
     "A Tutorial on Conceptual Modeling for Simulation", ["Robinson"], None, None),
    ("des-methodology",
     "Conceptual Modeling: Definition, Purpose and Benefits", ["Robinson"],
     None, None),
    ("des-methodology",
     "Conceptual Modelling: Knowledge Acquisition and Model Abstraction",
     ["Robinson"], None, None),
    ("des-methodology",
     "Tutorial: Choosing what to Model - Conceptual Modeling for Simulation",
     ["Robinson"], None, None),
    ("des-methodology",
     "Non-Uniform Random Variate Generation", ["Devroye"], None, None),
    ("des-methodology",
     "History of Random Variate Generation", ["L'Ecuyer"], None, None),
    ("des-methodology",
     "History of Input Modeling", ["Biller", "Gunes Corlu"], None, None),
    ("des-methodology",
     "Introduction to Simulation Input Modeling", ["Biller", "Gunes"], None, None),
    ("des-methodology",
     "Introduction to Simulation", ["Goldsman", "Goldsman"], None, None),
    ("des-methodology",
     "Discrete-Event Simulation of Queues with Spreadsheets: A Teaching Case",
     ["Ingolfsson", "Grossman"], None, None),
    # --- 2e. Hybrid / system-dynamics / agent-based ------------------------
    ("hybrid-simulation",
     "A Primer for System Dynamics Modeling and Simulation", ["Sterman"],
     None, None),
    ("hybrid-simulation",
     "System Dynamics: a Behavioral Modeling Method", ["Pruyt"], None, None),
    ("hybrid-simulation",
     "Hybrid simulation modelling in operational research: A state-of-the-art review",
     ["Brailsford", "Eldabi", "Kunc", "Mustafee", "Osorio"], None,
     "10.1016/j.ejor.2018.10.025"),
    ("hybrid-simulation",
     "Discrete-Event and Agent-Based Simulation and Where to Use Each",
     ["Siebers", "Macal"], None, None),
    ("hybrid-simulation",
     "How Agent-Based Modeling Can Benefit Your System Dynamic and Discrete "
     "Event Models", ["Borshchev"], None, None),
    ("hybrid-simulation",
     "Agent-based modeling: Methods and techniques for simulating human systems",
     ["Bonabeau"], "https://europepmc.org/articles/PMC128598?pdf=render",
     "10.1073/pnas.082080899"),
    ("hybrid-simulation",
     "Tutorial on Agent-Based Modeling and Simulation", ["Macal", "North"],
     None, None),
    ("hybrid-simulation",
     "Agent-Based Modeling: An Introduction and Primer", ["Macal"], None, None),
    ("hybrid-simulation",
     "Introductory Tutorial: Agent-Based Modeling and Simulation",
     ["Macal", "North"], None, None),
    ("hybrid-simulation",
     "AgentSimulator: An Agent-based Approach for Data-driven Business Process "
     "Simulation", ["Kirchdorfer", "Blumel", "Ruppert", "Fettke"], None, None),
    # --- 2f. Short-term simulation / operational decision support ----------
    ("short-term-simulation",
     "Short-term simulation: bridging the gap between operational support and "
     "strategic decision making", ["van der Aalst", "Nakatumba", "Rozinat",
     "Russell"], None, None),
    ("short-term-simulation",
     "Process Mining and Simulation: A Match Made in Heaven!",
     ["van der Aalst"], None, None),
    ("short-term-simulation",
     "Predictive Business Process Monitoring with LSTM Neural Networks",
     ["Tax", "Verenich", "La Rosa", "Dumas"], None, None),
    ("short-term-simulation",
     "Survey and cross-benchmark comparison of remaining time prediction "
     "methods in business process monitoring",
     ["Verenich", "Dumas", "La Rosa", "Maggi", "Teinemaa"], None, None),
    ("short-term-simulation",
     "Prescriptive Process Monitoring: Quo Vadis?",
     ["Kubrak", "Milani", "Nolte", "Dumas"], None, None),
    ("short-term-simulation",
     "Digital Twin Paradigm: A Systematic Literature Review",
     ["Semeraro", "Lezoche", "Panetto", "Dassisti"], None,
     "10.1016/j.compind.2021.103469"),
    # --- 2g. Simulation-model quality and comparative process mining -------
    ("bps-evaluation",
     "Can I Trust My Simulation Model? Measuring the Quality of Business "
     "Process Simulation Models",
     ["Chapela-Campa", "Benchekroun", "Baron", "Dumas"], None, None),
    ("bps-evaluation",
     "Enhancing Business Process Simulation Models with Extraneous Activity "
     "Delays", ["Chapela-Campa", "Dumas"], None, None),
    ("bps-evaluation",
     "Business Process Variant Analysis: Survey and Classification",
     ["Taymouri", "La Rosa", "Dumas"], "https://arxiv.org/pdf/1911.07582v2",
     None),
    ("bps-evaluation",
     "Detecting Drift from Event Streams of Unpredictable Business Processes",
     ["Ostovar", "Maaradji", "La Rosa", "ter Hofstede", "van Dongen"], None,
     "10.1007/978-3-319-46397-1_26"),
    ("bps-evaluation",
     "Statistical Tests and Association Measures for Business Processes",
     ["Bolt", "de Leoni", "van der Aalst"], None,
     "10.1109/TKDE.2017.2764465"),
    ("bps-evaluation",
     "Process Variant Comparison: Using Event Logs to Detect Differences in "
     "Behavior and Business Rules", ["Bolt", "van der Aalst", "de Leoni"], None,
     "10.1016/j.is.2017.12.006"),
]


# --------------------------------------------------------------------------
# 3. His own publications page, scanned rather than enumerated.
# --------------------------------------------------------------------------
# Deliberately narrow. "Simulation" as a bare word appears in venue names
# ("Systems Analysis - Modelling - Simulation", "European Simulation
# Multiconference") attached to papers about workflow verification, so the venue
# tail of each citation is cut off before matching and the terms below are the
# ones that name the subject rather than the room it was presented in.
OWN_TERMS = re.compile(
    r"simulat|queue|queueing|queuing|discrete[- ]event|system dynamics|"
    r"digital twin|short[- ]term simulation|handboek", re.I)

# Citations whose *subject* is something else entirely; the term above only
# matches their venue or a passing phrase.
OWN_SKIP = re.compile(
    r"Reachable Dead States|Message Sequence Charts|Woflan:|Browsing Semantics|"
    r"Tower Model|Integrated systems modelling", re.I)


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
# van der Aalst's own publications page as a first-class resolver
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r'<a\s[^>]*href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>',
                      re.I | re.S)


def vdaalst_index(sess) -> list[dict]:
    """Every linked PDF on the publications page, with its title and citation.

    The page's markup is regular in the one way that matters: the **anchor text
    is the title** and everything before it is the author list, so titles come
    out exactly rather than by cutting a citation string at a full stop. Some
    entries link twice (entry 30 offers `Handboek simulatie` and its English
    `Simulation Handbook`); both are kept, because they are different documents.

    His site is also the only place several of the slide references exist at all
    — DBLP knows the 1990 European Simulation Multiconference citation and no OA
    backend has the file.
    """
    try:
        html = sess.get(VDAALST_PUBS, timeout=90).text
    except Exception as exc:  # noqa: BLE001
        print(f"  [vdaalst] page unreachable ({type(exc).__name__}); skipping")
        return []
    import requests
    entries: list[dict] = []
    for body in re.split(r"<dt>", html)[1:]:
        eid = re.match(r"\s*(\w+)\s*</dt>", body)
        links = _LINK_RE.findall(body)
        if not links:
            continue
        citation = pf.clean(body)
        head = pf.clean(body[:body.lower().index("<a ")]) if "<a " in body.lower() else ""
        authors = [a.strip() for a in re.split(r",| and ", re.sub(r"^\s*\w+\s*", "", head))
                   if a.strip() and a.strip() != "."]
        for href, anchor in links:
            title = pf.clean(anchor).strip(" .")
            if len(title) < 6:
                continue
            entries.append({
                "id": eid.group(1) if eid else "",
                "title": title,
                "authors": authors,
                "citation": citation,
                "url": requests.compat.urljoin(VDAALST_PUBS, href),
            })
    print(f"  [vdaalst] {len(entries)} linked PDFs on the publications page")
    return entries


def vdaalst_match(entries: list[dict], title: str) -> str | None:
    """Best own-site PDF for a title: exact normalised title, else containment.

    Containment needs a length guard, and the reason is concrete. Slide
    reference 18 is the *Modern Business Process Automation* chapter "Process
    Mining and Simulation", which his page lists without a PDF; its title is a
    prefix of "Process Mining and Simulation: A Match Made in Heaven!", which
    does have one. Unguarded containment silently returns the wrong paper —
    byte-identical to the copy fetched for reference 11 — and reports it as a
    hit. A candidate is therefore only accepted if it is barely longer than what
    was asked for, which admits a subtitle and rejects a different paper.
    """
    want = pf.norm(title)
    if len(want) < 12:
        return None
    for e in entries:
        if pf.norm(e["title"]) == want:
            return e["url"]
    limit = len(want) * 1.15 + 8
    best, best_len = None, 0.0
    for e in entries:
        hay = pf.norm(e["title"])
        if want in hay and len(hay) <= limit and (best is None or len(hay) < best_len):
            best, best_len = e["url"], len(hay)
    return best


# ---------------------------------------------------------------------------
# Two more self-hosted archives, for the two themes no OA backend could serve
# ---------------------------------------------------------------------------
# Why these two and not a smarter resolver: the DES-methodology and
# queueing-theory works below are *published* by INFORMS, Cambridge, Palgrave
# and Wiley, so Unpaywall reports them closed and arXiv has never heard of
# them — yet the Winter Simulation Conference has put its entire proceedings
# online for free since 1968, and Ward Whitt self-hosts essentially his whole
# bibliography. Both are title-indexed HTML pages, which is the same shape as
# van der Aalst's publications page and needs the same treatment: build
# title → PDF once, then look titles up.

_WSC_TITLE_RE = re.compile(
    r'<div\s+class="slot-title"\s*>(.*?)</div>'
    r'|<div\s+class="session-title"\s*>(.*?)</div>'
    r'|<i>(.*?)</i>|<I>(.*?)</I>|<em>(.*?)</em>', re.S)


def wsc_index(sess, since: int = 1990) -> list[dict]:
    """Title → PDF for the free Winter Simulation Conference archive.

    Every WSC paper since 1968 is open at informs-sim.org, which is where the
    canonical tutorials on output analysis, warm-up, verification & validation,
    conceptual modelling and agent-based simulation actually live — the journal
    versions of the same material are paywalled.

    Two page generations have to be read. Up to 2011 a paper is
    ``<I>Title</I><BR>authors<br><a href="…PDF">Full paper</a>``; from 2012 it
    is ``<div class="slot-title">Title</div>…<a href="…pdf">pdf</a>``, with
    ``session-title`` standing in when a session holds a single paper. Since the
    PDF link carries no title in either generation, each link is attributed to
    the **nearest preceding title element**, whichever of those forms it takes.
    """
    try:
        html = sess.get(WSC_ARCHIVE, timeout=60).text
    except Exception as exc:  # noqa: BLE001
        print(f"  [wsc] archive unreachable ({type(exc).__name__}); skipping")
        return []
    import requests
    # The year comes from the path (`/wsc98papers/…`, `/wsc25papers/…`) rather
    # than the link text, which is wrapped in markup and inconsistently spaced.
    years: dict[int, str] = {}
    for href, yy in re.findall(r'href=["\']([^"\']*wsc(\d{2})papers[^"\']*\.html?)["\']',
                               html, re.I):
        year = 1900 + int(yy) if int(yy) >= 60 else 2000 + int(yy)
        if year >= since:
            years.setdefault(year, requests.compat.urljoin(WSC_ARCHIVE, href))
    years_list = sorted(years.items(), reverse=True)
    out: list[dict] = []
    for year, url in years_list:
        try:
            page = sess.get(url, timeout=90).text
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+\.pdf)["\']', page, re.I):
            titles = [pf.clean(g) for t in _WSC_TITLE_RE.finditer(page, 0, m.start())
                      for g in t.groups() if g]
            if not titles:
                continue
            title = titles[-1].strip(" .")
            if len(title) < 12:
                continue
            out.append({"title": title, "year": year,
                        "url": requests.compat.urljoin(url, m.group(1))})
    print(f"  [wsc] {len(out)} papers indexed from {len(years_list)} WSC proceedings")
    return out


def whitt_index(sess) -> list[dict]:
    """Title → PDF for Ward Whitt's self-hosted bibliography.

    His page is one long ``<li>`` list in which the title is the bolded run and
    the file is the first ``.pdf`` link in the same item, so per-item parsing is
    exact rather than positional.
    """
    try:
        html = sess.get(WHITT_PUBS, timeout=90).text
    except Exception as exc:  # noqa: BLE001
        print(f"  [whitt] page unreachable ({type(exc).__name__}); skipping")
        return []
    import requests
    out: list[dict] = []
    for item in re.split(r"<li>|<LI>", html)[1:]:
        tm = re.search(r"<b>(.*?)</b>", item, re.S | re.I)
        um = re.search(r'href=["\']([^"\']+\.pdf)["\']', item, re.I)
        if not tm or not um:
            continue
        title = pf.clean(tm.group(1)).strip(" .")
        if len(title) < 12:
            continue
        out.append({"title": title,
                    "url": requests.compat.urljoin(WHITT_PUBS, um.group(1))})
    print(f"  [whitt] {len(out)} papers indexed from his publications page")
    return out


def index_match(entries: list[dict], title: str, cutoff: float = 0.90) -> str | None:
    """Best PDF in a title-indexed archive, by fuzzy title agreement.

    Exact normalised equality first; then a high-cutoff similarity ratio, which
    is what absorbs the difference between a WSC tutorial's title and the way it
    is cited ("An Introduction to Verification and Validation of Simulation
    Models" vs "Verification and validation of simulation models"). Containment
    is allowed in either direction for the same reason, but only when the two
    titles are within a quarter of each other in length, so a short title cannot
    match an unrelated longer one that happens to embed it.
    """
    want = pf.norm(title)
    if len(want) < 12:
        return None
    best, best_score = None, 0.0
    for e in entries:
        hay = pf.norm(e["title"])
        if hay == want:
            return e["url"]
        ratio = difflib.SequenceMatcher(None, want, hay).ratio()
        if (want in hay or hay in want) and min(len(want), len(hay)) / max(len(want), len(hay)) > 0.75:
            ratio = max(ratio, 0.95)
        if ratio >= cutoff and ratio > best_score:
            best, best_score = e["url"], ratio
    return best


def own_papers(entries: list[dict]) -> list[Paper]:
    """The simulation/queue subset of his own self-hosted output."""
    out: list[Paper] = []
    seen: set[str] = set()
    for e in entries:
        if not OWN_TERMS.search(e["title"]) or OWN_SKIP.search(e["title"]):
            continue
        key = pf.norm(e["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(("vdaalst-own", e["title"], e["authors"], e["url"], None))
    return out


class Archives:
    """The three title-indexed archives, built lazily on first miss.

    WSC costs ~35 page fetches, so it is not paid for unless a title actually
    fails the cheap resolvers.
    """

    def __init__(self, sess):
        self.sess = sess
        self.vdaalst = vdaalst_index(sess)
        self._wsc: list[dict] | None = None
        self._whitt: list[dict] | None = None

    @property
    def wsc(self) -> list[dict]:
        if self._wsc is None:
            self._wsc = wsc_index(self.sess)
        return self._wsc

    @property
    def whitt(self) -> list[dict]:
        if self._whitt is None:
            self._whitt = whitt_index(self.sess)
        return self._whitt


def resolve(sess, arc: Archives, title: str, authors: list[str],
            url: str | None, doi: str | None) -> tuple[str | None, str]:
    if url:
        return url, "override"
    own = vdaalst_match(arc.vdaalst, title)
    if own:
        return own, "vdaalst.com"
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
    for entries, how in ((arc.whitt, "columbia.edu/~ww2040"),
                         (arc.wsc, "informs-sim.org")):
        got = index_match(entries, title)
        if got:
            return got, how
    # Last resort: DBLP may know an `ee` that is a direct open PDF.
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
    return None, "unresolved"


def run(what: str, dry_run: bool, skip_held: bool) -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    arc = Archives(sess)
    papers: list[Paper] = []
    if what in ("slides", "all"):
        papers += SLIDE_REFS
    if what in ("gaps", "all"):
        papers += GAP_PAPERS
    if what in ("own", "all"):
        own = own_papers(arc.vdaalst)
        print(f"  [vdaalst] {len(own)} simulation/queue entries on his own page")
        papers += own

    dedup = pf.IndexDedup() if skip_held else None
    state = load_state()
    rows: list[dict] = []

    for topic, title, authors, url, doi in papers:
        key = pf.norm(title)
        prev = state["done"].get(key)
        if prev and prev.get("status") == "downloaded" and Path(ROOT / prev["file"]).exists():
            print(f"[{'cached':>22}] {title[:74]}")
            rows.append(prev)
            continue
        if dedup and dedup.contains(title):
            row = {"topic": topic, "title": title, "how": "held",
                   "url": "", "status": "already-in-library", "file": ""}
            print(f"[{'already in library':>22}] {title[:74]}")
            rows.append(row)
            state["done"][key] = row
            continue

        found, how = resolve(sess, arc, title, authors, url, doi)
        status, dest = ("no-open-copy" if not found else "pending"), ""
        if found and dry_run:
            status = "would-download"
        elif found:
            stem = pf.safe_stem(authors, title)
            path = OUT / f"{stem}.pdf"
            ok, detail = pf.download_pdf(sess, found, path)
            status = "downloaded" if ok else f"failed: {detail}"
            dest = str(path.relative_to(ROOT)) if ok else ""
        print(f"[{status:>22}] ({how}) {title[:70]}")
        row = {"topic": topic, "title": title, "how": how,
               "url": found or "", "status": status, "file": dest}
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
                   choices=["slides", "gaps", "own", "all"])
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
