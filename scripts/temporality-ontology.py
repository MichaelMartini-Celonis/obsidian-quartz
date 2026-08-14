#!/usr/bin/env python3
"""Harvester for the **temporality & ontology** gap: 3D/endurantism vs 4D/perdurantism.

`scripts/gap-audit.py --topic temporality-ontology` found that the library holds
the *data-engineering* answer to "does a thing stay the same thing through
change?" in depth (Anchor Modeling, bitemporal relational theory, Snodgrass,
object-centric event data) while the two traditions that actually argue the
question were absent:

  * **analytic metaphysics of persistence** — endurantism/perdurantism, temporal
    parts, McTaggart, presentism/eternalism: the vocabulary appeared in exactly
    one document (a blog post) and nowhere else;
  * **industrial 4D engineering** — ISO 15926, HQDM, BORO, IDEAS and the UK
    Information Management Framework: *zero* documents, even though this is
    where perdurantism actually shipped into lifecycle and configuration
    management;
  * **process philosophy** — Heraclitus, Whitehead, Bergson, Heidegger appeared
    only as decorative epigraphs ("everything flows") in database blog posts.

This script fetches an explicitly curated bibliography for those gaps. Unlike the
venue scrapers (`icde-arxiv.py`, `tum-bpm.py`, …) there is no listing page to
crawl: philosophy and engineering-standards material is scattered across author
homepages, institutional repositories, Project Gutenberg and government report
sites. So the reading list is **declared** in ``WORKS`` below, each entry with a
verified direct URL where one exists, and metadata-only otherwise so the shared
resolvers (OpenAlex -> Unpaywall -> arXiv) can try to find an open copy.

Encyclopedia articles (Stanford/Internet Encyclopedia of Philosophy) are *not*
handled here — they are registered as `Philosophy` collections in
``scripts/import-docs.py``, which already knows how to turn HTML doc sites into
consolidated markdown.

A **second round** (sections ``interval-algebra``, ``historization``,
``event-sourcing``, ``kg-versioning``) closes the five concepts the audit still
rated `thin` after the first round: the library discussed Allen relations,
slowly-changing dimensions, event sourcing and graph versioning without holding
a work about any of them. That round is mostly CS literature, so entries are
largely metadata-only — DBLP/arXiv/OpenAlex resolve those far better than the
philosophy material, where hand-verified URLs were necessary.

Downloads land in ``Inbox/temporality/<section>/``, from where
``import-downloads.py`` files them into ``Literature/`` and the indexer picks
them up. Resumable via a JSON checkpoint; writes a CSV report.

Pipeline:
  1. gather   - load the declared bibliography; flag works already in the index.
  2. resolve  - for entries without a direct URL, look for an open copy.
  3. download - fetch everything resolved.

Usage:
  scripts/.venv/bin/python scripts/temporality-ontology.py all
  scripts/.venv/bin/python scripts/temporality-ontology.py gather
  scripts/.venv/bin/python scripts/temporality-ontology.py resolve
  scripts/.venv/bin/python scripts/temporality-ontology.py download --limit 20
  scripts/.venv/bin/python scripts/temporality-ontology.py list --section imf
  scripts/.venv/bin/python scripts/temporality-ontology.py report
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "temporality"
CKPT = OUT_DIR / "_temporality.json"
REPORT = OUT_DIR / "_temporality-report.csv"
DL_SLEEP = 0.7
RESOLVE_SLEEP = 0.4

# Magic-byte / content-type expectations per file kind, so a Cloudflare
# challenge page never lands in the library masquerading as a paper.
KINDS = {
    "pdf": (b"%PDF", "pdf"),
    "epub": (b"PK", "epub"),
    "txt": (b"", "text"),
}


@dataclass
class Work:
    section: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    url: str = ""                 # verified direct URL; "" => resolve by metadata
    kind: str = "pdf"             # pdf | epub | txt
    doi: str = ""
    note: str = ""
    # runtime state
    in_index: bool | None = None
    pdf_url: str | None = None
    source: str | None = None
    status: str = "pending"


# ---------------------------------------------------------------------------
# The reading list.
#
# Sections mirror the themes in scripts/gap-topics.json. URLs marked "verified"
# returned HTTP 200 with the expected content type when this list was compiled;
# entries with url="" are deliberately metadata-only for the resolvers to chase.
# ---------------------------------------------------------------------------

WORKS: list[Work] = [

    # === Analytic metaphysics of persistence =================================
    # The literature the 3D/4D vocabulary actually comes from. Sider's and
    # Hawley's monographs are paywalled; the open journal articles carry the
    # same arguments.
    Work("persistence", "Four-Dimensionalism", ["Theodore Sider"], 1997,
         "https://www.tedsider.org/papers/4d.pdf",
         note="Philosophical Review; open precis of the 2001 monograph's core argument"),
    Work("persistence", "All the World's a Stage", ["Theodore Sider"], 1996,
         "https://www.tedsider.org/papers/all_the_worlds_a_stage.pdf",
         note="Founding paper of stage theory / exdurantism"),
    Work("persistence", "The Stage View and Temporary Intrinsics",
         ["Theodore Sider"], 2000,
         "https://www.tedsider.org/papers/stages_and_intrinsics.pdf"),
    Work("persistence", "Parthood and Identity Across Time",
         ["Judith Jarvis Thomson"], 1983,
         "https://metaphysicist.com/articles/Thomson_Parthood.pdf",
         note="The classic endurantist attack on temporal parts"),
    Work("persistence", "Endurance and Temporary Intrinsics", ["Sally Haslanger"], 1989,
         "http://sallyhaslanger.weebly.com/uploads/1/8/2/7/18272031/"
         "haslanger_1989_endurance_temporary_intrinsics.pdf",
         note="States the problem of temporary intrinsics that motivates 4D"),
    Work("persistence", "Persistence, Change, and Explanation", ["Sally Haslanger"], 1989,
         "https://sallyhaslanger.weebly.com/uploads/1/8/2/7/18272031/"
         "haslanger_1989_persistence_change_explanation.pdf"),
    Work("persistence", "Rearrangement of Particles: Reply to Lowe",
         ["David Lewis"], 1988,
         "https://metaphysicist.com/articles/Lewis_Reply_to_Lowe.pdf",
         note="Lewis on intrinsic change and persistence"),
    Work("persistence", "The Unreality of Time", ["John Ellis McTaggart"], 1908,
         "https://zenodo.org/records/1431815/files/article.pdf?download=1",
         note="Origin of the A-series / B-series distinction; public domain"),
    Work("persistence", "From a Logical Point of View",
         ["Willard Van Orman Quine"], 1953,
         "https://archive.org/download/FromALogicalPointOfView/"
         "QuineFromALogicalPointOfViewText.pdf",
         note="Contains 'Identity, Ostension, and Hypostasis' (ch. 4)"),
    # Metadata-only: let the resolvers look for open copies.
    Work("persistence", "How Things Persist", ["Katherine Hawley"], 2001, "",
         note="OUP monograph; likely no open copy — resolver will confirm"),
    Work("persistence", "Temporal Parts Unmotivated", ["Judith Jarvis Thomson"], 1983, ""),
    Work("persistence", "Identity, Ostension, and Hypostasis",
         ["Willard Van Orman Quine"], 1950, ""),

    # === Process philosophy =================================================
    # Public-domain primary sources plus open secondary scholarship. The library
    # quotes Heraclitus as an epigraph in four database texts and holds nothing.
    Work("process-philosophy", "The Concept of Nature",
         ["Alfred North Whitehead"], 1920,
         "https://www.gutenberg.org/cache/epub/18835/pg18835.epub", kind="epub",
         note="Whitehead's events-first metaphysics of nature; public domain"),
    Work("process-philosophy", "Science and the Modern World",
         ["Alfred North Whitehead"], 1925,
         "https://archive.org/download/in.ernet.dli.2015.17780/"
         "2015.17780.Science-And-The-Modern-World_text.pdf"),
    Work("process-philosophy", "Time and Free Will", ["Henri Bergson"], 1910,
         "https://www.gutenberg.org/cache/epub/56852/pg56852.epub", kind="epub",
         note="Bergson on duration vs spatialised time; public domain"),
    Work("process-philosophy", "Creative Evolution", ["Henri Bergson"], 1911,
         "https://www.gutenberg.org/cache/epub/26163/pg26163.epub", kind="epub"),
    Work("process-philosophy", "Matter and Memory", ["Henri Bergson"], 1911,
         "https://archive.org/download/matterandmemory00berguoft/"
         "matterandmemory00berguoft.pdf"),
    Work("process-philosophy", "Temporality (Heidegger's Being and Time)",
         ["William Blattner"], 2005,
         "https://faculty.georgetown.edu/blattnew/topics/docs/temporality.pdf",
         note="Open scholarly treatment of Heideggerian temporality; "
              "Being and Time itself is in copyright"),

    # === Industrial 4D: the UK Information Management Framework =============
    # The largest and most surprising hole: an entire engineering tradition that
    # adopted perdurantism for lifecycle data integration. These CDBB reports
    # explicitly survey top-level ontologies and choose the 4D ones.
    Work("imf", "A Survey of Top-Level Ontologies",
         ["Chris Partridge", "Andrew Mitchell", "Al Cook", "Jan Sullivan",
          "Matthew West"], 2020,
         "https://www.cdbb.cam.ac.uk/files/a_survey_of_top-level_ontologies_lowres.pdf",
         note="Classifies 36 upper ontologies by 3D/4D commitment — the single "
              "most direct answer to the 3D-vs-4D modelling question"),
    Work("imf", "The Approach to Develop the Foundation Data Model for the "
                "Information Management Framework",
         ["Matthew West"], 2021,
         "https://www.cdbb.cam.ac.uk/files/250221_the_choice_of_start_point_for_"
         "the_foundation_data_model_for_the_information_management_framework_1.pdf",
         note="Selects BORO, IDEAS, HQDM and ISO 15926-2 — all 4D"),
    Work("imf", "The Pathway Towards an Information Management Framework: "
                "A Commons for a Digital Built Britain",
         ["James Hetherington", "Matthew West"], 2020,
         "https://www.cdbb.cam.ac.uk/files/the_pathway_towards_an_imf.pdf"),
    Work("imf", "A Survey of Industry Data Models and Reference Data Libraries",
         ["David Leal", "Al Cook", "Chris Partridge", "Jan Sullivan",
          "Matthew West"], 2020,
         "https://www.cdbb.cam.ac.uk/files/"
         "industry_data_models_and_reference_data_libraries_0.pdf"),
    Work("imf", "A Framework for Composition: A Step Towards a Foundation for Assembly",
         ["Chris Partridge"], 2021,
         "https://www.cdbb.cam.ac.uk/files/"
         "a_framework_for_compositiona_step_towards_a_foundation_for_assembly_final.pdf",
         note="Mereology/composition for built assets on a 4D base"),
    Work("imf", "National Digital Twin: Integration Architecture Pattern and Principles",
         ["National Digital Twin Programme"], 2021,
         "https://www.cdbb.cam.ac.uk/files/architecture_principles_final.pdf"),
    Work("imf", "The Gemini Principles", ["Digital Framework Task Group"], 2018,
         "https://www.cdbb.cam.ac.uk/system/files/documents/TheGeminiPrinciples.pdf"),
    Work("imf", "The Approach to Delivering a National Digital Twin for the "
                "United Kingdom", ["CDBB"], 2020,
         "https://www.cdbb.cam.ac.uk/files/approach_summaryreport_final.pdf"),
    Work("imf", "Summary of Responses to the Pathway towards an Information "
                "Management Framework Consultation", ["CDBB"], 2021,
         "https://www.cdbb.cam.ac.uk/files/imf_consultation_summary_11032021.pdf"),
    Work("imf", "An Integrated Approach to Information Management: Process Model",
         ["CDBB"], 2021,
         "https://www.cdbb.cam.ac.uk/files/process_model.pdf"),

    # === 4D ontology in engineering practice: BORO / HQDM / ISO 15926 =======
    Work("industrial-4d", "Exploiting a Perdurantist Foundational Ontology for "
                          "Data Integration (4D-SETL)",
         ["Chris Partridge"], 2016,
         "https://bura.brunel.ac.uk/bitstream/2438/12053/1/FulltextThesis.pdf",
         note="PhD thesis connecting perdurantism directly to graph databases "
              "and ETL — the missing bridge between metaphysics and data work"),
    Work("industrial-4d", "Enterprise Data Modelling: Developing an Ontology-Based "
                          "Framework for the Shell Downstream Business",
         ["Matthew West", "Chris Partridge", "Mark Lycett"], 2006,
         "https://www.loa.istc.cnr.it/old/Files/Presentations/West.pdf",
         note="4D + extensionalism applied to a production enterprise data model"),
    Work("industrial-4d", "Ontology Meets Business: Applying Ontology to the "
                          "Development of Business Information Systems",
         ["Matthew West"], 2009,
         "https://framework.sysfeat.com/resources/external-references/"
         "Matthew-West-2009_Ontology-meets-business.pdf",
         note="4D spatio-temporal extents in enterprise modelling"),
    Work("industrial-4d", "Some Industrial Experiences in the Development and "
                          "Use of Ontologies", ["Matthew West"], 2004,
         "https://ceur-ws.org/Vol-118/paper1.pdf",
         note="How Partridge's 4D approach became ISO 15926-2"),
    Work("industrial-4d", "Developing High Quality Data Models: Front Matter",
         ["Matthew West"], 2011,
         "https://booksite.elsevier.com/samplechapters/9780123751065/"
         "01~Front_Matter.pdf",
         note="Only openly published portion of the HQDM book; records the "
              "EPISTLE / ISO 15926 / BORO lineage"),
    Work("industrial-4d", "ISO 15926-1:2004 Industrial automation systems and "
                          "integration: Overview and fundamental principles",
         ["ISO TC184/SC4"], 2004,
         "https://cdn.standards.iteh.ai/samples/29556/"
         "6932f57444354195b80d4fa65591ac62/ISO-15926-1-2004.pdf",
         note="Official open preview sample, not the full standard"),
    Work("industrial-4d", "ISO 15926-2:2003 Industrial automation systems and "
                          "integration: Data model",
         ["ISO TC184/SC4"], 2003,
         "https://cdn.standards.iteh.ai/samples/29557/"
         "8aecccd3564f4f3da94b71eb4427e503/ISO-15926-2-2003.pdf",
         note="Official open preview of the 4D data model itself"),
    Work("industrial-4d", "ISO 15926 and Autodesk", ["Autodesk"], 2013,
         "https://damassets.autodesk.net/content/dam/autodesk/files/"
         "1375383519-autodesk_iso_15926_whitepaper(1).pdf"),
    Work("industrial-4d", "Grounding for Ontological Architecture Quality: "
                          "Metaphysical Choices",
         ["Chris Partridge", "Sergio de Cesare"], 2016,
         "https://bura.brunel.ac.uk/bitstream/2438/15110/1/99750002.pdf",
         note="Argues the metaphysical choice (3D vs 4D) *is* an architecture "
              "quality decision — the crux of the question"),
    Work("industrial-4d", "Formalization of the Classification Pattern: Survey of "
                          "Classification Modeling in Information Systems Engineering",
         ["Chris Partridge", "Sergio de Cesare", "Andrew Mitchell",
          "James Odell"], 2016,
         "https://bura.brunel.ac.uk/bitstream/2438/12420/3/Fulltext.pdf"),
    Work("industrial-4d", "The Role of Ontology in Integrating Semantically "
                          "Heterogeneous Databases", ["Chris Partridge"], 2002,
         "http://ftp.informatik.rwth-aachen.de/Publications/CEUR-WS/Vol-124/"
         "08partridge.pdf"),
    # Metadata-only: books and papers with no verified open copy.
    Work("industrial-4d", "Business Objects: Re-engineering for Re-use",
         ["Chris Partridge"], 1996, "",
         note="The origin of BORO's 4D commitment; likely paywalled"),
    Work("industrial-4d", "Developing High Quality Data Models",
         ["Matthew West"], 2011, "", note="Elsevier monograph; expect no open copy"),

    # === Digital twin / lifecycle identity ==================================
    Work("lifecycle", "Specification of the Asset Administration Shell "
                      "Part 1: Metamodel", ["IDTA"], 2025,
         "https://industrialdigitaltwin.io/aas-specifications/IDTA-01001/v3.2/"
         "part-1-metamodel.pdf",
         note="CC-BY; how Industry 4.0 models asset identity across a lifecycle"),
    Work("lifecycle", "The Asset Administration Shell and Common Misunderstandings",
         ["Open Industry 4.0 Alliance"], 2024,
         "https://openindustry4.com/wp-content/uploads/2025/03/"
         "The_Asset_Administration_Shell__AAS__and_common_misunderstandings.pdf"),

    # === The mismatch itself =================================================
    # Work that explicitly confronts the philosophical distinction with modern
    # knowledge-representation practice. The thinnest area of all.
    Work("mismatch", "On the Representation of Temporally Changing Information in OWL",
         ["Giancarlo Guizzardi", "Renata S. S. Guizzardi",
          "João Paulo A. Almeida"], 2010,
         "https://nemo.inf.ufes.br/wp-content/papercite-data/pdf/"
         "on_the_representation_of_temporally_changing_information_in_owl_2010.pdf",
         note="4D fluents vs time slices — the 3D/4D choice as an OWL "
              "engineering decision"),
    Work("mismatch", "Empirically Evaluating Three Proposals for Representing "
                     "Changes in OWL2",
         ["Jean-Rémi Bourguet", "Giancarlo Guizzardi",
          "Alessander Botti Benevides", "Veruska Zamborlini"], 2017,
         "https://ceur-ws.org/Vol-2050/DEW_paper_4.pdf",
         note="Explicit endurantism-vs-perdurantism comparison in practice"),
    Work("mismatch", "Temporal Modelling in Cultural Heritage Knowledge Graphs",
         ["Gilles Falquet", "Sarah Schmid"], 2024,
         "https://drops.dagstuhl.de/storage/08tgdk/tgdk-vol004/"
         "tgdk-vol004-issue001/TGDK.4.1.2/TGDK.4.1.2.pdf",
         note="BFO continuants/occurrents and 4D fluents in knowledge graphs"),
    Work("mismatch", "Ontological Foundations for Structural Conceptual Models",
         ["Giancarlo Guizzardi"], 2005,
         "https://nemo.inf.ufes.br/wp-content/papercite-data/pdf/"
         "ontological_foundations_for_structural_conceptual_models_2005.pdf",
         note="The UFO thesis: analytic metaphysics turned into modelling rules"),
    Work("mismatch", "Towards Ontological Foundations for Conceptual Modeling: "
                     "The Unified Foundational Ontology (UFO) Story",
         ["Giancarlo Guizzardi", "Gerd Wagner", "João Paulo A. Almeida",
          "Renata S. S. Guizzardi"], 2015,
         "https://inf.ufes.br/~gguizzardi/UFO-Story.pdf"),
    Work("mismatch", "A Formal Ontology of Properties",
         ["Nicola Guarino", "Christopher Welty"], 2000,
         "http://www.loa-cnr.it/Papers/EKAW-2000.pdf",
         note="Rigidity and identity criteria — the OntoClean machinery"),
    Work("mismatch", "Evaluating Ontological Decisions with OntoClean",
         ["Nicola Guarino", "Christopher Welty"], 2002,
         "http://www.loa.istc.cnr.it/old/Papers/CACM2002.pdf"),
    # Metadata-only bridge candidates with no verified open copy.
    Work("mismatch", "Identity, Unity, and Individuality: Towards a Formal "
                     "Toolkit for Ontological Analysis",
         ["Nicola Guarino", "Christopher Welty"], 2000, "",
         note="ECAI 2000; no open PDF found — OntoClean papers cover the ground"),

    # === Representing time in OWL / RDF: the 3D-vs-4D choice, operationalised ==
    # The engineering literature that has to pick a side. 4D fluents, temporal
    # reification, named graphs and n-ary relations are all direct answers to
    # "where do the changing properties live?".
    Work("temporal-kr", "A Reusable Ontology for Fluents in OWL",
         ["Christopher Welty", "Richard Fikes"], 2006,
         "https://web.archive.org/web/20100615000000id_/http://www.comp.leeds.ac.uk/"
         "brandon/FOIS-06/CRC/Part-5/20_fois06.pdf",
         note="FOIS 2006; the canonical 4D-fluents proposal. Only surviving copy "
              "is the Wayback snapshot of the FOIS-06 camera-ready site"),
    Work("temporal-kr", "Temporal RDF", ["Claudio Gutierrez", "Carlos Hurtado",
                                         "Alejandro Vaisman"], 2005,
         "https://www.dcc.uchile.cl/TR/2005/TR_DCC-2005-002.pdf"),
    Work("temporal-kr", "Introducing Time into RDF",
         ["Claudio Gutierrez", "Carlos Hurtado", "Alejandro Vaisman"], 2007,
         "https://www.dcc.uchile.cl/TR/2007/TR_DCC-2007-001.pdf"),
    Work("temporal-kr", "A Logical Design Pattern for Representing Change Over "
                        "Time in OWL", ["Megan Katsumi", "Mark Fox"], 2017,
         "https://ceur-ws.org/Vol-2043/paper-05.pdf"),
    Work("temporal-kr", "Defining Activity Specifications in OWL",
         ["Megan Katsumi", "Mark Fox"], 2017,
         "https://ceur-ws.org/Vol-2043/paper-07.pdf"),
    Work("temporal-kr", "A General Methodology for Equipping Ontologies With Time",
         ["Hans-Ulrich Krieger"], 2010,
         "http://www.lrec-conf.org/proceedings/lrec2010/pdf/29_Paper.pdf"),
    Work("temporal-kr", "A Temporal Extension of the Hayes and ter Horst "
                        "Entailment Rules for RDFS and OWL",
         ["Hans-Ulrich Krieger"], 2011,
         "http://commonsensereasoning.org/2011/papers/krieger1.pdf"),
    Work("temporal-kr", "An OWL Ontology for Biographical Knowledge: Representing "
                        "Time-Dependent Factual Knowledge",
         ["Hans-Ulrich Krieger", "Thierry Declerck"], 2015,
         "https://ceur-ws.org/Vol-1399/paper16.pdf"),
    Work("temporal-kr", "tOWL: Integrating Time in OWL",
         ["Flavius Frasincar", "Viorel Milea", "Uzay Kaymak"], 2010,
         "https://personal.eur.nl/frasincar/papers/SWIM2010/swim2010.pdf"),
    Work("temporal-kr", "A Temporal Web Ontology Language",
         ["Viorel Milea", "Flavius Frasincar", "Uzay Kaymak"], 2009,
         "https://repub.eur.nl/pub/16794/ERS-2009-050-LIS.pdf"),
    Work("temporal-kr", "Temporally Enhanced Ontologies in OWL: A Shared "
                        "Conceptual Model and Reference Implementation",
         ["Flavius Frasincar"], 2015,
         "https://personal.eur.nl/frasincar/papers/WISE2015/wise2015p.pdf"),
    Work("temporal-kr", "Temporal Representation and Reasoning in OWL 2",
         ["Sotiris Batsakis", "Euripides G. M. Petrakis", "Ilias Tachmazidis",
          "Grigoris Antoniou"], 2016,
         "https://www.semantic-web-journal.net/system/files/swj1118.pdf"),
    Work("temporal-kr", "Ontological Patterns for Modeling the Validity of "
                        "Spatiotemporal Statements", ["Nicola Carboni"], 2024,
         "https://ceur-ws.org/Vol-3809/paper5.pdf"),

    # === Round 2: the concepts the first audit still rated `thin` ============
    # After the round above, gap-audit.py reported five concepts as discussed in
    # passing but with no work *about* them. The four sections below target them
    # directly. Unlike the philosophy sections, most of this is CS literature, so
    # metadata-only entries are cheap — DBLP/arXiv/OpenAlex resolve them well.

    # --- Interval algebra & temporal reasoning ------------------------------
    # 88 documents mention Allen relations; none is the paper that defined them.
    Work("interval-algebra", "Maintaining Knowledge about Temporal Intervals",
         ["James F. Allen"], 1983,
         "https://cse.unl.edu/~choueiry/Documents/Allen-CACM1983.pdf",
         note="CACM; defines the 13 interval relations every later interval "
              "join, temporal ontology and event calculus builds on"),
    Work("interval-algebra", "Time Representation: A Taxonomy of Interval Relations",
         ["Peter Ladkin"], 1986,
         "https://cdn.aaai.org/AAAI/1986/AAAI86-060.pdf",
         note="AAAI-86; systematises Allen's calculus of convex intervals"),
    Work("interval-algebra", "Towards a General Theory of Action and Time",
         ["James F. Allen"], 1984, ""),
    Work("interval-algebra", "Actions and Events in Interval Temporal Logic",
         ["James F. Allen", "George Ferguson"], 1994, ""),
    Work("interval-algebra", "Constraint Propagation Algorithms for Temporal Reasoning",
         ["Marc Vilain", "Henry Kautz"], 1986, "",
         note="The tractable point-algebra fragment of Allen's calculus"),
    Work("interval-algebra", "Temporal Constraint Networks",
         ["Rina Dechter", "Itay Meiri", "Judea Pearl"], 1991, ""),
    Work("interval-algebra", "Temporal Reasoning Based on Semi-Intervals",
         ["Christian Freksa"], 1992, "",
         note="Coarse temporal knowledge — the case for not demanding exact "
              "endpoints, which is how real event data arrives"),
    Work("interval-algebra", "Developing Time-Oriented Database Applications in SQL",
         ["Richard T. Snodgrass"], 1999,
         "https://www.cs.arizona.edu/~rts/tdbbook.pdf",
         note="The author's freely released monograph; the practical bridge from "
              "interval semantics to valid-time/transaction-time SQL. This host "
              "serves an incomplete certificate chain, so `requests` (certifi) "
              "rejects it while curl (macOS trust store) accepts it — fetched "
              "manually. Its text layer is a broken ToUnicode map, so it needs "
              "OCR to become searchable"),

    # --- Slowly changing dimensions & historization ------------------------
    # The library holds Kimball's chapter but nothing that studies the problem.
    Work("historization", "A Survey on Temporal Data Warehousing",
         ["Matteo Golfarelli", "Stefano Rizzi"], 2009,
         "http://www-db.deis.unibo.it/~srizzi/PDF/ijdwm09-temporal.pdf",
         note="Frames slowly-changing dimensions as the temporal-database "
              "problem it actually is"),
    Work("historization", "Changes of Dimension Data in Temporal Data Warehouses",
         ["Johann Eder", "Christian Koncilia"], 2001, ""),
    Work("historization", "A Conceptual Model for Temporal Data Warehouses and "
                          "Its Transformation to the ER and the Object-Relational Models",
         ["Elzbieta Malinowski", "Esteban Zimányi"], 2008, ""),
    Work("historization", "Managing Time Consistency for Active Data Warehouse "
                          "Environments",
         ["Robert M. Bruckner", "A Min Tjoa"], 2001, ""),
    Work("historization", "On Handling the Evolution of External Data Sources in "
                          "a Data Warehouse Architecture",
         ["Robert Wrembel"], 2009, ""),

    # --- Event sourcing & immutable append-only state ----------------------
    # Mentioned in stream-processing chapters; no work about the pattern itself.
    Work("event-sourcing", "Immutability Changes Everything", ["Pat Helland"], 2015,
         "https://www.cidrdb.org/cidr2015/Papers/CIDR15_Paper16.pdf",
         note="CIDR 2015; the systems-side argument that append-only state is "
              "the natural representation — the database answer to 4D"),
    Work("event-sourcing", "The Dark Side of Event Sourcing: Managing Data Conversion",
         ["Michiel Overeem", "Marten Spoor", "Slinger Jansen"], 2017, "",
         note="SANER; the schema-evolution cost of an immutable log"),
    Work("event-sourcing", "An Empirical Characterization of Event Sourced Systems "
                           "and Their Schema Evolution",
         ["Michiel Overeem", "Marten Spoor", "Slinger Jansen",
          "Sjaak Brinkkemper"], 2021, "https://arxiv.org/pdf/2104.01146",
         note="JSS; author preprint, confirmed by reading page 1 — the resolvers "
              "missed it because the published version is Elsevier-gated"),
    Work("event-sourcing", "Online Event Processing: Achieving Consistency Where "
                           "Distributed Transactions Have Failed",
         ["Martin Kleppmann", "Alastair R. Beresford", "Boerge Svingen"], 2019, "",
         note="ACM Queue; CQRS/event-sourcing as a consistency mechanism"),

    # --- Identity & versioning in knowledge graphs --------------------------
    # The crux concept: the same question the philosophy sections ask, asked of
    # graphs that are actually deployed.
    Work("kg-versioning", "High-Level Change Detection in RDF(S) KBs",
         ["Vicky Papavasileiou", "Giorgos Flouris", "Irini Fundulaki",
          "Kostas Kotzinos", "Vassilis Christophides"], 2013, ""),
    Work("kg-versioning", "OSTRICH: Versioned Random-Access Triple Store",
         ["Ruben Taelman", "Miel Vander Sande", "Ruben Verborgh"], 2018, ""),
    Work("kg-versioning", "R&Wbase: Git for Triples",
         ["Miel Vander Sande", "Pieter Colpaert", "Ruben Verborgh",
          "Sam Coppens", "Erik Mannens", "Rik Van de Walle"], 2013, ""),
    Work("kg-versioning", "Towards Fully-Fledged Archiving for RDF Datasets",
         ["Olivier Pelgrin", "Luis Galárraga", "Katja Hose"], 2021, ""),
    Work("kg-versioning", "Detecting and Reporting Extensional Concept Drift in "
                          "Statistical Linked Data",
         ["Albert Meroño-Peñuela", "Christophe Guéret", "Stefan Schlobach"], 2015, "",
         note="Semantic drift: when the identity of a concept, not just its "
              "values, changes between versions"),

    # --- The 3D/4D modelling decision, from the empirical side --------------
    Work("mismatch", "Comprehending 3D and 4D Ontology-Driven Conceptual Models: "
                     "An Empirical Study",
         ["Michael Verdonck", "Frederik Gailly", "Sergio de Cesare"], 2020, "",
         note="Rare experimental comparison of the two commitments; the "
              "publisher copy is behind a 403, so the resolvers get a turn"),
    Work("mismatch", "Insights on the Use and Application of Ontology and "
                     "Conceptual Modeling Languages in Ontology-Driven "
                     "Conceptual Modeling",
         ["Michael Verdonck", "Frederik Gailly"], 2016, ""),
]


# ---------------------------------------------------------------------------
# 1. gather
# ---------------------------------------------------------------------------

def gather(dedup: bool) -> list[dict]:
    recs = [asdict(w) for w in WORKS]
    print(f"declared bibliography: {len(recs)} works "
          f"across {len({r['section'] for r in recs})} sections")
    for r in recs:
        if r["url"]:
            r["pdf_url"], r["source"], r["status"] = r["url"], "declared", "resolved"
    if dedup:
        idx = pf.IndexDedup()
        for r in recs:
            r["in_index"] = idx.contains(r["title"])
            if r["in_index"]:
                r["status"] = "in_index"
        print(f"  {sum(1 for r in recs if r['in_index'])} already in the search index")
    return recs


# ---------------------------------------------------------------------------
# 2. resolve
# ---------------------------------------------------------------------------

def resolve_one(r: dict, email: str) -> None:
    """Find an open copy for a metadata-only entry.

    OpenAlex leads here (not DBLP/arXiv as in the CS harvesters) because it is
    the only backend of the three that indexes philosophy and grey literature.
    """
    authors, title, year = r.get("authors") or [], r["title"], r.get("year")

    if r.get("doi"):
        up = pf.unpaywall_pdf(r["doi"], email)
        if up:
            r["pdf_url"], r["source"], r["status"] = up, "unpaywall", "resolved"
            return

    hit = pf.openalex_best(title, authors, year, email)
    if hit:
        for u in hit.get("pdf_urls") or []:
            r["pdf_url"], r["source"], r["status"] = u, "openalex", "resolved"
            return
        if hit.get("doi"):
            r["doi"] = hit["doi"]
            up = pf.unpaywall_pdf(hit["doi"], email)
            if up:
                r["pdf_url"], r["source"], r["status"] = up, "unpaywall", "resolved"
                return

    dh = pf.dblp_best(title, authors, year)
    if dh:
        for ee in dh.get("ee", []):
            low = ee.lower()
            if "arxiv.org/abs" in low or low.endswith(".pdf"):
                r["pdf_url"], r["source"], r["status"] = ee, "dblp-ee", "resolved"
                return
        if dh.get("doi"):
            up = pf.unpaywall_pdf(dh["doi"], email)
            if up:
                r["pdf_url"], r["source"], r["status"] = up, "unpaywall", "resolved"
                return

    ax = pf.arxiv_pdf(title, authors)
    if ax:
        r["pdf_url"], r["source"], r["status"] = ax, "arxiv", "resolved"
        return

    # Last: Semantic Scholar. It runs after the others because it is the slowest
    # (unauthenticated rate limit) but it reaches author-posted copies the
    # publisher-centric backends do not, which is the shape of what survives a
    # first harvest round.
    s2 = pf.semanticscholar_pdf(title, authors, year)
    if s2:
        r["pdf_url"], r["source"], r["status"] = s2, "semanticscholar", "resolved"
        return
    r["status"] = "unresolved"


def resolve(records: list[dict], limit: int | None) -> None:
    todo = [r for r in records
            if not r.get("in_index") and not r.get("pdf_url")
            and r.get("status") in ("pending", "unresolved")]
    if limit:
        todo = todo[:limit]
    if not todo:
        print("nothing to resolve (every entry has a URL or is already indexed)")
        return
    print(f"resolving open copies for {len(todo)} metadata-only entries...")
    email = pf.git_email()
    for i, r in enumerate(todo, 1):
        try:
            resolve_one(r, email)
        except Exception as exc:  # noqa: BLE001
            r["status"] = "unresolved"
            print(f"[{i}/{len(todo)}] ERR {type(exc).__name__} {r['title'][:55]}")
            continue
        print(f"[{i}/{len(todo)}] {(r['source'] or '--'):10s} {r['title'][:64]}")
        if i % 10 == 0:
            save_ckpt(records)
        time.sleep(RESOLVE_SLEEP)
    save_ckpt(records)


# ---------------------------------------------------------------------------
# 3. download
# ---------------------------------------------------------------------------

def download_file(sess, url: str, dest: Path, kind: str,
                  timeout: int = 120) -> tuple[bool, str]:
    """Fetch ``url`` to ``dest`` iff the body really is of type ``kind``.

    ``paperfetch.download_pdf`` only accepts PDFs; this bibliography also
    includes Project Gutenberg EPUBs of the public-domain classics, so the
    validation is generalised while keeping the same guarantee: a Cloudflare
    challenge or an HTML error page never lands in the library.
    """
    if dest.exists() and dest.stat().st_size > 2000:
        return True, "exists"
    magic, ctype_hint = KINDS.get(kind, KINDS["pdf"])
    try:
        r = sess.get(pf.normalize_pdf_url(url), timeout=timeout, allow_redirects=True)
        data = r.content
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:80]}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    ctype = r.headers.get("Content-Type", "").lower()
    if magic and not (data[:len(magic)] == magic or ctype_hint in ctype):
        return False, f"not a {kind} ({ctype or 'unknown'})"
    if len(data) < 2000:
        return False, f"too small ({len(data)} bytes)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True, f"{len(data) // 1024} KB"


def download(records: list[dict], limit: int | None) -> None:
    targets = [r for r in records if r.get("pdf_url") and not r.get("in_index")
               and r.get("status") in ("resolved", "dl_failed")]
    if limit:
        targets = targets[:limit]
    print(f"downloading {len(targets)} works -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        kind = r.get("kind") or "pdf"
        stem = pf.safe_stem(r.get("authors") or [], r["title"])
        dest = OUT_DIR / r["section"] / f"{stem}.{kind}"
        got, msg = download_file(sess, r["pdf_url"], dest, kind)
        if got:
            r["status"] = "downloaded"
            ok += 1
            print(f"[{i}/{len(targets)}] OK  ({r['source']}) {dest.name}  ({msg})")
        else:
            r["status"] = "dl_failed"
            r["note"] = (r.get("note") or "")
            fail += 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:52]}  ({msg})")
        if i % 10 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


# ---------------------------------------------------------------------------
# checkpoint / report
# ---------------------------------------------------------------------------

def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["section", "status", "in_index", "source", "year", "title",
                    "authors", "kind", "url", "note"])
        for r in records:
            w.writerow([r["section"], r.get("status", ""), r.get("in_index"),
                        r.get("source") or "", r.get("year") or "", r["title"],
                        "; ".join(r.get("authors", [])), r.get("kind", "pdf"),
                        r.get("pdf_url") or "", r.get("note", "")])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    from collections import Counter
    st = Counter(r.get("status") for r in records)
    by_sec = Counter(r["section"] for r in records)
    dl = Counter(r["section"] for r in records if r.get("status") == "downloaded")
    print("\n=== temporality & ontology harvest ===")
    print(f"  works: {len(records)}"
          f" | in index: {sum(1 for r in records if r.get('in_index'))}"
          f" | with a URL: {sum(1 for r in records if r.get('pdf_url'))}"
          f" | downloaded: {st.get('downloaded', 0)}")
    print(f"  status: {dict(st)}")
    print("  by section (downloaded/total):")
    for sec in sorted(by_sec):
        print(f"    {sec:20s} {dl.get(sec, 0):3d}/{by_sec[sec]}")
    unresolved = [r for r in records if r.get("status") in ("unresolved", "dl_failed")]
    if unresolved:
        print(f"\n  {len(unresolved)} without an obtainable copy "
              f"(see {REPORT.relative_to(DOCS_ROOT)}):")
        for r in unresolved:
            print(f"    [{r['section']}] {r['title'][:66]}")


def cmd_list(section: str | None) -> int:
    for w in WORKS:
        if section and w.section != section:
            continue
        flag = "url" if w.url else "resolve"
        print(f"  [{w.section:16s}] {flag:8s} ({w.year or '????'}) {w.title[:70]}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "resolve", "download", "all", "list", "report"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--section", default=None, help="restrict `list` to one section")
    p.add_argument("--no-dedup", action="store_true",
                   help="do not skip works already in the index")
    args = p.parse_args(argv)

    if args.cmd == "list":
        return cmd_list(args.section)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dedup = not args.no_dedup

    if args.cmd == "report":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint yet; run gather first", file=sys.stderr)
            return 2
        print_summary(recs)
        return 0
    if args.cmd == "gather":
        recs = gather(dedup); save_ckpt(recs); print_summary(recs); return 0
    if args.cmd == "resolve":
        recs = load_ckpt() or gather(dedup)
        resolve(recs, args.limit); print_summary(recs); return 0
    if args.cmd == "download":
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr)
            return 2
        download(recs, args.limit); print_summary(recs); return 0

    recs = load_ckpt()
    if not recs:
        recs = gather(dedup); save_ckpt(recs)
    resolve(recs, args.limit)
    download(recs, args.limit)
    print_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
