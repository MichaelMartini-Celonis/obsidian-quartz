#!/usr/bin/env python3
"""One-way copy of the knowledge garden into a private My Drive folder.

Destination (corporate Drive for Desktop, streaming mount)::

    ~/Library/CloudStorage/GoogleDrive-m.martini@celonis.de/My Drive/m.martini/knowledge-garden/

Copies only the document trees (Literature, Internal, Outbox, Inbox,
Transcripts, notebooks, db_systems). Never copies ``Personal/`` (that would
loop with Drive pull). Skips the DuckDB index, git, venvs, ``reference/``,
and ``imports/``. Re-run anytime; rsync is incremental. Deletion on Drive is
opt-in (``--delete``).

The git project stays on the local SSD — this is a backup, not a working copy.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
DEFAULT_DEST = (
    Path.home()
    / "Library/CloudStorage/GoogleDrive-m.martini@celonis.de"
    / "My Drive"
    / "m.martini"
    / "knowledge-garden"
)
TREES = ("Literature", "Internal", "Outbox", "Inbox", "Transcripts", "notebooks", "db_systems")
RSYNC_EXCLUDES = [
    ".DS_Store",
    ".git",
    ".gitignore",
    "__pycache__",
    ".venv",
    ".venv-ocr",
]


def dest_path() -> Path:
    return Path(os.environ.get("DOCS_GDRIVE_DEST", str(DEFAULT_DEST)))


def ensure_dest(dest: Path) -> None:
    my_drive = dest.parents[1]  # …/My Drive
    if my_drive.name != "My Drive":
        raise SystemExit(f"refusing to write outside My Drive: {dest}")
    if "Shared drives" in dest.parts:
        raise SystemExit("refusing Shared Drive path — this copy must stay private")
    dest.mkdir(parents=True, exist_ok=True)


def rsync_tree(src: Path, dest_root: Path, *, delete: bool, dry_run: bool) -> int:
    if not src.exists():
        print(f"skip missing {src.name}", file=sys.stderr)
        return 0
    rsync = shutil.which("rsync")
    if not rsync:
        raise SystemExit("rsync not found")
    target = dest_root / src.name
    target.mkdir(parents=True, exist_ok=True)
    cmd = [
        rsync,
        "-rlt",
        "--progress",
        *[f"--exclude={e}" for e in RSYNC_EXCLUDES],
    ]
    if delete:
        cmd.append("--delete")
    if dry_run:
        cmd += ["-n", "--itemize-changes"]
    cmd += [f"{src}/", f"{target}/"]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest", type=Path, default=dest_path())
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delete", action="store_true",
                   help="remove Drive files that vanished locally (opt-in)")
    p.add_argument("--only", nargs="*", choices=list(TREES),
                   help="limit to named trees")
    args = p.parse_args(argv)

    dest = args.dest.expanduser().resolve()
    if not args.dry_run:
        ensure_dest(dest)
        marker = dest / ".garden-backup"
        if not marker.exists():
            marker.write_text(
                "One-way backup of ~/docs document trees. Not a working copy.\n"
                "Owner-only. Do not move to a Shared Drive.\n"
                "Does not include Personal/.\n"
            )
        print(f"dest {dest}")

    trees = args.only or list(TREES)
    rc = 0
    for name in trees:
        n = rsync_tree(DOCS / name, dest, delete=args.delete, dry_run=args.dry_run)
        rc = n or rc
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
