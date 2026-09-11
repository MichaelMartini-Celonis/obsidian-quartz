#!/usr/bin/env python3
"""Maintain the gitignored ``reference/`` checkouts and their search index.

``reference/`` holds independent clones of Celonis and upstream repositories that
are used as *reference context only* — each keeps its own ``.git``, is never
committed from here, and is pulled separately. The set is declared in
``scripts/reference-repos.json`` so that adding a repository is a one-line change
rather than a remembered incantation.

Because ``reference/`` is gitignored, the fast Glob/Grep tools return nothing for
it and an agent has no way to discover what is on disk. ``index`` therefore
generates **``REFERENCE.md``** at the repository root — a tracked, high-level map
naming each checkout, what it answers, the words worth grepping for, and its
top-level directories — so a search can be aimed before it is run.

Clones are made with ``--filter=blob:none`` (partial clone): the full commit graph
is present and ``git log``/``git pull`` behave normally, but historical file
contents are fetched only when actually read. On this set that is the difference
between ~0.5 GB and ~2 GB.

Commands
--------
    list      Print the declared repositories, grouped, with on-disk status.
    clone     Clone whatever is declared but missing (idempotent).
    pull      Fast-forward every present checkout to its declared branch.
    status    Show dirty/ahead/behind state per checkout.
    index     Regenerate REFERENCE.md from the manifest + what is on disk.
    sync      clone, then pull, then index.

Run via the project venv, e.g.::

    scripts/.venv/bin/python scripts/reference-repos.py sync
    scripts/.venv/bin/python scripts/reference-repos.py clone --only celonis/architecture
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).resolve().parent / "reference-repos.json"
INDEX_OUT = DOCS_ROOT / "REFERENCE.md"

# Directory entries that say nothing about where a repo's prose lives.
SKIP_DIRS = {".git", ".github", ".idea", ".vscode", ".devcontainer", "node_modules", "__pycache__"}
DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".adoc"}


def load_manifest() -> dict:
    with MANIFEST.open() as fh:
        return json.load(fh)


def git(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True,
    )


def repo_path(root: Path, entry: dict) -> Path:
    return root / entry["path"]


def select(manifest: dict, only: list[str] | None) -> list[dict]:
    repos = manifest["repos"]
    if not only:
        return repos
    wanted = set(only)
    chosen = [r for r in repos if r["path"] in wanted or r["path"].split("/")[-1] in wanted]
    missing = wanted - {r["path"] for r in chosen} - {r["path"].split("/")[-1] for r in chosen}
    if missing:
        sys.exit(f"not declared in {MANIFEST.name}: {', '.join(sorted(missing))}")
    return chosen


# --------------------------------------------------------------------------- clone


def clone_one(root: Path, entry: dict) -> tuple[str, str]:
    dest = repo_path(root, entry)
    if (dest / ".git").exists():
        return entry["path"], "present"
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = git(
        [
            "clone", "--filter=blob:none",
            "--branch", entry["branch"],
            entry["remote"], str(dest),
        ],
        check=False,
    )
    if proc.returncode != 0:
        return entry["path"], "FAILED: " + (proc.stderr.strip().splitlines() or ["?"])[-1]
    return entry["path"], "cloned"


def cmd_clone(args, manifest: dict) -> None:
    root = DOCS_ROOT / manifest["root"]
    repos = select(manifest, args.only)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for path, result in pool.map(lambda e: clone_one(root, e), repos):
            print(f"{result:>10}  {path}")


# --------------------------------------------------------------------------- pull


def pull_one(root: Path, entry: dict) -> tuple[str, str]:
    dest = repo_path(root, entry)
    if not (dest / ".git").exists():
        return entry["path"], "missing"
    proc = git(["pull", "--ff-only"], cwd=dest, check=False)
    if proc.returncode != 0:
        return entry["path"], "FAILED: " + (proc.stderr.strip().splitlines() or ["?"])[-1]
    return entry["path"], (proc.stdout.strip().splitlines() or ["ok"])[-1][:60]


def cmd_pull(args, manifest: dict) -> None:
    root = DOCS_ROOT / manifest["root"]
    repos = select(manifest, args.only)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for path, result in pool.map(lambda e: pull_one(root, e), repos):
            print(f"{path:<52} {result}")


# --------------------------------------------------------------------------- status


def describe(root: Path, entry: dict) -> dict:
    """Everything the index needs about one checkout, or ``present: False``."""
    dest = repo_path(root, entry)
    info = {"present": (dest / ".git").exists(), "path": entry["path"]}
    if not info["present"]:
        return info
    info["branch"] = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest, check=False).stdout.strip()
    info["off_branch"] = info["branch"] != entry["branch"]
    info["commit"] = git(["rev-parse", "--short", "HEAD"], cwd=dest, check=False).stdout.strip()
    info["last_commit"] = git(
        ["log", "-1", "--format=%cs"], cwd=dest, check=False,
    ).stdout.strip()
    info["dirty"] = bool(git(["status", "--porcelain"], cwd=dest, check=False).stdout.strip())

    dirs, doc_files, total_files = [], 0, 0
    for name in sorted(os.listdir(dest)):
        if name in SKIP_DIRS:
            continue
        if (dest / name).is_dir():
            dirs.append(name + "/")
    for cur, subdirs, files in os.walk(dest):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
        for name in files:
            total_files += 1
            if Path(name).suffix.lower() in DOC_SUFFIXES:
                doc_files += 1
    info["dirs"] = dirs
    info["doc_files"] = doc_files
    info["total_files"] = total_files
    return info


def cmd_status(args, manifest: dict) -> None:
    root = DOCS_ROOT / manifest["root"]
    for entry in select(manifest, args.only):
        info = describe(root, entry)
        if not info["present"]:
            print(f"{entry['path']:<52} MISSING")
            continue
        flag = "dirty" if info["dirty"] else "clean"
        print(
            f"{entry['path']:<52} {info['branch']:<16} {info['commit']:<9} "
            f"{info['last_commit']}  {flag}  {info['doc_files']:>5} docs"
        )


def cmd_list(args, manifest: dict) -> None:
    root = DOCS_ROOT / manifest["root"]
    by_group = {g["id"]: g for g in manifest["groups"]}
    for gid, group in by_group.items():
        entries = [r for r in manifest["repos"] if r["group"] == gid]
        if not entries:
            continue
        print(f"\n## {group['title']}")
        for entry in entries:
            mark = "*" if (repo_path(root, entry) / ".git").exists() else " "
            print(f" {mark} {entry['path']:<50} {entry['what'][:80]}")


# --------------------------------------------------------------------------- index


def render_index(manifest: dict, infos: dict[str, dict]) -> str:
    root_rel = manifest["root"]
    present = [i for i in infos.values() if i["present"]]
    total_docs = sum(i["doc_files"] for i in present)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    out: list[str] = []
    w = out.append

    w("# Reference checkouts — a search map")
    w("")
    w(
        f"`{root_rel}/` holds **{len(present)} independent repository checkouts** used as reference "
        "context only. Each keeps its own `.git`, is pulled separately, and is **gitignored** by this "
        "project — so `Glob` and `Grep` return nothing for them and neither does the DuckDB search "
        "index. This file is the map that makes them findable: what each checkout answers, the words "
        "worth grepping for, and where its prose lives."
    )
    w("")
    w(
        f"Generated by `scripts/reference-repos.py index` from `scripts/reference-repos.json` "
        f"on {stamp} — {total_docs:,} documentation files across {len(present)} checkouts. "
        "Do not edit by hand."
    )
    w("")
    w("```bash")
    w("scripts/.venv/bin/python scripts/reference-repos.py sync     # clone missing, pull, regenerate this file")
    w("scripts/.venv/bin/python scripts/reference-repos.py status   # per-checkout branch / commit / dirty state")
    w("```")
    w("")
    w(
        "> **Searching them.** These trees are invisible to the repository's own tooling, so use "
        "`rg` directly and aim it with the *Ask it about* column below:"
    )
    w(">")
    w("> ```bash")
    w(f"> rg -i --glob '*.md' 'asset lock' {root_rel}/celonis/")
    w(f"> rg -il 'architecture decision' {root_rel}/celonis/architecture/")
    w("> ```")
    w(">")
    w(
        "> For a question that spans *all* of Celonis rather than these checkouts, query the "
        "**Knowledge Lake** instead — see [Knowledge Lake & DeveloperAssist](#knowledge-lake--developerassist)."
    )
    w("")
    w("---")
    w("")

    # Contents
    w("## Contents")
    w("")
    for group in manifest["groups"]:
        entries = [r for r in manifest["repos"] if r["group"] == group["id"]]
        if not entries:
            continue
        anchor = group["title"].lower().replace(" & ", "--").replace(" ", "-").replace(",", "")
        w(f"- [{group['title']}](#{anchor}) — {group['blurb']}")
    w("- [Knowledge Lake & DeveloperAssist](#knowledge-lake--developerassist) — querying Celonis knowledge that is *not* on disk.")
    w("")
    w("---")
    w("")

    for group in manifest["groups"]:
        entries = [r for r in manifest["repos"] if r["group"] == group["id"]]
        if not entries:
            continue
        w(f"## {group['title']}")
        w("")
        w(group["blurb"])
        w("")
        w("| Checkout | What it is | Ask it about |")
        w("|---|---|---|")
        for entry in entries:
            info = infos[entry["path"]]
            org, name = entry["path"].split("/", 1)
            link = f"[`{name}/`]({root_rel}/{entry['path']})"
            if not info["present"]:
                link += " ⚠️ *not cloned*"
            terms = ", ".join(f"`{t}`" for t in entry.get("ask_it_about", []))
            w(f"| {link} | {entry['what']} | {terms} |")
        w("")

        for entry in entries:
            info = infos[entry["path"]]
            if not info["present"]:
                continue
            org, name = entry["path"].split("/", 1)
            w(f"### `{name}/`")
            w("")
            branch = f"branch `{info['branch']}`"
            if info["off_branch"]:
                branch += f" ⚠️ *(declared `{entry['branch']}`)*"
            w(
                f"[{entry['remote'].removeprefix('https://github.com/')}]({entry['remote']}) · "
                f"{branch} · last commit {info['last_commit']} · "
                f"{info['doc_files']:,} doc files of {info['total_files']:,}"
            )
            w("")
            if info["dirs"]:
                w("Top level: " + " ".join(f"`{d}`" for d in info["dirs"]))
                w("")
            if entry.get("read_order"):
                w("Read order: " + " → ".join(f"`{p}`" for p in entry["read_order"]))
                w("")
            if entry.get("notes"):
                w(f"> {entry['notes']}")
                w("")
        w("---")
        w("")

    w("## Knowledge Lake & DeveloperAssist")
    w("")
    w(
        "The checkouts above are the part of Celonis knowledge that fits on a laptop. Everything "
        "else — Confluence, Jira, Slack, Google Drive, Cortex, `docs.celonis.com`, the Roadie "
        "service catalog and several hundred further GitHub repositories — is indexed by the "
        "**Knowledge Lake** (`celonis/cloud-knowledge-lake`), a Milvus-backed RAG service. Its "
        "engineering-facing profile is **DeveloperAssist**."
    )
    w("")
    w("| Surface | Where | Use it for |")
    w("|---|---|---|")
    w(
        "| Knowledge Lake MCP | `https://knowledge-lake-develop.mf.celonis.cloud/knowledge-lake/api/knowledge-retrieval/mcp/` "
        "| An agent session that needs `list_topics`, `search_knowledge`, `chat_completion`, `submit_feedback` as tools. |"
    )
    w(
        "| DeveloperAssist | Slack `#ask-developer-assist` "
        "| A one-off engineering question, no setup. |"
    )
    w(
        "| CeloAssist | Slack, company-wide "
        "| A one-off general internal question. |"
    )
    w(
        "| `search_knowledge_lake` | the `studio-mcp` MCP server, already configured "
        "| **Public** Celonis product documentation only — not internal knowledge. |"
    )
    w("")
    w(
        "Connecting the MCP server takes a token from "
        "`https://knowledge-lake-develop.mf.celonis.cloud/knowledge-lake/api/auth/login` (Microsoft SSO, "
        "24-hour lifetime) sent as `Authorization: Bearer …`. Full instructions, topic list and "
        "sharing rules are in the checkout at "
        f"`{root_rel}/celonis/cloud-knowledge-lake/docs/knowledge-lake-mcp-quick-start.md`; "
        "support is `#knowledge-lake-support`."
    )
    w("")
    w(
        "The traffic runs the other way too. "
        f"`{root_rel}/celonis/cloud-knowledge-lake/data_pipeline/config/sources/github-markdown/` "
        "registers a documentation repository as an ingestion source with about a dozen lines of "
        "YAML — `context-model-documentation` is already registered that way — so a repository worth "
        "reading here is also a candidate for being answerable through DeveloperAssist."
    )
    w("")
    return "\n".join(out) + "\n"


def cmd_index(args, manifest: dict) -> None:
    root = DOCS_ROOT / manifest["root"]
    infos = {e["path"]: describe(root, e) for e in manifest["repos"]}
    INDEX_OUT.write_text(render_index(manifest, infos))
    present = sum(1 for i in infos.values() if i["present"])
    print(f"wrote {INDEX_OUT.relative_to(DOCS_ROOT)} — {present}/{len(infos)} checkouts present")


def cmd_sync(args, manifest: dict) -> None:
    cmd_clone(args, manifest)
    print()
    cmd_pull(args, manifest)
    print()
    cmd_index(args, manifest)


def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--only", action="append", help="limit to this repo (path or bare name); repeatable")
    common.add_argument("--jobs", type=int, default=6, help="parallel git operations (default 6)")

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (
        ("list", cmd_list), ("clone", cmd_clone), ("pull", cmd_pull),
        ("status", cmd_status), ("index", cmd_index), ("sync", cmd_sync),
    ):
        sub.add_parser(name, parents=[common]).set_defaults(func=fn)

    args = parser.parse_args()
    args.func(args, load_manifest())


if __name__ == "__main__":
    main()
