# Knowledge Repository — a living, gardened knowledge base

This directory (`~/docs`) is a **personal knowledge repository** maintained as a *living garden*: a
continuously tended collection of research literature, project documentation, and working drafts,
paired with the tooling and agent context needed to keep it organized over time.

The intent is that **any agent session rooted here (`~/docs`) has thorough, first-class access** to
the whole collection — the paper library, the Celonis Context Model documentation, and a drop-zone
for new material — rather than being confined to a single project subfolder.

> *"The art of exploration is to preserve order amid change and to preserve change amid order."*

---

## Layout

```
~/docs/                    <- single git project rooted here (git remote: MichaelMartini-Celonis/obsidian-quartz)
├── README.md              <- you are here (repository intent + agent context)
├── Inbox/                 <- DROP ZONE: put new papers/documents here to be integrated
├── Outbox/                <- authored artifacts / drafts (e.g. thesis proposals)
├── Literature/            <- the curated paper library (classified + consistently named)
├── scripts/               <- Python tooling (the Inbox importer, etc.) + its .venv
├── imports/               <- import manifests + library backups
└── reference/             <- gitignored; independent checkouts used only as reference
    └── context-model-documentation/  <- Celonis Context Model wiki (pulled separately)
```

`Literature/`, the contents of `Inbox/`, `imports/`, `reference/`, the DuckDB search index
(`search/*.duckdb`), and `scripts/.venv/` are gitignored (large binaries and independently-managed
checkouts); everything else in `~/docs` is tracked by this project. The gitignored **search index +
`Literature/` corpus** are versioned separately in a companion **Git LFS** repo at `~/docs-data`
(see *Companion data repo* under Tooling).

### `Inbox/` — the drop zone
Drop any `.pdf`, `.docx`, `.pptx`, `.epub`, `.md`, `.txt`, `.xlsx`, `.ipynb`, `.bpmn` here
(subfolders are fine). Then run the importer, which infers an `Author - Title` filename, classifies
the file into the right `Literature/` subfolder, and de-duplicates against the existing library:

```bash
cd ~/docs && scripts/.venv/bin/python scripts/import-downloads.py
```

This Inbox exists specifically so material never has to be pulled from `~/Downloads` (which is
subject to path-access restrictions — see *Agent notes* below).

### `Outbox/` — authored artifacts
Original work produced in this repository (as opposed to imported source material). Currently holds
`Outbox/thesis/` — the agent-in-the-loop thesis proposals and drafts.

### `Literature/` — the curated library
The main research collection, organized into topic folders. Key top-level areas:
`Process Mining/` (with subfolders like `Object-centric/`, `Discovery/`, `Conformance Checking/`,
`Event Log extraction/`, `Architecture/`, `AI/` …), `Process Modeling/`, `Process Querying/`,
`Proceedings/`, `Engineering/`, and `Inbox/` (unclassified fallback inside the library).

Naming convention: `Author et al. - Title.pdf`.

### `reference/context-model-documentation/`
Independent local checkout of https://github.com/celonis/context-model-documentation — the
directional wiki for the Context Model project (codename `pig-sl`): vision, architecture, component
model, decisions. It lives under the gitignored `reference/` folder, has its own `.git`, and is
**not** part of this project or the Quartz site — it only serves as reference context.
Update with `git -C ~/docs/reference/context-model-documentation pull --ff-only`.

### `scripts/` and `imports/`
`scripts/` holds the Python tooling that maintains this repository (Inbox importer and a few
historical migration helpers), with its virtualenv at `scripts/.venv/`. `imports/` holds import
manifests and library backups (e.g. `Literature-backup-*.zip`).

---

## Tooling (run from `~/docs`)

Python tooling lives in `scripts/` (virtualenv at `scripts/.venv/`):

| Command | Purpose |
|---|---|
| `scripts/.venv/bin/python scripts/import-downloads.py` | Import + classify + rename files dropped in `Inbox/` into `Literature/` (de-duplicates against the library). |
| `scripts/.venv/bin/python scripts/import-web-book.py` | Import free online HTML books (e.g. the Google SRE books) into `Literature/` as markdown (`--list` / `--only KEY`). |
| `scripts/.venv/bin/python scripts/package-data.py` | Package the DuckDB search index + `Literature/` into the companion **Git LFS** data repo (`init` / `pack` / `push` / `restore` / `status`). |

### Companion data repo (`~/docs-data`, Git LFS)

The heavy, binary artifacts — the built DuckDB search index (`search/index.duckdb`, ~1.7 GB) and the
`Literature/` corpus (~2.8 GB) — are gitignored here and instead versioned in a **separate LFS-backed
git repository** so the code + agent skills stay lean and the data can be located/cloned
independently. `scripts/package-data.py` manages it:

```bash
scripts/.venv/bin/python scripts/package-data.py init       # create ~/docs-data (+ git-lfs, .gitattributes)
scripts/.venv/bin/python scripts/package-data.py pack        # checkpoint index, mirror data, write manifest, commit
scripts/.venv/bin/python scripts/package-data.py push        # push (or print GitHub remote-setup instructions)
scripts/.venv/bin/python scripts/package-data.py restore     # on a new machine: place index + Literature back (--link to symlink)
scripts/.venv/bin/python scripts/package-data.py status      # git status + drift vs. the live data
```

The location defaults to a `~/docs-data` sibling (override with `--repo` or `DOCS_DATA_REPO`). At
~4.5 GB total, pushing to GitHub LFS requires paid data packs, and the repo should be **private**.

---

## Agent notes (context for future sessions)

- **Root a session at `~/docs`** to work across the whole repository (Literature, Inbox, Outbox,
  scripts, and the Context Model reference under `reference/`).
- **Listing gitignored/large trees:** `Literature/` and the project's `imports/` are gitignored, so
  the fast `Glob`/`Grep` tools return nothing for them. To enumerate files, use a Python walk, e.g.:
  ```bash
  python3 -c "import os;[print(os.path.join(r,f)) for r,_,fs in os.walk('Literature') for f in fs]"
  ```
  Individual files can still be read directly with the file-read tool.
- **`~/Downloads` path restriction:** an admin policy blocks shell commands whose paths traverse a
  folder named `agent-mining-data-collector-ms-copilot-studio` (a copy lives under `~/Downloads`).
  This is why the **Inbox** drop-zone exists — integrate material through `~/docs/Inbox` instead of
  reaching into Downloads.
- **Naming:** keep the `Author et al. - Title.ext` convention when adding to `Literature/`.
