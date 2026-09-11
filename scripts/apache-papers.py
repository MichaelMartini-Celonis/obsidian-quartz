#!/usr/bin/env python3
"""Harvest the academic papers behind the Apache data-platform projects.

The companion to the documentation sources registered in
``scripts/import-docs.py``: a project's manual says how to use it, and its
paper says what problem it claims to solve and what it gave up to do so. For
this collection the papers are the more valuable half — the design arguments in
them (log-structured storage, snapshot isolation over object stores, watermarks
and out-of-order streams, cross-platform plan federation, columnar layout
trade-offs) are the prior art that the Context Model's own storage and event
semantics are argued against, and they are what the manuals leave out.

**This is a citation cohort, not a scrape.** Apache projects publish
documentation, not papers; the papers live at VLDB, SIGMOD, CIDR, NSDI, SOSP
and OSDI under the authors' names, and there is no per-project listing to
crawl. So the cohort is enumerated here — one entry per canonical paper, tagged
with the project it belongs to — and resolved through the shared open-access
backends in ``scripts/paperfetch.py`` (arXiv → OpenAlex → Semantic Scholar →
Unpaywall by DOI), with an explicit URL where a paper is only served from one
place. Several entries are *ancestors* rather than Apache papers: Bigtable
behind HBase, Dremel behind Parquet and Drill, Percolator behind Fluo, Pregel
behind Giraph, Raft behind Ratis, Dapper behind SkyWalking. A project's
documentation never cites them and its design is unreadable without them.

**Half of this cohort is invisible to the open-access graph.** These papers are
overwhelmingly SIGMOD/SoCC/ICDE, and OpenAlex reports most of them as `closed`
even when a free PDF has sat on the author's university page for fifteen years —
the copy exists, but nothing links it to the DOI. A first pass resolved only 20
of 62. So ``MIRRORS`` below records a verified open location per title, checked
by actually fetching it and confirming a `%PDF` header rather than trusting the
URL to look plausible; it is consulted **last**, after the OA backends, so a
paper that later becomes properly open is taken from its canonical home instead.
Three venue patterns cover most of it: VLDB's proceedings are open at
`vldb.org/pvldb/vol<N>/`, ACM serves author-selected open articles at
`dl.acm.org/doi/pdf/<doi>` even where the abstract page looks paywalled, and
USENIX (NSDI/OSDI/ATC) publishes everything. Because a mirror is a URL on
someone else's homepage, expect this map to rot; a `dl_failed` line in the report
means re-verifying that entry, not that the paper vanished.

Because the corpus already holds a large share of the classic systems
literature, the cohort is filtered against the search index *before* anything
is downloaded (``paperfetch.IndexDedup``): a title match costs nothing and
avoids re-fetching what is already filed. Unlike the IDSA and Panikzettel
harvesters this check *does* gate the download — these are single-edition
papers, so a title match is a genuine duplicate rather than a newer revision.

Pipeline (resumable via a JSON checkpoint):

  1. gather   - build the cohort, mark what the index already holds.
  2. resolve  - find an open copy for each remaining paper.
  3. download - fetch them into ``Inbox/apache-papers/``.

    scripts/.venv/bin/python scripts/apache-papers.py all
    scripts/.venv/bin/python scripts/apache-papers.py gather|resolve|download
    scripts/.venv/bin/python scripts/apache-papers.py all --project spark flink
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

DOCS_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = DOCS_ROOT / "Inbox" / "apache-papers"
CKPT = OUT_DIR / "_apache-papers.json"
REPORT = OUT_DIR / "_apache-papers-report.csv"
DL_SLEEP = 1.0

# (project, title, first-author surnames, direct URL or None, DOI or None)
#
# ``project`` is the Apache project the paper belongs to, or ``<project>
# (ancestor)`` for the pre-Apache system a project reimplements.
PAPERS: list[tuple[str, str, list[str], str | None, str | None]] = [
    # --- Hadoop: the storage and scheduling substrate --------------------
    ("hadoop", "The Hadoop Distributed File System",
     ["Shvachko", "Kuang", "Radia", "Chansler"], None,
     "10.1109/MSST.2010.5496972"),
    ("hadoop", "Apache Hadoop YARN: Yet Another Resource Negotiator",
     ["Vavilapalli", "Murthy", "Douglas", "Agarwal"], None,
     "10.1145/2523616.2523633"),
    ("hadoop (ancestor)", "MapReduce: Simplified Data Processing on Large Clusters",
     ["Dean", "Ghemawat"], None, "10.1145/1327452.1327492"),
    ("hadoop (ancestor)", "The Google File System",
     ["Ghemawat", "Gobioff", "Leung"], None, "10.1145/945445.945450"),
    ("hadoop", "A Comparison of Approaches to Large-Scale Data Analysis",
     ["Pavlo", "Paulson", "Rasin", "Abadi", "DeWitt", "Madden", "Stonebraker"],
     None, "10.1145/1559845.1559865"),
    # --- Spark ----------------------------------------------------------
    ("spark", "Resilient Distributed Datasets: A Fault-Tolerant Abstraction "
     "for In-Memory Cluster Computing",
     ["Zaharia", "Chowdhury", "Das", "Dave", "Ma"], None, None),
    ("spark", "Spark SQL: Relational Data Processing in Spark",
     ["Armbrust", "Xin", "Lian", "Huai", "Liu"], None,
     "10.1145/2723372.2742797"),
    ("spark", "Structured Streaming: A Declarative API for Real-Time "
     "Applications in Apache Spark",
     ["Armbrust", "Das", "Torres", "Yavuz", "Zhu"], None,
     "10.1145/3183713.3190664"),
    ("spark", "Apache Spark: A Unified Engine for Big Data Processing",
     ["Zaharia", "Xin", "Wendell", "Das", "Armbrust"], None,
     "10.1145/2934664"),
    ("spark", "Discretized Streams: Fault-Tolerant Streaming Computation at Scale",
     ["Zaharia", "Das", "Li", "Hunter", "Shenker", "Stoica"], None,
     "10.1145/2517349.2522737"),
    ("spark", "GraphX: Graph Processing in a Distributed Dataflow Framework",
     ["Gonzalez", "Xin", "Dave", "Crankshaw", "Franklin", "Stoica"], None, None),
    ("spark", "MLlib: Machine Learning in Apache Spark",
     ["Meng", "Bradley", "Yavuz", "Sparks", "Venkataraman"], None, None),
    # --- Flink, Beam and the streaming model ----------------------------
    ("flink", "Apache Flink: Stream and Batch Processing in a Single Engine",
     ["Carbone", "Katsifodimos", "Ewen", "Markl", "Haridi", "Tzoumas"], None,
     None),
    ("flink", "Lightweight Asynchronous Snapshots for Distributed Dataflows",
     ["Carbone", "Fora", "Ewen", "Haridi", "Tzoumas"], None, None),
    ("flink", "State Management in Apache Flink: Consistent Stateful "
     "Distributed Stream Processing",
     ["Carbone", "Ewen", "Fora", "Haridi", "Richter", "Tzoumas"], None,
     "10.14778/3137765.3137777"),
    ("beam", "The Dataflow Model: A Practical Approach to Balancing "
     "Correctness, Latency, and Cost in Massive-Scale, Unbounded, "
     "Out-of-Order Data Processing",
     ["Akidau", "Bradshaw", "Chambers", "Chernyak"], None,
     "10.14778/2824032.2824076"),
    ("beam (ancestor)", "MillWheel: Fault-Tolerant Stream Processing at "
     "Internet Scale",
     ["Akidau", "Balikov", "Bekiroglu", "Chernyak"], None,
     "10.14778/2536222.2536229"),
    ("beam (ancestor)", "Photon: Fault-tolerant and Scalable Joining of "
     "Continuous Data Streams",
     ["Ananthanarayanan", "Basker", "Das", "Gupta"], None,
     "10.1145/2463676.2465272"),
    # --- Kafka, Pulsar, Samza, Storm: logs and stream transport ---------
    ("kafka", "Kafka: a Distributed Messaging System for Log Processing",
     ["Kreps", "Narkhede", "Rao"], None, None),
    ("kafka", "Building a Replicated Logging System with Apache Kafka",
     ["Wang", "Koshy", "Subramanian", "Paramasivam"], None,
     "10.14778/2824032.2824063"),
    ("samza", "Samza: Stateful Scalable Stream Processing at LinkedIn",
     ["Noghabi", "Paramasivam", "Pan", "Ramesh", "Bringhurst"], None,
     "10.14778/3137765.3137770"),
    ("storm", "Storm@Twitter",
     ["Toshniwal", "Taneja", "Shukla", "Ramasamy", "Patel"], None,
     "10.1145/2588555.2595641"),
    ("storm (successor)", "Twitter Heron: Stream Processing at Scale",
     ["Kulkarni", "Bhagat", "Fu", "Kedigehalli", "Kellogg"], None,
     "10.1145/2723372.2742788"),
    ("pulsar", "Pulsar: Efficient and Flexible Multi-Tenant Messaging",
     ["Merli", "Guo"], None, None),
    ("bookkeeper", "DistributedLog: A High Performance Replicated Log Service",
     ["Guo", "Kumar", "Shah", "Ye"], None, "10.1109/ICDE.2017.194"),
    # --- Wide-column and key-value stores -------------------------------
    ("hbase (ancestor)", "Bigtable: A Distributed Storage System for "
     "Structured Data",
     ["Chang", "Dean", "Ghemawat", "Hsieh", "Wallach"], None,
     "10.1145/1365815.1365816"),
    ("cassandra", "Cassandra: a decentralized structured storage system",
     ["Lakshman", "Malik"], None, "10.1145/1773912.1773922"),
    ("cassandra (ancestor)", "Dynamo: Amazon's Highly Available Key-value Store",
     ["DeCandia", "Hastorun", "Jampani", "Kakulapati"], None,
     "10.1145/1294261.1294281"),
    ("accumulo (ancestor)", "Large-scale Incremental Processing Using "
     "Distributed Transactions and Notifications",
     ["Peng", "Dabek"], None, None),
    # --- SQL on Hadoop --------------------------------------------------
    ("hive", "Hive - A Warehousing Solution Over a Map-Reduce Framework",
     ["Thusoo", "Sarma", "Jain", "Shao", "Chakka"], None,
     "10.14778/1687553.1687609"),
    ("hive", "Major Technical Advancements in Apache Hive",
     ["Huai", "Chauhan", "Gates", "Hagleitner", "Hanson"], None,
     "10.1145/2588555.2595630"),
    ("pig", "Pig Latin: A Not-So-Foreign Language for Data Processing",
     ["Olston", "Reed", "Srivastava", "Kumar", "Tomkins"], None,
     "10.1145/1376616.1376726"),
    ("pig", "Building a High-Level Dataflow System on top of Map-Reduce: "
     "The Pig Experience",
     ["Gates", "Natkovich", "Chopra", "Kamath", "Narayanamurthy"], None,
     "10.14778/1687553.1687568"),
    ("impala", "Impala: A Modern, Open-Source SQL Engine for Hadoop",
     ["Kornacker", "Behm", "Bittorf", "Bobrovytsky", "Ching"], None, None),
    ("tez", "Apache Tez: A Unifying Framework for Modeling and Building "
     "Data Processing Applications",
     ["Saha", "Shah", "Seth", "Vijayaraghavan", "Murthy", "Curino"], None,
     "10.1145/2723372.2742790"),
    ("calcite", "Apache Calcite: A Foundational Framework for Optimized "
     "Query Processing Over Heterogeneous Data Sources",
     ["Begoli", "Camacho-Rodriguez", "Hyde", "Mior", "Lemire"], None,
     "10.1145/3183713.3190662"),
    ("drill (ancestor)", "Dremel: Interactive Analysis of Web-Scale Datasets",
     ["Melnik", "Gubarev", "Long", "Romer", "Shivakumar"], None,
     "10.14778/1920841.1920886"),
    ("drill (ancestor)", "Dremel: A Decade of Interactive SQL Analysis at "
     "Web Scale",
     ["Melnik", "Gubarev", "Long", "Romer", "Shivakumar"], None,
     "10.14778/3415478.3415568"),
    # --- Columnar storage, table formats and the lakehouse --------------
    ("parquet", "An Empirical Evaluation of Columnar Storage Formats",
     ["Zeng", "Liu", "Butrovich", "Zhou", "Pavlo"], None, None),
    ("iceberg", "Analyzing and Comparing Lakehouse Storage Systems",
     ["Jain", "Zaharia", "Armbrust", "Ghodsi"], None, None),
    ("iceberg (comparison)", "Delta Lake: High-Performance ACID Table "
     "Storage over Cloud Object Stores",
     ["Armbrust", "Das", "Sun", "Yavuz", "Zhu"], None,
     "10.14778/3415478.3415560"),
    ("iceberg (comparison)", "Lakehouse: A New Generation of Open Platforms "
     "that Unify Data Warehousing and Advanced Analytics",
     ["Zaharia", "Ghodsi", "Xin", "Armbrust"], None, None),
    ("arrow", "The Composable Data Management System Manifesto",
     ["Pedreira", "Erling", "Karanasos", "Schneider", "McKinney"], None,
     "10.14778/3603581.3603604"),
    ("datafusion", "Apache Arrow DataFusion: A Fast, Embeddable, Modular "
     "Analytic Query Engine",
     ["Lamb", "Shen", "Hare", "Sun", "Kabak"], None,
     "10.1145/3626246.3653368"),
    ("gluten (ancestor)", "Velox: Meta's Unified Execution Engine",
     ["Pedreira", "Erling", "Basmanova", "Wilfong", "Sakka"], None,
     "10.14778/3554821.3554829"),
    # --- OLAP stores ----------------------------------------------------
    ("druid", "Druid: a real-time analytical data store",
     ["Yang", "Tschetter", "Leaute", "Ray", "Merlino"], None,
     "10.1145/2588555.2595631"),
    ("pinot", "Pinot: Realtime OLAP for 530 Million Users",
     ["Im", "Gopalakrishna", "Subramaniam", "Shrivastava"], None,
     "10.1145/3183713.3190661"),
    ("doris", "Apache Doris: An Easy-to-Use, High-Performance and Unified "
     "Analytical Database",
     ["Chen", "Yang", "Zhao", "Yang"], None, None),
    ("kudu", "Kudu: Storage for Fast Analytics on Fast Data",
     ["Lipcon", "Alves", "Burkert", "Cryans", "Dembo"], None, None),
    ("cloudberry (ancestor)", "Greenplum: A Hybrid Database for "
     "Transactional and Analytical Workloads",
     ["Lyu", "Li", "Chen", "Zhang", "Wang"], None,
     "10.1145/3448016.3457562"),
    ("kylin (ancestor)", "Implementing Data Cubes Efficiently",
     ["Harinarayan", "Rajaraman", "Ullman"], None, "10.1145/235968.233333"),
    # --- Semistructured / document / multi-model ------------------------
    ("asterixdb", "AsterixDB: A Scalable, Open Source BDMS",
     ["Alsubaiee", "Altowim", "Altwaijry", "Behm", "Borkar"], None,
     "10.14778/2733085.2733096"),
    ("asterixdb", "Algebricks: a data model-agnostic compiler backend for "
     "Big Data languages",
     ["Borkar", "Bu", "Carman", "Onose", "Westmann"], None,
     "10.1145/2806777.2806923"),
    ("asterixdb", "The SQL++ Query Language: Configurable, Unifying and "
     "Semi-structured",
     ["Ong", "Papakonstantinou", "Vernoux"], None, None),
    ("couchdb (ancestor)", "A Comparison of Document-Oriented and "
     "Relational Data Models for Semi-Structured Data",
     ["Bourhis", "Reutter", "Suarez", "Vrgoc"], None, None),
    # --- Time series ----------------------------------------------------
    ("iotdb", "Apache IoTDB: A Time Series Database for Internet of Things",
     ["Wang", "Qiao", "Kang", "Jiang", "Song"], None,
     "10.14778/3415478.3415504"),
    ("iotdb", "Apache IoTDB: Time-series database for Internet of Things",
     ["Wang", "Kang", "Jiang", "Song", "Wang"], None, None),
    # --- Consensus and coordination -------------------------------------
    ("zookeeper", "ZooKeeper: Wait-free Coordination for Internet-scale Systems",
     ["Hunt", "Konar", "Junqueira", "Reed"], None, None),
    ("zookeeper", "Zab: High-performance broadcast for primary-backup systems",
     ["Junqueira", "Reed", "Serafini"], None, "10.1109/DSN.2011.5958223"),
    ("ratis (ancestor)", "In Search of an Understandable Consensus Algorithm",
     ["Ongaro", "Ousterhout"], None, None),
    ("ratis (ancestor)", "The Part-Time Parliament",
     ["Lamport"], None, "10.1145/279227.279229"),
    # --- Graph ----------------------------------------------------------
    ("tinkerpop", "The Gremlin Graph Traversal Machine and Language",
     ["Rodriguez"], None, "10.1145/2815072.2815073"),
    ("tinkerpop (context)", "Graph Pattern Matching in GQL and SQL/PGQ",
     ["Deutsch", "Francis", "Green", "Hare", "Li"], None,
     "10.1145/3514221.3526057"),
    ("giraph (ancestor)", "Pregel: A System for Large-Scale Graph Processing",
     ["Malewicz", "Austern", "Bik", "Dehnert", "Horn"], None,
     "10.1145/1807167.1807184"),
    ("giraph", "One Trillion Edges: Graph Processing at Facebook-Scale",
     ["Ching", "Edunov", "Kabiljo", "Logothetis", "Muthukrishnan"], None,
     "10.14778/2824032.2824077"),
    ("geaflow", "GeaFlow: A Graph Extended and Accelerated Dataflow System",
     ["Pan", "Fang", "Chen", "Zhang"], None, "10.1145/3589771"),
    ("graphar", "GraphAr: An Efficient Storage Scheme for Graph Data in "
     "Data Lakes",
     ["Li", "Zhang", "Wang", "Chen"], None, None),
    ("hugegraph (context)", "The Ubiquity of Large Graphs and Surprising "
     "Challenges of Graph Processing",
     ["Sahu", "Mhedhbi", "Salihoglu", "Lin", "Ozsu"], None,
     "10.14778/3157794.3157795"),
    # --- Geospatial -----------------------------------------------------
    ("sedona", "Spatial Data Management in Apache Spark: The GeoSpark "
     "Perspective and Beyond",
     ["Yu", "Zhang", "Sarwat"], None, "10.1007/s10707-018-0330-9"),
    ("sedona", "GeoSpark: A Cluster Computing Framework for Processing "
     "Large-Scale Spatial Data",
     ["Yu", "Wu", "Sarwat"], None, "10.1145/2820783.2820860"),
    # --- Declarative machine learning in the database -------------------
    ("systemds", "SystemDS: A Declarative Machine Learning System for the "
     "End-to-End Data Science Lifecycle",
     ["Boehm", "Antonov", "Baunsgaard", "Dokter", "Ginthoer"], None, None),
    ("systemds (ancestor)", "SystemML: Declarative Machine Learning on Spark",
     ["Boehm", "Dusenberry", "Eriksson", "Evfimievski", "Manshadi"], None,
     "10.14778/3007263.3007279"),
    ("madlib", "The MADlib Analytics Library or MAD Skills, the SQL",
     ["Hellerstein", "Re", "Schoppmann", "Wang", "Fratkin"], None,
     "10.14778/2367502.2367510"),
    ("madlib (ancestor)", "MAD Skills: New Analysis Practices for Big Data",
     ["Cohen", "Dolan", "Dunlap", "Hellerstein", "Welton"], None,
     "10.14778/1687553.1687576"),
    # --- Cross-platform / federated execution ---------------------------
    ("wayang", "RHEEM: Enabling Cross-Platform Data Processing",
     ["Agrawal", "Chawla", "Contreras-Rojas", "Elmagarmid", "Idris"], None,
     "10.14778/3204028.3204035"),
    ("wayang", "Apache Wayang: A Unified Data Analytics Framework",
     ["Beedkar", "Brinkmann", "Kruse", "Quiane-Ruiz", "Markl"], None, None),
    ("wayang", "Road to Freedom in Big Data Analytics",
     ["Agrawal", "Ba", "Berti-Equille", "Chawla", "Elmagarmid"], None,
     "10.5441/002/edbt.2016.47"),
    ("reef", "REEF: Retainable Evaluator Execution Framework",
     ["Chun", "Condie", "Chen", "Cho", "Chung"], None,
     "10.1145/2723372.2742793"),
    ("gobblin", "Gobblin: Unifying Data Ingestion for Hadoop",
     ["Qiao", "Li", "Narkhede", "Fung", "Vasanth"], None,
     "10.14778/2824032.2824073"),
    # --- Cluster management and observability ---------------------------
    ("yunikorn (ancestor)", "Mesos: A Platform for Fine-Grained Resource "
     "Sharing in the Data Center",
     ["Hindman", "Konwinski", "Zaharia", "Ghodsi", "Joseph"], None, None),
    ("yunikorn (ancestor)", "Large-scale cluster management at Google with Borg",
     ["Verma", "Pedrosa", "Korupolu", "Oppenheimer", "Tune"], None,
     "10.1145/2741948.2741964"),
    ("skywalking (ancestor)", "Dapper, a Large-Scale Distributed Systems "
     "Tracing Infrastructure",
     ["Sigelman", "Barroso", "Burrows", "Stephenson", "Plakal"], None, None),
    # --- Visualisation and interactive analytics ------------------------
    ("echarts", "ECharts: A declarative framework for rapid construction of "
     "web-based visualization",
     ["Li", "Mei", "Shen", "Su", "Zhang"], None,
     "10.1016/j.visinf.2018.04.011"),
    ("superset (context)", "Voyager: Exploratory Analysis via Faceted "
     "Browsing of Visualization Recommendations",
     ["Wongsuphasawat", "Moritz", "Anand", "Mackinlay", "Howe", "Heer"], None,
     "10.1109/TVCG.2015.2467191"),
    ("texera", "Texera: A System for Collaborative and Interactive Data "
     "Analytics Workflows",
     ["Wang", "Liu", "Kim", "Xu", "Zuo"], None, None),
    ("zeppelin (context)", "Notebooks as Programs: Composing Reproducible "
     "Data Science Pipelines",
     ["Pimentel", "Murta", "Braganholo", "Freire"], None, None),
    # --- Distributed ledgers (incubating) -------------------------------
    ("resilientdb", "ResilientDB: Global Scale Resilient Blockchain Fabric",
     ["Gupta", "Hellings", "Rahnama", "Sadoghi"], None,
     "10.14778/3389133.3389156"),
]


# Verified open locations for papers the OA graph reports as closed. Every URL
# here was fetched and confirmed to return a PDF; see the module docstring.
MIRRORS: dict[str, str] = {
    # VLDB — the Endowment's proceedings are open, but only some are indexed.
    "Hive - A Warehousing Solution Over a Map-Reduce Framework":
        "https://www.vldb.org/pvldb/vol2/vldb09-938.pdf",
    "Building a High-Level Dataflow System on top of Map-Reduce: "
    "The Pig Experience":
        "https://www.vldb.org/pvldb/vol2/vldb09-1074.pdf",
    "MAD Skills: New Analysis Practices for Big Data":
        "https://www.vldb.org/pvldb/vol2/vldb09-219.pdf",
    "Building a Replicated Logging System with Apache Kafka":
        "https://www.vldb.org/pvldb/vol8/p1654-wang.pdf",
    "Gobblin: Unifying Data Ingestion for Hadoop":
        "https://www.vldb.org/pvldb/vol8/p1764-qiao.pdf",
    "One Trillion Edges: Graph Processing at Facebook-Scale":
        "https://www.vldb.org/pvldb/vol8/p1804-ching.pdf",
    "SystemML: Declarative Machine Learning on Spark":
        "https://www.vldb.org/pvldb/vol9/p1425-boehm.pdf",
    "Samza: Stateful Scalable Stream Processing at LinkedIn":
        "https://www.vldb.org/pvldb/vol10/p1634-noghabi.pdf",
    "State Management in Apache Flink: Consistent Stateful Distributed "
    "Stream Processing":
        "https://www.vldb.org/pvldb/vol10/p1718-carbone.pdf",
    "Dremel: A Decade of Interactive SQL Analysis at Web Scale":
        "https://www.vldb.org/pvldb/vol13/p3461-melnik.pdf",
    # ACM — author-selected open access, reachable at /doi/pdf/ even where the
    # landing page presents a paywall.
    "Apache Spark: A Unified Engine for Big Data Processing":
        "https://dl.acm.org/doi/pdf/10.1145/2934664",
    "Structured Streaming: A Declarative API for Real-Time Applications "
    "in Apache Spark":
        "https://dl.acm.org/doi/pdf/10.1145/3183713.3190664",
    "Storm@Twitter":
        "https://dl.acm.org/doi/pdf/10.1145/2588555.2595641",
    "Major Technical Advancements in Apache Hive":
        "https://dl.acm.org/doi/pdf/10.1145/2588555.2595630",
    "Apache Tez: A Unifying Framework for Modeling and Building Data "
    "Processing Applications":
        "https://dl.acm.org/doi/pdf/10.1145/2723372.2742790",
    "REEF: Retainable Evaluator Execution Framework":
        "https://dl.acm.org/doi/pdf/10.1145/2723372.2742793",
    "Algebricks: a data model-agnostic compiler backend for Big Data languages":
        "https://dl.acm.org/doi/pdf/10.1145/2806777.2806941",
    "Pinot: Realtime OLAP for 530 Million Users":
        "https://dl.acm.org/doi/pdf/10.1145/3183713.3190661",
    "Apache Arrow DataFusion: A Fast, Embeddable, Modular Analytic "
    "Query Engine":
        "https://dl.acm.org/doi/pdf/10.1145/3626246.3653368",
    "Implementing Data Cubes Efficiently":
        "https://dl.acm.org/doi/pdf/10.1145/233269.233333",
    # USENIX — everything it publishes is open.
    "ZooKeeper: Wait-free Coordination for Internet-scale Systems":
        "https://www.usenix.org/legacy/event/atc10/tech/full_papers/Hunt.pdf",
    "Mesos: A Platform for Fine-Grained Resource Sharing in the Data Center":
        "https://www.usenix.org/legacy/event/nsdi11/tech/full_papers/"
        "Hindman_new.pdf",
    "GraphX: Graph Processing in a Distributed Dataflow Framework":
        "https://www.usenix.org/system/files/conference/osdi14/"
        "osdi14-paper-gonzalez.pdf",
    # Author, project and course pages — the least stable of the three.
    "The Hadoop Distributed File System":
        "https://pages.cs.wisc.edu/~akella/CS838/F15/838-CloudPapers/hdfs.pdf",
    "Apache Hadoop YARN: Yet Another Resource Negotiator":
        "https://www.cse.ust.hk/~weiwa/teaching/Fall15-COMP6611B/"
        "reading_list/YARN.pdf",
    "A Comparison of Approaches to Large-Scale Data Analysis":
        "https://www.cs.cmu.edu/~pavlo/static/papers/benchmarks-sigmod09.pdf",
    "Spark SQL: Relational Data Processing in Spark":
        "https://people.csail.mit.edu/matei/papers/2015/sigmod_spark_sql.pdf",
    "Pig Latin: A Not-So-Foreign Language for Data Processing":
        "http://infolab.stanford.edu/~olston/publications/sigmod08.pdf",
    "Cassandra: a decentralized structured storage system":
        "https://www.cs.cornell.edu/projects/ladis2009/papers/"
        "lakshman-ladis2009.pdf",
    "Kafka: a Distributed Messaging System for Log Processing":
        "http://notes.stephenholiday.com/Kafka.pdf",
    "Photon: Fault-tolerant and Scalable Joining of Continuous Data Streams":
        "https://research.google.com/pubs/archive/41318.pdf",
    "Pregel: A System for Large-Scale Graph Processing":
        "https://kowshik.github.io/JPregel/pregel_paper.pdf",
    "Druid: a real-time analytical data store":
        "http://static.druid.io/docs/druid.pdf",
    "Kudu: Storage for Fast Analytics on Fast Data":
        "https://kudu.apache.org/kudu.pdf",
    "GeoSpark: A Cluster Computing Framework for Processing Large-Scale "
    "Spatial Data":
        "https://jiayuasu.github.io/files/paper/GeoSpark_ShortPaper.pdf",
    "Spatial Data Management in Apache Spark: The GeoSpark Perspective "
    "and Beyond":
        "https://jiayuasu.github.io/files/paper/"
        "GeoSpark_Geoinformatica_2018.pdf",
    "Voyager: Exploratory Analysis via Faceted Browsing of Visualization "
    "Recommendations":
        "https://idl.cs.washington.edu/files/2015-Voyager-InfoVis.pdf",
    "Road to Freedom in Big Data Analytics":
        "https://openproceedings.org/2016/conf/edbt/paper-47.pdf",
    "Notebooks as Programs: Composing Reproducible Data Science Pipelines":
        "https://arxiv.org/pdf/1903.00934",
}


def cohort(projects: set[str] | None) -> list[dict]:
    out = []
    for project, title, authors, url, doi in PAPERS:
        if projects and project.split()[0] not in projects:
            continue
        out.append({
            "project": project, "title": title, "authors": authors,
            "url_override": url, "doi": doi,
            "status": "pending", "how": "", "url": "", "file": "",
        })
    return out


def gather(projects: set[str] | None, dedup: bool) -> list[dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = cohort(projects)
    print(f"cohort: {len(records)} papers across "
          f"{len({r['project'].split()[0] for r in records})} projects")
    if dedup:
        idx = pf.IndexDedup()
        if idx.available:
            held = 0
            for r in records:
                if idx.contains(r["title"]):
                    r["status"], held = "held", held + 1
            print(f"  {held} already in the search index — not downloaded again")
        else:
            print("  ! search index unavailable; every paper will be fetched",
                  file=sys.stderr)
    return records


def resolve_one(rec: dict) -> tuple[str | None, str]:
    if rec["url_override"]:
        return rec["url_override"], "override"
    title, authors = rec["title"], rec["authors"]
    # A location that already failed to yield a PDF is not a location: prefer
    # the verified mirror over asking the same backend for the same dead URL.
    if rec["status"].startswith("dl_failed") and (m := MIRRORS.get(title)):
        return m, "mirror"
    for fn, how in (
        (lambda: pf.arxiv_pdf(title, authors), "arxiv"),
        (lambda: pf.openalex_pdf(title, authors), "openalex"),
        (lambda: pf.semanticscholar_pdf(title, authors), "semanticscholar"),
    ):
        try:
            if got := fn():
                return got, how
        except Exception:
            pass
    if rec["doi"]:
        try:
            for loc in pf.unpaywall_locations(rec["doi"], pf.git_email()):
                return loc, "unpaywall"
        except Exception:
            pass
    if mirror := MIRRORS.get(title):
        return mirror, "mirror"
    return None, "unresolved"


def resolve(records: list[dict]) -> None:
    for r in records:
        if r["status"].startswith("dl_failed"):
            r["url"] = ""
    targets = [r for r in records
               if r["status"] not in ("held", "downloaded") and not r["url"]]
    print(f"resolving an open copy for {len(targets)} papers …")
    for i, r in enumerate(targets, 1):
        url, how = resolve_one(r)
        r["url"], r["how"] = url or "", how
        if not url:
            r["status"] = "no-open-copy"
        print(f"[{i}/{len(targets)}] {how:>16}  {r['title'][:68]}")
        if i % 10 == 0:
            save_ckpt(records)
    save_ckpt(records)


def download(records: list[dict], force: bool) -> None:
    targets = [r for r in records if r["url"]
               and (force or r["status"] not in ("held", "downloaded"))]
    print(f"downloading {len(targets)} PDFs -> {OUT_DIR}")
    sess = pf.session()
    ok = fail = 0
    for i, r in enumerate(targets, 1):
        stem = pf.safe_stem(r["authors"][:1], r["title"])
        dest = OUT_DIR / f"{stem}.pdf"
        got, msg = pf.download_pdf(sess, r["url"], dest)
        if got:
            r["status"], r["file"] = "downloaded", str(dest.relative_to(DOCS_ROOT))
            ok += 1
            print(f"[{i}/{len(targets)}] OK  {dest.name}  ({msg})")
        else:
            r["status"], fail = f"dl_failed: {msg}", fail + 1
            print(f"[{i}/{len(targets)}] --  {r['title'][:60]}  ({msg})")
        if i % 10 == 0:
            save_ckpt(records)
        time.sleep(DL_SLEEP)
    save_ckpt(records)
    print(f"\n=== downloaded {ok}, failed {fail} ===")


def save_ckpt(records: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(records, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["project", "status", "how", "title", "doi", "url", "file"])
        for r in records:
            w.writerow([r["project"], r["status"], r["how"], r["title"],
                        r["doi"] or "", r["url"], r["file"]])


def load_ckpt() -> list[dict]:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []


def print_summary(records: list[dict]) -> None:
    st = Counter(r["status"].split(":")[0] for r in records)
    print("\n=== Apache papers summary ===")
    print(f"  cohort {len(records)} | downloaded {st['downloaded']} | "
          f"held {st['held']} | no open copy {st['no-open-copy']} | "
          f"failed {st['dl_failed']} | pending {st['pending']}")
    for r in records:
        if r["status"].startswith(("no-open-copy", "dl_failed")):
            print(f"  ! [{r['project']}] {r['title'][:66]} ({r['status'][:40]})")
    print(f"\nreport: {REPORT.relative_to(DOCS_ROOT)}")
    print("Next: scripts/.venv/bin/python scripts/import-downloads.py "
          "--only apache-papers")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["gather", "resolve", "download", "all"])
    p.add_argument("--project", nargs="*", metavar="KEY",
                   help="restrict the cohort to these projects")
    p.add_argument("--force", action="store_true",
                   help="re-download papers already fetched")
    p.add_argument("--no-dedup", action="store_true",
                   help="do not skip papers already in the search index")
    args = p.parse_args(argv)

    projects = set(args.project) if args.project else None
    if args.cmd == "gather":
        recs = gather(projects, not args.no_dedup)
        save_ckpt(recs)
        print_summary(recs)
        return 0
    if args.cmd in ("resolve", "download"):
        recs = load_ckpt()
        if not recs:
            print("no checkpoint; run gather first", file=sys.stderr)
            return 2
        (resolve if args.cmd == "resolve" else
         lambda r: download(r, args.force))(recs)
        print_summary(recs)
        return 0

    recs = load_ckpt() or gather(projects, not args.no_dedup)
    save_ckpt(recs)
    resolve(recs)
    download(recs, args.force)
    print_summary(recs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
