#!/usr/bin/env python3
"""Package the search index + Literature corpus into a separate Git LFS repo.

The ``~/docs`` repository holds only *code and agent skills* (the ``search/``
engine, ``scripts/``, ``.cursor/`` rules & skills). The heavy artifacts — the
built DuckDB search index and the ``Literature/`` PDF corpus — are gitignored
here and instead live in a **separate, LFS-backed git repository** so they can
be located, versioned, and cloned independently of the code.

Default data repo: ``~/docs-data`` (a sibling of ``~/docs``). Override with
``--repo PATH`` or the ``DOCS_DATA_REPO`` environment variable.

Data-repo layout
----------------
    docs-data/
      .gitattributes      # Git LFS tracking for *.pdf, *.duckdb, ...
      .gitignore
      README.md           # restore instructions
      manifest.json       # generated: sizes, hashes, code commit, index stats
      index/index.duckdb  # the DuckDB search index (checkpointed copy)
      Literature/...       # mirror of ~/docs/Literature

Commands
--------
    init      Create the data repo, install Git LFS, write .gitattributes/README.
    pack      Checkpoint the DuckDB index, mirror index + Literature, commit.
    push      git push (or print exact remote-setup commands if none is set).
    restore   Copy (or --link) the packaged index + Literature back into ~/docs.
    status    Show git status of the data repo and any drift vs. the live data.

Run via the project venv, e.g.::

    scripts/.venv/bin/python scripts/package-data.py init
    scripts/.venv/bin/python scripts/package-data.py pack
    scripts/.venv/bin/python scripts/package-data.py push
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = Path(os.environ.get("DOCS_DATA_REPO", str(DOCS_ROOT.parent / "docs-data")))

# What we package. The DuckDB index lands under index/ ; Literature is mirrored.
DB_SRC = DOCS_ROOT / "search" / "index.duckdb"
DB_REL = "index/index.duckdb"
LITERATURE_SRC = DOCS_ROOT / "Literature"
LITERATURE_REL = "Literature"

# Binary file types (present in Literature) that must go through Git LFS.
LFS_PATTERNS = [
    "*.duckdb", "*.duckdb.wal",
    "*.pdf", "*.docx", "*.doc", "*.pptx", "*.ppt", "*.xlsx", "*.xls",
    "*.epub", "*.zip", "*.gz", "*.tar", "*.png", "*.jpg", "*.jpeg",
]

GITATTRIBUTES = "\n".join(f"{p} filter=lfs diff=lfs merge=lfs -text" for p in LFS_PATTERNS) + "\n"

GITIGNORE = """\
# Transient DuckDB write-ahead log — the checkpointed .duckdb is what we store.
*.duckdb.wal
.DS_Store
"""

README_TEMPLATE = """\
# docs-data — search index + Literature corpus (Git LFS)

Companion data repository for the `~/docs` knowledge base. This repo stores the
large, regenerable/binary artifacts that are **gitignored** in the code repo:

- `index/index.duckdb` — the built DuckDB graph-RAG search index.
- `Literature/` — the source document corpus (PDFs, etc.).

All binaries are tracked with **Git LFS** (see `.gitattributes`). The `~/docs`
code repo (the `search/` engine, `scripts/`, and `.cursor/` agent skills) is
versioned separately and stays lean.

## Restore onto a machine

```bash
# 1. Clone both repos as siblings.
git clone <docs-remote>       ~/docs
git clone <this-repo-remote>  ~/docs-data     # pulls LFS objects

# 2. Put the data where the search engine expects it.
cd ~/docs
scripts/.venv/bin/python scripts/package-data.py restore            # copy
scripts/.venv/bin/python scripts/package-data.py restore --link     # or symlink
```

`restore` places `index/index.duckdb` at `~/docs/search/index.duckdb` and
`Literature/` at `~/docs/Literature/`.

## Refresh the snapshot

From `~/docs` (after re-indexing / adding literature):

```bash
scripts/.venv/bin/python scripts/package-data.py pack
scripts/.venv/bin/python scripts/package-data.py push
```

