# Topic Proposal / Summary: Agent-in-the-Loop Discovery of Objects, Events, Processes, and Relationships

*The art of exploration is to preserve order amid change and to preserve change amid order.*


Enterprise systems such as SAP and Oracle persist operational reality in relational schemas—tables, foreign keys, and transactional change histories—yet the abstractions that object-centric process mining (OCPM) actually needs (objects, events, processes, and relationships, "OER") are never stored explicitly. They must be *discovered* from raw data. Fahland et al. showed that forcing the multi-artifact behavior of an ERP process such as Order-to-Cash into a single case identifier produces divergence and convergence, obscuring the very unusual flows analysts care about; their artifact-centric pipeline instead discovers business objects, their life-cycles, and their interactions from schema and change data.1 The same challenge is studied, in different communities and largely in isolation, as ontology learning from relational databases (BURR, RODI),2 ontology-based data access (Ontop, virtual knowledge graphs),3 relational profiling and foreign-key/join discovery (Metanome),4 and change exploration over time.5

As Celonis shifts toward an agentic paradigm—where the Context Model, object-centric event data, and profiling are core platform capabilities—there is a unique opportunity to redefine this discovery problem. Instead of relying on fixed, semi-automatic extraction pipelines, we can treat agents as iterative actors that **explore raw database extracts**: probing tables with formal profiling and mining tools, hypothesizing objects and relationships, validating them against ontology-learning and OBDA criteria, and refining their proposals under analyst prompts and existing model context. The goal is grounded in the original research challenge of discovering interacting artifacts from ERP systems,1 extended with the practical toolchain an agent needs to move up the abstraction ladder—from flat relational models6 to the richer entity-relationship semantics they encode,7 the hierarchical structure ontology learning targets,2 and, crucially for OCPM, the temporality and change that connect data to objects over time.5,8

## The Research Gap

A major gap exists between structural database exploration and the semantic OER abstractions OCPM requires:

- **Fixed, disconnected pipelines:** Artifact discovery from ERP data is semi-automatic and hard-wired; it does not iterate on missing foreign keys, semantic joins, schema heterogeneity (SAP vs. Oracle), or analyst intent, and it is disconnected from the profiling, ontology-learning, and OBDA tools that address the same sub-problems.1,2,3,4
- **Abstraction mismatch:** Relational schemas are only the storage layer; the real semantics are richer (entity-relationship), hierarchical, and evolving. Naively mapping tables to concepts yields semantically weak models, and elevation beyond flat relations is a research challenge in its own right.2,6,7
- **Change, temporality, and evaluation:** Object-centric analysis depends on *how objects and relationships change over time*, but change exploration is studied separately from schema profiling, and there is no benchmark to test whether an agent actually discovers correct OER structure—versus hallucinating plausible-sounding objects and relationships.5,8

## Research Objectives

The objective of this thesis is to conceptualize and build an agent-driven framework for discovering objects, events, processes, and relationships from raw ERP database extracts, treating discovery as an iterative, tool-grounded exploration loop.

### 1. Benchmark Framework & Qualitative Analysis

Develop a methodology to evaluate discovery agents on ERP-style extracts. This includes:

- Defining "OER discovery quality" for the agentic setting, drawing the *challenges* (not the tooling) from the ontology-learning field—the impedance mismatch, N-to-M tables, and record-as-concept cases articulated by benchmarks such as BURR and RODI.2
- Creating a benchmark on ERP-style data (simplified Order-to-Cash, synthetic multi-artifact schemas, sanitized samples) where ground truth is known or expert-approximated.1
- Conducting a qualitative study comparing agent-discovered OER models against the semi-automatic artifact-centric baseline and against direct LLM schema interpretation.1

### 2. Tooling for Agent-Driven OER Discovery

Design an "Agentic Toolbox" and, as a central research question, **discover which agent tools actually answer the challenges the ontology-learning literature outlines**:

- Implementing functions that let agents probe extracts with deterministic profiling—foreign-key, unique-column, and inclusion-dependency discovery, plus semantic join discovery (Metanome family).4
- Integrating change exploration so agents can query *what changed, when, and in relation to what*, linking transactional change to object life-cycles and temporal OCPM semantics.5,8
- Navigating the abstraction ladder—relational tables6 → entity-relationship elevation7 → object-centric event data—with OBDA/virtual-knowledge-graph checks (Ontop) as a validator that a hypothesized mapping is semantically consistent.3
- Exploring interfaces for agents to "explain" their discovery choices, aligning with the platform's shift toward explainable, agent-assisted analysis.

## Expected Output

The output will be primarily algorithmic and prototypical, aligned with a fast-iteration working style.

- A Python-based framework implementing the OER discovery benchmark and evaluation suite.
- An agentic prototype (leveraging the profiling/function layer) capable of iterative, tool-grounded OER discovery from ERP extracts.
- A thesis document positioning agentic OER discovery as an orchestration of existing, validated formalisms—profiling, ontology learning, OBDA, artifact-centric discovery, and change exploration—rather than a new modeling language.

---

### References

1. X. Lu, M. Nagelkerke, D. van de Wiel, D. Fahland. *Discovering Interacting Artifacts from ERP Systems.* IEEE Trans. Services Computing 8(6), 2015. EMISA 2016 extended abstract: https://ceur-ws.org/Vol-1701/paper2.pdf
2. L. Laskowski, M. Hladik, J. Portisch, F. Panse, F. Naumann. *Burr: A Benchmark for Ontology Learning from Relational Databases.* PACMMOD 3(6) / SIGMOD 2025. (RODI as prior ontology-learning/matching benchmark.)
3. D. Calvanese et al. *Ontop: Answering SPARQL Queries over Relational Databases.* Semantic Web 8(3), 2017; Calvanese & Lanti, *Designing Virtual Knowledge Graphs.*
4. T. Papenbrock, T. Bergmann, M. Finke, J. Zwiener, F. Naumann. *Data Profiling with Metanome.* PVLDB 8(12), 2015 (INDs / UCCs / FDs → FK and key discovery); Cong et al., *WarpGate: Semantic Join Discovery.*
5. T. Bleifuß et al. *Exploring Change – A New Dimension of Data Analytics.* PVLDB 12(1):85–98, 2019, https://www.vldb.org/pvldb/vol12/p85-bleifu%C3%9F.pdf; *Enabling Change Exploration* (vision), ExploreDB 2017. HPI change-exploration: https://hpi.de/en/database-group/projects/data-integration-projects/data-profiling-and-analytics/change-exploration/
6. H. Garcia-Molina, J. Ullman, J. Widom. *Database Systems: The Complete Book*, Ch. 4 "High-Level Database Models."
7. A. Deshpande. *Beyond Relations: A Case for Elevating to the Entity-Relationship Abstraction.* CIDR 2025.
8. H. Hooshyar, M. Fumagalli, M. Montali, G. Guizzardi. *Time and Relations into Focus: Ontological Foundations of Object-Centric Event Data* (gOCED); G. Li et al., *Extracting Object-Centric Event Logs to Support Process Mining on Databases*; Winkler et al., *Detecting Dynamic Relationships in Object-Centric Event Logs.*
