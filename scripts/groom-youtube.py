#!/usr/bin/env python3
"""Groom the YouTube transcript backlog down to conference/lecture talks.

The backlog (`imports/youtube-backlog.json`) is built by `import-youtube.py
enqueue`, which expands playlists and channels wholesale. That sweep picks up
material a transcript corpus has no use for: channel trailers, teasers, course
administrivia, customer testimonials and product marketing. Fetching those costs
real time, because this IP is limited to roughly 20 transcripts a day.

Grooming runs in two steps so the judgement stays reviewable:

    groom-youtube.py fetch              # video metadata -> imports/youtube-meta.json
    groom-youtube.py apply --dry-run    # what would be dropped, and why
    groom-youtube.py apply              # mark them `skipped` in the backlog

`fetch` is safe to run while transcripts are blocked. The ban is on YouTube's
`timedtext` endpoint; the metadata the player API returns is not rate-limited
the same way, so durations can be collected even on a day when no transcript
can be. Results are cached, so a re-run costs nothing for videos already seen.

`apply` only ever moves `pending` -> `skipped`, never the reverse and never
`done`. `skipped` is the importer's own terminal state for "do not retry", so a
groomed video is simply one `run` will not pick up. Every drop records its
reason in the entry's `error` field, which `import-youtube.py status --errors`
prints — so the decision can be audited and, if wrong, reverted by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKLOG = ROOT / "imports" / "youtube-backlog.json"
META = ROOT / "imports" / "youtube-meta.json"

# A talk is worth a transcript; a ten-minute clip almost never is.
MIN_SECONDS = 600

# …except when the clip is one numbered part of a lecture or tutorial series,
# where a short part is still talk content and dropping it leaves a hole in the
# middle of a course. A flat 10-minute bar would have cut "Multi Dimensional
# Process Analysis - 3 - Detecting Emergent Dynamics" (9m32s) out of a BPM 2022
# tutorial while keeping parts 1, 2, 4 and 5. Series parts get a lower floor,
# below which they are stubs rather than content.
MIN_SERIES_SECONDS = 180
_SERIES = re.compile(
    r"\blecture\s*\d"          # "Lecture 10a", "Lecture 7.1"
    r"|\bpart\s*\d|\bpt\.?\s*\d"
    r"|\s[-–—|]\s*\d+\s*[-–—|]\s"   # "… - 3 - Detecting …"
    r"|^\s*#?\d{1,2}\s*[-–—]\s"     # "02 - Modern Analytical Database Systems"
    r"|\b(cs|cse|ee|stat)\s*\d{3}\b"
    r"|\b\d+\.\d+\s*[-–—]\s",       # "| 2021 | Lecture 7.1 - …"
    re.I)

# Matched against "<channel> — <title>", case-insensitively. Kept explicit and
# narrow: a false drop costs a talk, and the corpus is mostly academic, so a
# generic word like "intro" or "demo" would do more harm than good.
DROP_PATTERNS: list[tuple[str, str]] = [
    (r"\bcustomer (story|stories|testimonial|spotlight|success)\b", "customer marketing"),
    (r"\btestimonial\b", "customer marketing"),
    (r"\bsuccess story\b", "customer marketing"),
    (r"\bcase study:? (how|why)\b", "customer marketing"),
    (r"\bwhy (customers|companies|teams) choose\b", "customer marketing"),
    (r"\b(product|feature) (announcement|launch|release)\b", "product marketing"),
    (r"\bwhat'?s new in\b", "product marketing"),
    (r"\brelease (notes|highlights)\b", "product marketing"),
    (r"\b(sizzle|teaser|trailer|promo)\b", "promo"),
    (r"\bchannel trailer\b", "promo"),
    (r"\bwebinar:? (register|sign up)\b", "promo"),
    (r"\b(highlights|recap|wrap[- ]?up) (video|reel)\b", "promo"),
    (r"\bday \d+ (recap|highlights)\b", "promo"),
    (r"\bsentiment\b.*\b(customer|survey|report)\b", "sentiment/marketing"),
    (r"\b(shorts?|#shorts)\b", "short-form"),
    (r"\bcourse (logistics|administrivia)\b", "course admin"),
    (r"\b(welcome to|about) the channel\b", "promo"),
]
_COMPILED = [(re.compile(p, re.I), why) for p, why in DROP_PATTERNS]


def load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


# A throttled request and a dead video look identical in the exit code but mean
# opposite things: one says "ask again later", the other "never ask again". Only
# the second may inform a drop, so throttling is never cached as an answer.
_RETRYABLE = re.compile(
    r"sign in to confirm|not a bot|too many requests|http error 429"
    r"|temporarily|timeout|timed out|connection|failed to resolve", re.I)


def _ytdlp(extra: list[str], url: str, timeout: int) -> tuple[int, str, str]:
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings",
           "--socket-timeout", "20", *extra, url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    return out.returncode, out.stdout or "", out.stderr or ""


def sweep_container(url: str) -> dict[str, dict]:
    """Flat-extract a playlist or channel: one request for every video in it.

    This is the cheap path and the reason grooming is possible at all while the
    IP is throttled — a 47-video playlist costs one request instead of 47.
    """
    rc, stdout, stderr = _ytdlp(
        ["--flat-playlist", "--print", "%(id)s\t%(duration)s\t%(title)s"],
        url, timeout=300)
    got: dict[str, dict] = {}
    for line in stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0]:
            continue
        vid, dur, title = parts[0], parts[1], parts[2]
        got[vid] = {"ok": True, "duration": int(dur) if dur.isdigit() else None,
                    "channel": None, "title": title, "availability": "NA",
                    "via": "playlist"}
    if rc != 0 and not got:
        print(f"    ! {stderr.strip().splitlines()[-1][:120] if stderr.strip() else rc}")
    return got


def fetch_meta(video_id: str) -> dict:
    """One yt-dlp metadata call. Never raises — failure is a recorded state."""
    rc, stdout, stderr = _ytdlp(
        ["--skip-download", "--print",
         "%(duration)s\t%(channel)s\t%(title)s\t%(availability)s"],
        f"https://www.youtube.com/watch?v={video_id}", timeout=120)
    line = stdout.strip().splitlines()
    if rc != 0 or not line:
        err = stderr.strip().splitlines()
        msg = err[-1][:200] if err else "no output"
        return {"ok": False, "error": msg, "retryable": bool(_RETRYABLE.search(msg))}
    parts = line[0].split("\t")
    while len(parts) < 4:
        parts.append("NA")
    dur = parts[0]
    return {"ok": True, "duration": int(dur) if dur.isdigit() else None,
            "channel": parts[1], "title": parts[2], "availability": parts[3],
            "via": "video"}


def _needs_fetch(meta: dict, vid: str, force: bool) -> bool:
    if force or vid not in meta:
        return True
    m = meta[vid]
    return (not m.get("ok")) and m.get("retryable", False)


def cmd_fetch(args) -> int:
    backlog = load(BACKLOG, {"entries": {}})
    meta = load(META, {})
    entries = backlog["entries"]
    pending = {vid: e for vid, e in entries.items() if e["status"] == "pending"}

    # Cheap pass first: every playlist/channel a pending video belongs to.
    if not args.no_playlists:
        containers: list[str] = []
        for e in pending.values():
            for pl in e.get("playlists") or []:
                url = f"https://www.youtube.com/playlist?list={pl}"
                if url not in containers:
                    containers.append(url)
            hint = e.get("channel_hint")
            if hint and hint.startswith("http") and hint not in containers:
                containers.append(hint)
        print(f"sweeping {len(containers)} playlists/channels")
        for i, url in enumerate(containers, 1):
            got = sweep_container(url)
            new = sum(1 for v in got if _needs_fetch(meta, v, False))
            meta.update({v: g for v, g in got.items()
                         if _needs_fetch(meta, v, False)})
            print(f"  [{i}/{len(containers)}] +{new:4d} of {len(got):4d}  {url[-46:]}")
            META.write_text(json.dumps(meta, indent=1))

    todo = [vid for vid in pending if _needs_fetch(meta, vid, args.force)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} still need a per-video call ({len(meta)} cached)")

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for vid, got in zip(todo, pool.map(fetch_meta, todo)):
            meta[vid] = got
            done += 1
            if done % 25 == 0 or done == len(todo):
                META.write_text(json.dumps(meta, indent=1))
                print(f"  {done}/{len(todo)}")
    META.write_text(json.dumps(meta, indent=1))

    resolved = sum(1 for v in pending if meta.get(v, {}).get("ok"))
    retry = sum(1 for v in pending
                if not meta.get(v, {}).get("ok", True)
                and meta.get(v, {}).get("retryable"))
    print(f"resolved={resolved}/{len(pending)} throttled(retry later)={retry} "
          f"-> {META.relative_to(ROOT)}")
    return 0


def verdict(entry: dict, m: dict | None) -> tuple[str, str] | None:
    """Return (reason_code, detail) when the video should be dropped."""
    if m is None:
        return None
    if not m.get("ok"):
        # Throttled, not dead. Leave it pending rather than drop a talk because
        # YouTube was rate-limiting the day we asked.
        if m.get("retryable"):
            return None
        return ("unavailable", m.get("error", "metadata unavailable")[:120])

    avail = (m.get("availability") or "").lower()
    if avail in {"private", "premium_only", "subscriber_only", "needs_auth"}:
        return ("unavailable", f"availability={avail}")

    hay = f"{m.get('channel') or ''} — {m.get('title') or entry.get('title') or ''}"

    dur = m.get("duration")
    if dur is None:
        return ("unavailable", "no duration (live or removed)")
    floor = MIN_SERIES_SECONDS if _SERIES.search(hay) else MIN_SECONDS
    if dur < floor:
        return ("short", f"{dur // 60}m{dur % 60:02d}s < {floor // 60}m")

    for rx, why in _COMPILED:
        if rx.search(hay):
            return (why, f"matched /{rx.pattern}/")
    return None


def cmd_apply(args) -> int:
    backlog = load(BACKLOG, {"entries": {}})
    meta = load(META, {})
    entries = backlog["entries"]

    drops: list[tuple[str, str, str, str]] = []
    for vid, e in entries.items():
        if e["status"] != "pending":
            continue
        v = verdict(e, meta.get(vid))
        if v:
            title = (meta.get(vid, {}).get("title") or e.get("title") or vid)
            drops.append((vid, v[0], v[1], title))

    by_reason: dict[str, list] = {}
    for vid, reason, detail, title in drops:
        by_reason.setdefault(reason, []).append((vid, detail, title))

    for reason in sorted(by_reason, key=lambda r: -len(by_reason[r])):
        rows = by_reason[reason]
        print(f"\n=== {reason} ({len(rows)}) ===")
        for vid, detail, title in rows[: args.show]:
            print(f"  {vid}  [{detail}]  {title[:88]}")
        if len(rows) > args.show:
            print(f"  … {len(rows) - args.show} more")

    pending = sum(1 for e in entries.values() if e["status"] == "pending")
    print(f"\n{len(drops)} of {pending} pending would be dropped "
          f"-> {pending - len(drops)} remain")

    if args.dry_run:
        print("(dry run — backlog untouched)")
        return 0

    for vid, reason, detail, _ in drops:
        entries[vid]["status"] = "skipped"
        entries[vid]["error"] = f"groomed: {reason} ({detail})"
    BACKLOG.write_text(json.dumps(backlog, indent=1))
    print(f"backlog updated -> {BACKLOG.relative_to(ROOT)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="cache video metadata for pending entries")
    # Two workers is deliberate: six tripped YouTube's bot challenge partway
    # through a 694-video run and poisoned 423 entries with a fake failure.
    pf.add_argument("--workers", type=int, default=2)
    pf.add_argument("--limit", type=int)
    pf.add_argument("--force", action="store_true", help="refetch cached entries")
    pf.add_argument("--no-playlists", action="store_true",
                    help="skip the bulk playlist sweep, use per-video calls only")
    pf.set_defaults(func=cmd_fetch)

    pa = sub.add_parser("apply", help="mark non-talk videos as skipped")
    pa.add_argument("--dry-run", action="store_true")
    pa.add_argument("--show", type=int, default=12, help="examples printed per reason")
    pa.set_defaults(func=cmd_apply)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