See `manifest.json` for the exact index stats, embedder model, and the `~/docs`
code commit this snapshot corresponds to.
"""


# --- shell helpers ----------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None, check: bool = True,
        capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, check=check,
        text=True, capture_output=capture,
    )


def git(repo: Path, *args: str, check: bool = True, capture: bool = False):
    return run(["git", *args], cwd=repo, check=check, capture=capture)


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def human(n: int) -> str:
    x = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            return f"{x:.1f} {unit}"
        x /= 1024
    return f"{x:.1f} TB"


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def dir_stats(path: Path) -> tuple[int, int]:
    """(total_bytes, file_count) for a directory tree."""
    total = count = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
                count += 1
            except OSError:
                pass
    return total, count


# --- commands ---------------------------------------------------------------

def cmd_init(args) -> int:
    repo: Path = args.repo
    repo.mkdir(parents=True, exist_ok=True)

    if not have("git"):
        print("error: git not found on PATH", file=sys.stderr)
        return 2
    if not have("git-lfs") and run(["git", "lfs", "version"], check=False,
                                   capture=True).returncode != 0:
        print("error: git-lfs not installed. Install it (e.g. `brew install git-lfs`) and retry.",
              file=sys.stderr)
        return 2

    if not (repo / ".git").exists():
        git(repo, "init", "-q")
        print(f"initialized empty git repo at {repo}")
    else:
        print(f"git repo already present at {repo}")

    # Enable LFS for this repo only (does not touch global config).
    git(repo, "lfs", "install", "--local")

    _write_if_changed(repo / ".gitattributes", GITATTRIBUTES)
    _write_if_changed(repo / ".gitignore", GITIGNORE)
    _write_if_changed(repo / "README.md", README_TEMPLATE)
    (repo / "index").mkdir(exist_ok=True)

    print("Git LFS tracking:")
    for p in LFS_PATTERNS:
        print(f"  {p}")
    print(f"\nData repo ready at {repo}")
    print("Next: scripts/.venv/bin/python scripts/package-data.py pack")
    return 0


def _write_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text() == content:
        return
    path.write_text(content)
    print(f"wrote {path.name}")


def _checkpoint_db() -> None:
    """Merge the WAL into the single .duckdb file so the copy is self-contained."""
    if not DB_SRC.exists():
        return
    try:
        import duckdb  # provided by the project venv
    except ImportError:
        print("warning: duckdb not importable; copying index.duckdb without an explicit checkpoint",
              file=sys.stderr)
        return
    try:
        con = duckdb.connect(str(DB_SRC))
        con.execute("CHECKPOINT")
        con.close()
        print("checkpointed index.duckdb (WAL merged)")
    except Exception as exc:  # pragma: no cover - best effort
        print(f"warning: could not checkpoint the DuckDB index ({exc}); copying as-is",
              file=sys.stderr)


def _mirror(src: Path, dst: Path, dry_run: bool) -> None:
    """Mirror src -> dst (dst becomes an exact copy). Prefers rsync."""
    dst.mkdir(parents=True, exist_ok=True)
    if have("rsync"):
        cmd = ["rsync", "-a", "--delete", "--exclude", ".DS_Store"]
        if dry_run:
            cmd += ["-n", "-v"]
        # Trailing slashes: copy the *contents* of src into dst.
        cmd += [f"{src}/", f"{dst}/"]
        run(cmd)
        return
    # Fallback: stdlib copy (no deletion of stray files).
    if dry_run:
        print(f"[dry-run] would copy tree {src} -> {dst}")
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _build_manifest(repo: Path) -> dict:
    manifest: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(DOCS_ROOT),
    }
    # Code repo commit this snapshot corresponds to.
    res = git(DOCS_ROOT, "rev-parse", "HEAD", check=False, capture=True)
    if res.returncode == 0:
        manifest["code_commit"] = res.stdout.strip()

    db = repo / DB_REL
    if db.exists():
        manifest["index"] = {
            "path": DB_REL,
            "bytes": db.stat().st_size,
            "size_human": human(db.stat().st_size),
            "sha256": sha256_file(db),
        }
        manifest["index"].update(_index_stats(db))

    lit = repo / LITERATURE_REL
    if lit.exists():
        total, count = dir_stats(lit)
        manifest["literature"] = {
            "path": LITERATURE_REL,
            "files": count,
            "bytes": total,
            "size_human": human(total),
        }
    return manifest


def _index_stats(db: Path) -> dict:
    try:
        import duckdb
    except ImportError:
        return {}
    stats: dict = {}
    try:
        con = duckdb.connect(str(db), read_only=True)
        for key, sql in (
            ("documents", "SELECT count(*) FROM documents"),
            ("chunks", "SELECT count(*) FROM chunks"),
        ):
            try:
                stats[key] = con.execute(sql).fetchone()[0]
            except Exception:
                pass
        # Embedder model / dim live in the meta table (see search/db.py).
        for key, meta_key in (("embedder", "embedder_model"), ("embedding_dim", "embedding_dim")):
            try:
                row = con.execute("SELECT value FROM meta WHERE key=?", [meta_key]).fetchone()
                if row:
                    stats[key] = row[0]
            except Exception:
                pass
        con.close()
    except Exception:
        pass
    return stats


def cmd_pack(args) -> int:
    repo: Path = args.repo
    if not (repo / ".git").exists():
        print(f"error: no data repo at {repo}. Run `init` first.", file=sys.stderr)
        return 2

    if not DB_SRC.exists() and not LITERATURE_SRC.exists():
        print("error: neither the DuckDB index nor Literature/ exist to package.",
              file=sys.stderr)
        return 2

    # 1. Index: checkpoint then copy the single file.
    if DB_SRC.exists():
        if not args.dry_run:
            _checkpoint_db()
        (repo / "index").mkdir(parents=True, exist_ok=True)
        if args.dry_run:
            print(f"[dry-run] would copy {DB_SRC} -> {repo / DB_REL} ({human(DB_SRC.stat().st_size)})")
        else:
            shutil.copy2(DB_SRC, repo / DB_REL)
            print(f"copied index.duckdb ({human((repo / DB_REL).stat().st_size)})")
    else:
        print("note: search/index.duckdb not found — skipping index", file=sys.stderr)

    # 2. Literature: mirror the tree.
    if LITERATURE_SRC.exists():
        print(f"mirroring Literature/ -> {repo / LITERATURE_REL} ...")
        _mirror(LITERATURE_SRC, repo / LITERATURE_REL, args.dry_run)
    else:
        print("note: Literature/ not found — skipping corpus", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] no manifest written and nothing committed.")
        return 0

    # 3. Manifest.
    manifest = _build_manifest(repo)
    (repo / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("wrote manifest.json")

    # 4. Commit.
    git(repo, "add", "-A")
    status = git(repo, "status", "--porcelain", capture=True).stdout.strip()
    if not status:
        print("nothing changed since the last snapshot; no commit created.")
        return 0
    msg = args.message or _default_message(manifest)
    git(repo, "commit", "-q", "-m", msg)
    print(f"committed snapshot: {msg}")
    _print_lfs_summary(repo)
    print("\nNext: scripts/.venv/bin/python scripts/package-data.py push")
    return 0


def _default_message(manifest: dict) -> str:
    idx = manifest.get("index", {})
    lit = manifest.get("literature", {})
    parts = []
    if idx:
        parts.append(f"{idx.get('documents', '?')} docs / {idx.get('chunks', '?')} chunks")
    if lit:
        parts.append(f"{lit.get('files', '?')} literature files ({lit.get('size_human', '?')})")
    detail = "; ".join(parts) if parts else "data snapshot"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"data snapshot {stamp}: {detail}"


def _print_lfs_summary(repo: Path) -> None:
    res = git(repo, "lfs", "ls-files", check=False, capture=True)
    if res.returncode == 0:
        n = len([ln for ln in res.stdout.splitlines() if ln.strip()])
        print(f"Git LFS is tracking {n} file(s).")


def cmd_push(args) -> int:
    repo: Path = args.repo
    if not (repo / ".git").exists():
        print(f"error: no data repo at {repo}. Run `init` first.", file=sys.stderr)
        return 2

    remotes = git(repo, "remote", capture=True).stdout.split()
    if not remotes:
        print("No git remote is configured for the data repo.\n")
        print("Create a PRIVATE GitHub repo (data + LFS should not be public), then run:\n")
        print(f"  cd {repo}")
        print("  # Option A: GitHub CLI")
        print("  gh repo create <owner>/docs-data --private --source . --remote origin")
        print("  # Option B: existing empty repo")
        print("  git remote add origin git@github.com:<owner>/docs-data.git")
        print("\n  git branch -M main")
        print("  git push -u origin main   # uploads LFS objects (~4.5 GB → needs LFS data packs)")
        print("\nNote: GitHub LFS free tier is 1 GB storage / 1 GB bandwidth per month.")
        print("This corpus needs paid data packs (sold in 50 GB increments).")
        return 0

    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip()
    print(f"pushing {branch} -> {remotes[0]} (this uploads LFS objects; may take a while) ...")
    return git(repo, "push", "-u", remotes[0], branch, check=False).returncode


def cmd_restore(args) -> int:
    repo: Path = args.repo
    db_pkg = repo / DB_REL
    lit_pkg = repo / LITERATURE_REL

    if not db_pkg.exists() and not lit_pkg.exists():
        print(f"error: nothing to restore from {repo} (run pack/clone first).", file=sys.stderr)
        return 2

    # Index -> search/index.duckdb
    if db_pkg.exists():
        _place(db_pkg, DB_SRC, args.link, args.dry_run)
    # Literature/
    if lit_pkg.exists():
        if args.link:
            _place(lit_pkg, LITERATURE_SRC, link=True, dry_run=args.dry_run)
        else:
            print(f"restoring Literature/ -> {LITERATURE_SRC} ...")
            _mirror(lit_pkg, LITERATURE_SRC, args.dry_run)
    if args.dry_run:
        print("\n[dry-run] nothing written.")
    return 0


def _place(src: Path, dst: Path, link: bool, dry_run: bool) -> None:
    if dry_run:
        how = "symlink" if link else "copy"
        print(f"[dry-run] would {how} {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if link:
        if dst.is_symlink() or dst.exists():
            if dst.is_dir() and not dst.is_symlink():
                print(f"refusing to replace existing directory {dst} with a symlink", file=sys.stderr)
                return
            dst.unlink()
        dst.symlink_to(src)
        print(f"symlinked {dst} -> {src}")
    else:
        shutil.copy2(src, dst)
        print(f"copied {src.name} -> {dst}")


def cmd_status(args) -> int:
    repo: Path = args.repo
    if not (repo / ".git").exists():
        print(f"no data repo at {repo}. Run `init` to create it.")
        return 0

    print(f"data repo: {repo}")
    remotes = git(repo, "remote", "-v", capture=True).stdout.strip()
    print(f"remote(s):\n{remotes or '  (none — run push for setup instructions)'}")
    print("\ngit status:")
    print(git(repo, "status", "-s", capture=True).stdout or "  (clean)")

    # Drift vs. live data.
    print("\ndrift vs. live ~/docs data:")
    if DB_SRC.exists():
        pkg = repo / DB_REL
        live_sz = DB_SRC.stat().st_size
        if pkg.exists():
            same = pkg.stat().st_size == live_sz
            print(f"  index: live {human(live_sz)} vs packaged {human(pkg.stat().st_size)}"
                  f" {'(sizes match)' if same else '(DIFFERENT — run pack)'}")
        else:
            print(f"  index: live {human(live_sz)} — not yet packaged")
    if LITERATURE_SRC.exists():
        lt, lc = dir_stats(LITERATURE_SRC)
        pkg = repo / LITERATURE_REL
        if pkg.exists():
            pt, pc = dir_stats(pkg)
            same = (lt, lc) == (pt, pc)
            print(f"  literature: live {lc} files/{human(lt)} vs packaged {pc} files/{human(pt)}"
                  f" {'(match)' if same else '(DIFFERENT — run pack)'}")
        else:
            print(f"  literature: live {lc} files/{human(lt)} — not yet packaged")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", type=Path, default=DEFAULT_REPO,
                   help=f"data repo location (default: {DEFAULT_REPO})")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the LFS data repo").set_defaults(func=cmd_init)

    sp = sub.add_parser("pack", help="checkpoint index, mirror data, commit")
    sp.add_argument("-n", "--dry-run", action="store_true", help="show what would happen")
    sp.add_argument("-m", "--message", help="commit message (default: auto-generated)")
    sp.set_defaults(func=cmd_pack)

    sub.add_parser("push", help="push to remote or print setup instructions").set_defaults(func=cmd_push)

    sp = sub.add_parser("restore", help="place packaged data back into ~/docs")
    sp.add_argument("--link", action="store_true", help="symlink instead of copy")
    sp.add_argument("-n", "--dry-run", action="store_true", help="show what would happen")
    sp.set_defaults(func=cmd_restore)

    sub.add_parser("status", help="show repo status and drift").set_defaults(func=cmd_status)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.repo = Path(args.repo).expanduser().resolve()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
