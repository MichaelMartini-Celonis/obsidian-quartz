"""Reclassify files sitting in the ``Literature/Inbox/`` catch-all into proper
topic folders, using the AI Gateway chat model.

The heuristic importer drops anything it can't keyword-match into ``Inbox``. This
pass reads each file's opening text and asks the LLM to pick the single best-fit
topic from the existing taxonomy plus a small set of new top-level buckets for
off-topic material (databases, graph theory, ML, cybernetics, software eng).

Usage (from ~/docs):
    scripts/.venv/bin/python -m search.reclassify_inbox            # dry-run
    scripts/.venv/bin/python -m search.reclassify_inbox --apply
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import config
from . import extract as extractmod
from .llm import ChatClient, GatewayError

INBOX_DIR = config.LITERATURE_DIR / "Inbox"

# New top-level buckets for material outside the process-mining taxonomy.
NEW_TOPICS = [
    "Databases",
    "Graph Theory and Algorithms",
    "Machine Learning",
    "Cybernetics and Systems",
    "Software Engineering",
    "Reference and Textbooks",
]

SYSTEM = (
    "You are a librarian classifying a document into exactly one topic folder for "
    "a research library focused on process mining, business processes, and data "
    "management. Choose the SINGLE best-fitting topic from the provided list. "
    "Prefer a specific existing 'Process Mining/...' or 'Process ...' topic when the "
    "document truly fits it; otherwise use one of the general buckets. "
    "Reply with a JSON object: {\"topic\": \"<exact topic string from the list>\"}."
)


def _existing_topics() -> list[str]:
    topics = []
    for d in sorted(config.LITERATURE_DIR.rglob("*")):
        if not d.is_dir():
            continue
        rel = d.relative_to(config.LITERATURE_DIR)
        s = str(rel)
        if s == "Inbox" or "(papers)" in s or s.startswith("Proceedings"):
            continue
        topics.append(s)
    return topics


def _opening_text(path: Path) -> str:
    try:
        doc = extractmod.extract_document(path)
    except Exception:
        return ""
    parts = []
    for _, t in doc.pages[:2]:
        parts.append(t)
        if sum(len(p) for p in parts) > 3000:
            break
    head = "\n".join(parts)[:3000]
    return f"TITLE: {doc.title or path.stem}\n\n{head}"


def classify_file(client: ChatClient, allowed: list[str], path: Path) -> str | None:
    text = _opening_text(path)
    if not text.strip():
        return None
    listing = "\n".join(f"- {t}" for t in allowed)
    try:
        out = client.json(
            SYSTEM,
            f"Topics:\n{listing}\n\nDocument:\n{text}",
            max_tokens=100,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[fail] {path.name}: {exc}")
        return None
    topic = (out.get("topic") or "").strip().strip("/")
    return topic if topic in allowed else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reclassify Literature/Inbox into topics")
    ap.add_argument("--apply", action="store_true", help="actually move files")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    if not INBOX_DIR.exists():
        print("no Literature/Inbox")
        return 0
    files = sorted(p for p in INBOX_DIR.rglob("*") if p.is_file()
                   and not p.name.startswith("."))
    if args.limit:
        files = files[: args.limit]

    allowed = _existing_topics() + NEW_TOPICS
    client = ChatClient()
    try:
        _ = client.token
    except GatewayError as exc:
        raise SystemExit(f"gateway unavailable: {exc}")

    moved = 0
    unresolved = []
    for path in files:
        topic = classify_file(client, allowed, path)
        if not topic:
            unresolved.append(path.name)
            print(f"[keep] {path.name}  (no confident topic)")
            continue
        dest_dir = config.LITERATURE_DIR / topic
        dest = dest_dir / path.name
        print(f"[{topic}] {path.name}")
        if args.apply:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest_dir / f"{path.stem} (dup){path.suffix}"
            shutil.move(str(path), str(dest))
            moved += 1

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] {moved if args.apply else 'would move'} files, "
          f"{len(unresolved)} kept in Inbox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
