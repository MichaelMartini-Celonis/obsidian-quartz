#!/usr/bin/env python3
"""Export corp Google Meet / Gemini notes into ``~/docs/Personal/meet``.

Native ``.gdoc`` stubs on Drive for Desktop are not searchable. This copies
Meet **chat transcripts** and **exports Gemini/Docs notes** via rclone
(``garden-meet`` in ``scripts/.rclone.conf``). Videos are excluded.

Then index separately from papers::

    scripts/.venv/bin/python -m search.cli --db meet index
    scripts/.venv/bin/python -m search.cli --db meet search "event handling"
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
DEST = DOCS / "Personal" / "meet"
RCLONE_CONF = Path(os.environ.get("RCLONE_CONFIG", str(DOCS / "scripts" / ".rclone.conf")))
REMOTE = os.environ.get("DOCS_MEET_RCLONE_REMOTE", "garden-meet")
FOLDERS = (
    ("Meet Recordings", "meet-recordings"),
    ("Google Meet", "google-meet"),
)
VIDEO_EXTS = ("mp4", "MP4", "mov", "MOV", "webm", "WEBM", "gdrive")


def _rclone() -> str:
    exe = shutil.which("rclone")
    if not exe:
        raise SystemExit("rclone not found; brew install rclone")
    return exe


def _rclone_base() -> list[str]:
    cmd = [_rclone()]
    if RCLONE_CONF.exists():
        cmd += ["--config", str(RCLONE_CONF)]
    return cmd


def ensure_remote() -> None:
    if not RCLONE_CONF.exists():
        raise SystemExit(
            f"No rclone config at {RCLONE_CONF}.\n"
            "Create a read-only Drive remote named garden-meet:\n"
            f"  RCLONE_CONFIG={RCLONE_CONF} rclone config create {REMOTE} drive "
            "scope drive.readonly config_shared_client_id true config_is_local true "
            "--non-interactive\n"
            "Complete the browser login, then re-run this script."
        )
    r = subprocess.run(
        _rclone_base() + ["listremotes"],
        check=False, capture_output=True, text=True,
    )
    names = {ln.strip().rstrip(":") for ln in (r.stdout or "").splitlines()}
    if REMOTE not in names:
        raise SystemExit(f"rclone remote {REMOTE!r} missing in {RCLONE_CONF}")


def copy_folder(drive_name: str, dest_sub: str, *, dest_root: Path, dry_run: bool) -> int:
    dest = dest_root / dest_sub
    dest.mkdir(parents=True, exist_ok=True)
    cmd = _rclone_base() + [
        "copy",
        f"{REMOTE}:{drive_name}",
        str(dest),
        "--drive-export-formats", "txt",
        "--max-size", "8M",
        "--fast-list",
    ]
    for ext in VIDEO_EXTS:
        cmd += ["--exclude", f"*.{ext}"]
    if dry_run:
        cmd.append("--dry-run")
    print(" ".join(cmd), flush=True)
    env = os.environ.copy()
    env["RCLONE_CONFIG"] = str(RCLONE_CONF)
    return subprocess.call(cmd, env=env)


def suffix_chat_transcripts(root: Path) -> int:
    """Meet chat exports often have no extension; the indexer only reads .txt/.md."""
    n = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith(".") or path.suffix:
            continue
        dest = path.with_suffix(".txt")
        if dest.exists():
            continue
        path.rename(dest)
        n += 1
    return n


def count_text_files(root: Path) -> int:
    n = 0
    if not root.exists():
        return 0
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".txt", ".md", ".docx"} and not p.name.startswith("."):
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dest", type=Path, default=DEST)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    dest: Path = args.dest.expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / ".source"
    if not marker.exists():
        marker.write_text(
            "Exported Google Meet / Gemini notes and chat transcripts.\n"
            "Not a working copy of Drive. Re-run scripts/sync-meet-notes.py.\n"
            "Indexed with: python -m search.cli --db meet index\n"
        )

    ensure_remote()
    rc = 0
    for drive_name, sub in FOLDERS:
        n = copy_folder(drive_name, sub, dest_root=dest, dry_run=args.dry_run)
        rc = n or rc
    if not args.dry_run:
        renamed = suffix_chat_transcripts(dest)
        if renamed:
            print(f"renamed {renamed} extensionless chat transcripts to .txt")
    print(f"text files under {dest}: {count_text_files(dest)}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
