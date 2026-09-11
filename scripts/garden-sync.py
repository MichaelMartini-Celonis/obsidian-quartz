#!/usr/bin/env python3
"""Drive ↔ garden routing: pull Personal/Meet/Colab, push Outbox/notebooks.

One-way copy/update only. Never delete on either side unless an operation
explicitly opts in (garden backup ``--delete``). Never turn Drive objects
into public share links — ``link`` prints authenticated viewer URLs from
object IDs.

    scripts/.venv/bin/python scripts/garden-sync.py pull-personal
    scripts/.venv/bin/python scripts/garden-sync.py pull-meet --index
    scripts/.venv/bin/python scripts/garden-sync.py pull-colab
    scripts/.venv/bin/python scripts/garden-sync.py push-outbox
    scripts/.venv/bin/python scripts/garden-sync.py push-notebooks
    scripts/.venv/bin/python scripts/garden-sync.py run-all
    scripts/.venv/bin/python scripts/garden-sync.py link PATH
    scripts/.venv/bin/python scripts/garden-sync.py pull-shared --index
    scripts/.venv/bin/python scripts/garden-sync.py audit-shared
    scripts/.venv/bin/python scripts/garden-sync.py install-agent
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
IMPORTS = DOCS / "imports"
PERSONAL_DRIVE = DOCS / "Personal" / "drive"
MEET_DEST = DOCS / "Personal" / "meet"
COLAB_LOCAL = DOCS / "notebooks" / "colab"
RCLONE_CONF = Path(os.environ.get("RCLONE_CONFIG", str(DOCS / "scripts" / ".rclone.conf")))
REMOTE = os.environ.get("DOCS_MEET_RCLONE_REMOTE", "garden-meet")
LOCK = IMPORTS / ".garden-sync.lock"
LAUNCH_AGENT_LABEL = "de.mmartini.docs.garden-sync"
LAUNCH_AGENT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

MY_DRIVE = (
    Path.home()
    / "Library/CloudStorage/GoogleDrive-m.martini@celonis.de"
    / "My Drive"
)
GARDEN_BACKUP = MY_DRIVE / "m.martini" / "knowledge-garden"
COLAB_PUSH = MY_DRIVE / "Colab Notebooks" / "Knowledge Garden"

PERSONAL_EXCLUDE = (
    "m.martini/**",
    "Google Meet/**",
    "Meet Recordings/**",
    "Colab Notebooks/**",
)

# Shared-with-me design / process folders. Party photos, recordings, and
# duplicate Literature dumps stay out. Destination: Internal/shared-drive/.
SHARED_FOLDERS = (
    "BPM on CCM",
    "Engine Exchanges",
    "[PIIT] Shared Folder",
    "PMI - Shared Folder",
    "EMS 2.0",
    "000-DESIGN-DOCS",
    "PQL Team Exchange",
    "BPMN Files for PAM Integration",
    "PM-Solutions",
    "Interviews (Internal, External, GLG) - Decision Intelligence",
    "Project Sync",
    "02 Product Architecture",
    "Event Documents",
    "M07.2 Semi-automated Generator of Events SQL T-ns",
    "Object Link Hands on E@T",
    "CCO Exercise - Knowledge Vault Documents",
    "Backend",
    "Innovative Process Mining Challenge",
    "DDIA_v2-Book-Club-2025",
    "ConvertProductionModels",
)
SHARED_DEST = DOCS / "Internal" / "shared-drive"
SHARED_VIDEO_EXTS = ("mp4", "MP4", "mov", "MOV", "webm", "WEBM", "m4v", "mkv")
SHARED_EXCLUDE = (
    "*.zip",
    "*.ZIP",
    "*.dmg",
    "*.iso",
    "Casino*",
    "*Party*",
    "*Photos*",
)

MIME_URL = {
    "application/vnd.google-apps.document":
        "https://docs.google.com/document/d/{id}/edit",
    "application/vnd.google-apps.spreadsheet":
        "https://docs.google.com/spreadsheets/d/{id}/edit",
    "application/vnd.google-apps.presentation":
        "https://docs.google.com/presentation/d/{id}/edit",
    "application/vnd.google-apps.folder":
        "https://drive.google.com/drive/folders/{id}",
    "application/vnd.google-apps.colab":
        "https://colab.research.google.com/drive/{id}",
}


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
        raise SystemExit(f"No rclone config at {RCLONE_CONF}")
    r = subprocess.run(
        _rclone_base() + ["listremotes"],
        check=False, capture_output=True, text=True,
    )
    names = {ln.strip().rstrip(":") for ln in (r.stdout or "").splitlines()}
    if REMOTE not in names:
        raise SystemExit(f"rclone remote {REMOTE!r} missing in {RCLONE_CONF}")


def viewer_url(file_id: str, mime: str | None = None) -> str:
    tmpl = MIME_URL.get(mime or "")
    if tmpl:
        return tmpl.format(id=file_id)
    return f"https://drive.google.com/file/d/{file_id}/view"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def cmd_pull_personal(args) -> int:
    ensure_remote()
    dest = PERSONAL_DRIVE
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / ".source"
    if not marker.exists():
        marker.write_text(
            "My Drive working files (excluding knowledge-garden backup, Meet, Colab).\n"
            "Indexed in search/index.duckdb with internal=TRUE.\n"
            "Refresh: scripts/garden-sync.py pull-personal\n"
        )
    cmd = _rclone_base() + [
        "copy", f"{REMOTE}:", str(dest),
        "--drive-export-formats", "docx,xlsx,pptx,txt",
        "--max-size", "50M",
        "--fast-list",
        "--exclude", ".DS_Store",
    ]
    for pat in PERSONAL_EXCLUDE:
        cmd += ["--exclude", pat]
    if args.dry_run:
        cmd.append("--dry-run")
    print(" ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    n = sum(1 for p in dest.rglob("*") if p.is_file() and p.name != ".source")
    write_json(IMPORTS / "pull-personal.json", {
        "at": datetime.now(timezone.utc).isoformat(),
        "dest": str(dest),
        "files": n,
        "rc": rc,
    })
    print(f"files under Personal/drive: {n}")
    if args.index and not args.dry_run:
        rc = _index(["--roots", "personal"]) or rc
    return rc


def cmd_pull_meet(args) -> int:
    meet = DOCS / "scripts" / "sync-meet-notes.py"
    cmd = [sys.executable, str(meet), "--dest", str(MEET_DEST)]
    if args.dry_run:
        cmd.append("--dry-run")
    print(" ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    if args.index and not args.dry_run:
        rc = _index(["--db", "meet"]) or rc
    return rc


def cmd_pull_colab(args) -> int:
    ensure_remote()
    COLAB_LOCAL.mkdir(parents=True, exist_ok=True)
    cmd = _rclone_base() + [
        "copy", f"{REMOTE}:Colab Notebooks", str(COLAB_LOCAL),
        "--filter", "+ *.ipynb",
        "--filter", "- Knowledge Garden/**",
        "--filter", "- *",
        "--fast-list",
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    print(" ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    n = sum(1 for p in COLAB_LOCAL.glob("*.ipynb"))
    print(f"colab notebooks: {n}")
    if args.index and not args.dry_run:
        rc = _index(["--roots", "notebooks"]) or rc
    return rc


def _rsync_no_delete(src: Path, dest: Path, *, dry_run: bool,
                     extra_exclude: tuple[str, ...] = ()) -> int:
    if not src.exists():
        print(f"skip missing {src}", file=sys.stderr)
        return 0
    rsync = shutil.which("rsync")
    if not rsync:
        raise SystemExit("rsync not found")
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [rsync, "-rlt", "--progress", "--exclude", ".DS_Store"]
    for e in extra_exclude:
        cmd += ["--exclude", e]
    if dry_run:
        cmd += ["-n", "--itemize-changes"]
    cmd += [f"{src}/", f"{dest}/"]
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def cmd_push_outbox(args) -> int:
    dest = GARDEN_BACKUP / "Outbox"
    if "Shared drives" in dest.parts:
        raise SystemExit("refusing Shared Drive path")
    return _rsync_no_delete(DOCS / "Outbox", dest, dry_run=args.dry_run)


def cmd_push_notebooks(args) -> int:
    src = DOCS / "notebooks"
    if "Shared drives" in COLAB_PUSH.parts:
        raise SystemExit("refusing Shared Drive path")
    return _rsync_no_delete(
        src, COLAB_PUSH, dry_run=args.dry_run, extra_exclude=("colab", "colab/**"),
    )


def cmd_backup_garden(args) -> int:
    gdrive = DOCS / "scripts" / "sync-gdrive.py"
    cmd = [sys.executable, str(gdrive)]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.delete:
        cmd.append("--delete")
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def _index(extra: list[str]) -> int:
    cmd = [sys.executable, "-m", "search.cli"]
    if extra[:1] == ["--db"]:
        cmd += extra[:2] + ["index"] + extra[2:]
    else:
        cmd += ["index"] + extra
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(DOCS))


def _rclone_shared_copy(src: str, dest: Path, *, dry_run: bool,
                        extra: list[str] | None = None) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = _rclone_base() + [
        "copy", src, str(dest),
        "--drive-shared-with-me",
        "--drive-export-formats", "docx,xlsx,pptx,txt",
        "--max-size", "80M",
        "--fast-list",
        "--retries", "1",
        "--drive-skip-dangling-shortcuts",
        "--exclude", ".DS_Store",
    ]
    for ext in SHARED_VIDEO_EXTS:
        cmd += ["--exclude", f"*.{ext}"]
    for pat in SHARED_EXCLUDE:
        cmd += ["--exclude", pat]
    if extra:
        cmd += extra
    if dry_run:
        cmd.append("--dry-run")
    print(" ".join(cmd), flush=True)
    return subprocess.call(cmd)


def cmd_pull_shared(args) -> int:
    """Copy reviewed Shared-with-me document folders into Internal/shared-drive."""
    ensure_remote()
    SHARED_DEST.mkdir(parents=True, exist_ok=True)
    marker = SHARED_DEST / ".source"
    if not marker.exists():
        marker.write_text(
            "Shared-with-me design/process folders (copy/update, no delete).\n"
            "Indexed in search/index.duckdb with internal=TRUE.\n"
            "Refresh: scripts/garden-sync.py pull-shared --index\n"
            "Does not include recordings, party photos, or Literature dumps.\n"
        )
    folders = list(args.only) if getattr(args, "only", None) else list(SHARED_FOLDERS)
    rc = 0
    for name in folders:
        dest = SHARED_DEST / name
        n = _rclone_shared_copy(f"{REMOTE}:{name}", dest, dry_run=args.dry_run)
        rc = n or rc
    if args.root:
        n = _rclone_shared_copy(
            f"{REMOTE}:", SHARED_DEST / "_root",
            dry_run=args.dry_run,
            extra=["--max-depth", "1"],
        )
        rc = n or rc
    nfiles = sum(
        1 for p in SHARED_DEST.rglob("*")
        if p.is_file() and p.name != ".source"
    )
    write_json(IMPORTS / "pull-shared.json", {
        "at": datetime.now(timezone.utc).isoformat(),
        "dest": str(SHARED_DEST),
        "folders": folders,
        "root": bool(args.root),
        "files": nfiles,
        "rc": rc,
    })
    print(f"files under Internal/shared-drive: {nfiles}")
    if args.index and not args.dry_run:
        rc = _index(["--roots", "internal"]) or rc
    return rc


def cmd_run_all(args) -> int:
    IMPORTS.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK, "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("garden-sync already running", file=sys.stderr)
        return 0
    try:
        ns = argparse.Namespace(dry_run=args.dry_run, index=not args.no_index, delete=False)
        rc = 0
        for fn in (cmd_pull_personal, cmd_pull_meet, cmd_pull_colab,
                   cmd_push_outbox, cmd_push_notebooks):
            n = fn(ns)
            rc = n or rc
        return rc
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def cmd_status(args) -> int:
    def count(root: Path) -> int:
        if not root.exists():
            return 0
        return sum(1 for p in root.rglob("*") if p.is_file() and not p.name.startswith("."))

    print(f"rclone config: {RCLONE_CONF} ({'ok' if RCLONE_CONF.exists() else 'MISSING'})")
    print(f"Personal/drive: {count(PERSONAL_DRIVE)} files")
    print(f"Personal/meet:  {count(MEET_DEST)} files")
    print(f"Internal/:      {count(DOCS / 'Internal')} files")
    print(f"  shared-drive: {count(SHARED_DEST)} files")
    print(f"notebooks/colab:{count(COLAB_LOCAL)} files")
    print(f"Outbox/:        {count(DOCS / 'Outbox')} files")
    print(f"DriveFS My Drive: {MY_DRIVE.exists()}")
    print(f"LaunchAgent:    {LAUNCH_AGENT_PLIST} ({'installed' if LAUNCH_AGENT_PLIST.exists() else 'not installed'})")
    return 0


def cmd_link(args) -> int:
    ensure_remote()
    raw = args.path
    drive_path = raw
    p = Path(raw).expanduser()
    if p.exists():
        try:
            drive_path = str(p.resolve().relative_to(PERSONAL_DRIVE.resolve()))
        except ValueError:
            try:
                drive_path = str(p.resolve().relative_to(MY_DRIVE.resolve()))
            except ValueError:
                print(f"not under Personal/drive or My Drive: {p}", file=sys.stderr)
                return 2
    cmd = _rclone_base() + [
        "lsjson", f"{REMOTE}:{drive_path}", "--original", "--files-only",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # Treat as a folder or exact file; try without --files-only for folders.
        cmd = _rclone_base() + ["lsjson", f"{REMOTE}:{drive_path}", "--original"]
        r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        return r.returncode
    rows = json.loads(r.stdout or "[]")
    if not rows:
        print("no Drive object found", file=sys.stderr)
        return 1
    for row in rows[:20]:
        fid = row.get("ID") or row.get("OrigID") or ""
        mime = row.get("MimeType") or ""
        url = viewer_url(fid, mime) if fid else "(no id)"
        print(f"{row.get('Path') or row.get('Name')}")
        print(f"  id   {fid}")
        print(f"  mime {mime}")
        print(f"  url  {url}")
    return 0


def cmd_audit_shared(args) -> int:
    ensure_remote()
    cmd = _rclone_base() + [
        "lsjson", f"{REMOTE}:", "--drive-shared-with-me", "--recursive",
        "--original", "--fast-list",
    ]
    if args.dry_run:
        print(" ".join(cmd), flush=True)
        return 0
    print("listing Shared with me (metadata only)…", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode
    rows = json.loads(r.stdout or "[]")
    clusters: dict[str, list] = defaultdict(list)
    out = []
    for row in rows:
        if row.get("IsDir"):
            continue
        path = row.get("Path") or row.get("Name") or ""
        cluster = path.split("/", 1)[0] if path else "(root)"
        fid = row.get("ID") or row.get("OrigID") or ""
        mime = row.get("MimeType") or ""
        rec = {
            "path": path,
            "name": row.get("Name"),
            "size": row.get("Size"),
            "mtime": row.get("ModTime"),
            "mime": mime,
            "id": fid,
            "url": viewer_url(fid, mime) if fid else None,
            "cluster": cluster,
        }
        clusters[cluster].append(rec)
        out.append(rec)
    ranked = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
    summary = {
        "at": datetime.now(timezone.utc).isoformat(),
        "files": len(out),
        "clusters": [
            {"name": name, "files": len(items), "bytes": sum(i.get("size") or 0 for i in items)}
            for name, items in ranked[:40]
        ],
    }
    write_json(IMPORTS / "shared-with-me-summary.json", summary)
    (IMPORTS / "shared-with-me-audit.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in out)
    )
    print(f"files: {len(out)}")
    print("top clusters:")
    for name, items in ranked[:15]:
        print(f"  {len(items):5d}  {name}")
    print(f"wrote {IMPORTS / 'shared-with-me-summary.json'}")
    return 0


def cmd_install_agent(args) -> int:
    python = str((DOCS / "scripts" / ".venv" / "bin" / "python").resolve())
    script = str((DOCS / "scripts" / "garden-sync.py").resolve())
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LAUNCH_AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>{script}</string>
    <string>run-all</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{DOCS}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>RCLONE_CONFIG</key>
    <string>{RCLONE_CONF}</string>
  </dict>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{IMPORTS / 'garden-sync.log'}</string>
  <key>StandardErrorPath</key>
  <string>{IMPORTS / 'garden-sync.log'}</string>
</dict>
</plist>
"""
    if args.dry_run:
        print(plist)
        return 0
    IMPORTS.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT_PLIST.parent.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENT_PLIST.write_text(plist)
    subprocess.call(["launchctl", "unload", str(LAUNCH_AGENT_PLIST)])
    rc = subprocess.call(["launchctl", "load", str(LAUNCH_AGENT_PLIST)])
    print(f"installed {LAUNCH_AGENT_PLIST}")
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_dry(sp):
        sp.add_argument("--dry-run", action="store_true")
        return sp

    sp = add_dry(sub.add_parser("pull-personal", help="rclone My Drive → Personal/drive"))
    sp.add_argument("--index", action="store_true")
    sp.set_defaults(func=cmd_pull_personal)

    sp = add_dry(sub.add_parser("pull-meet", help="rclone Meet → Personal/meet"))
    sp.add_argument("--index", action="store_true")
    sp.set_defaults(func=cmd_pull_meet)

    sp = add_dry(sub.add_parser("pull-colab", help="rclone Colab Notebooks → notebooks/colab"))
    sp.add_argument("--index", action="store_true")
    sp.set_defaults(func=cmd_pull_colab)

    add_dry(sub.add_parser("push-outbox", help="rsync Outbox → Drive garden backup")).set_defaults(
        func=cmd_push_outbox)
    add_dry(sub.add_parser("push-notebooks", help="rsync notebooks (except colab/) → Drive")).set_defaults(
        func=cmd_push_notebooks)

    sp = add_dry(sub.add_parser("backup-garden", help="rsync garden trees → Drive (no Personal/)"))
    sp.add_argument("--delete", action="store_true")
    sp.set_defaults(func=cmd_backup_garden)

    sp = add_dry(sub.add_parser("run-all", help="pulls + pushes; lockfile; optional index"))
    sp.add_argument("--no-index", action="store_true")
    sp.set_defaults(func=cmd_run_all)

    sub.add_parser("status", help="counts and LaunchAgent state").set_defaults(func=cmd_status)

    sp = sub.add_parser("link", help="authenticated Drive URL from a local or Drive path")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_link)

    sp = add_dry(sub.add_parser(
        "pull-shared",
        help="Shared-with-me design folders → Internal/shared-drive (no videos/photos)",
    ))
    sp.add_argument("--index", action="store_true")
    sp.add_argument("--only", nargs="*", help="limit to named Drive folders")
    sp.add_argument("--root", action="store_true",
                    help="also copy root-level shared files (still no videos)")
    sp.set_defaults(func=cmd_pull_shared)

    add_dry(sub.add_parser("audit-shared", help="metadata-only Shared-with-me report")).set_defaults(
        func=cmd_audit_shared)

    add_dry(sub.add_parser("install-agent", help="install 15-minute LaunchAgent")).set_defaults(
        func=cmd_install_agent)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
