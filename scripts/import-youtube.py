#!/usr/bin/env python3
"""Import YouTube video transcripts into the ``Transcripts/`` collection.

Companion to the paper importer (``import-downloads.py``) and the docs/blog
importers. Transcripts land under ``~/docs/Transcripts/<Channel>/`` as markdown
with the video URL and metadata in a header, so the search engine ingests them
into the *same* index as the papers (see ``search/config.py`` — ``Transcripts``
is a first-class root).

Design (so we don't hammer / get blocked by YouTube):

  * A persistent **backlog** (``imports/youtube-backlog.json``) holds one entry
    per video with a status (``pending`` / ``done`` / ``skipped`` / ``failed``).
  * ``enqueue`` parses ``scripts/youtube-sources.txt`` (+ any URLs passed on the
    CLI), expands playlists/channels via yt-dlp (flat, metadata only), and adds
    pending entries — it never fetches transcripts.
  * ``run`` drains the backlog with a delay + jitter between videos and
    **exponential backoff** when YouTube signals blocking, so it can be left
    running in the background (see ``scripts/youtube-transcribe-bg.sh``). When
    the transcript API reports a block it retries once through yt-dlp's caption
    tracks; note both read YouTube's ``timedtext`` endpoint, so a genuine IP ban
    needs a different IP or a proxy rather than a retry.

Usage::

    scripts/.venv/bin/python scripts/import-youtube.py enqueue
    scripts/.venv/bin/python scripts/import-youtube.py status
    scripts/.venv/bin/python scripts/import-youtube.py run --max 10
    scripts/.venv/bin/python scripts/import-youtube.py run --loop   # until empty
    # then make the transcripts searchable:
    scripts/.venv/bin/python -m search.cli index --roots transcripts
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = DOCS_ROOT / "Transcripts"
IMPORTS = DOCS_ROOT / "imports"
BACKLOG_PATH = IMPORTS / "youtube-backlog.json"
SOURCES_PATH = Path(__file__).resolve().parent / "youtube-sources.txt"

PREFERRED_LANGS = ["en", "en-US", "en-GB", "de"]

# Transcript-API exceptions that mean "there will never be a transcript" — mark
# the entry skipped (don't retry) vs. "we got blocked" — back off and retry.
_BLOCK_EXC = ("RequestBlocked", "IpBlocked", "YouTubeRequestFailed", "PoTokenRequired")
_SKIP_EXC = (
    "TranscriptsDisabled", "NoTranscriptFound", "VideoUnavailable",
    "VideoUnplayable", "AgeRestricted", "InvalidVideoId",
)


# --------------------------------------------------------------------------- #
# URL parsing
# --------------------------------------------------------------------------- #

def extract_video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([0-9A-Za-z_-]{11})", url)
    return m.group(1) if m else None


def extract_playlist_id(url: str) -> str | None:
    m = re.search(r"[?&]list=([0-9A-Za-z_-]+)", url)
    pid = m.group(1) if m else None
    # Ignore the ephemeral "radio"/mix playlists which aren't enumerable.
    if pid and (pid.startswith("RD") or pid == "WL" or pid == "LL"):
        return None
    return pid


def extract_channel_url(url: str) -> str | None:
    m = re.search(r"(https?://[^/]*youtube\.com/(?:@[^/?&#]+|channel/[^/?&#]+|c/[^/?&#]+|user/[^/?&#]+))", url)
    return m.group(1) if m else None


def read_sources(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


# --------------------------------------------------------------------------- #
# Backlog
# --------------------------------------------------------------------------- #

def load_backlog() -> dict:
    if BACKLOG_PATH.exists():
        return json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))
    return {"entries": {}, "updated_at": None}


def save_backlog(backlog: dict) -> None:
    IMPORTS.mkdir(parents=True, exist_ok=True)
    backlog["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = BACKLOG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(backlog, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(BACKLOG_PATH)


def add_entry(backlog: dict, video_id: str, *, url: str | None = None,
              title: str | None = None, playlist: str | None = None,
              channel: str | None = None) -> bool:
    """Add or enrich a backlog entry. Returns True if a *new* entry was created."""
    entries = backlog["entries"]
    e = entries.get(video_id)
    new = e is None
    if new:
        e = entries[video_id] = {
            "video_id": video_id,
            "url": url or f"https://www.youtube.com/watch?v={video_id}",
            "title": title,
            "playlists": [],
            "channel_hint": channel,
            "status": "pending",
            "attempts": 0,
            "error": None,
            "path": None,
            "added_at": date.today().isoformat(),
        }
    if title and not e.get("title"):
        e["title"] = title
    if channel and not e.get("channel_hint"):
        e["channel_hint"] = channel
    if playlist and playlist not in e["playlists"]:
        e["playlists"].append(playlist)
    return new


# --------------------------------------------------------------------------- #
# yt-dlp (playlist/channel expansion + per-video metadata)
# --------------------------------------------------------------------------- #

def _ydl(opts: dict):
    from yt_dlp import YoutubeDL
    base = {"quiet": True, "no_warnings": True, "skip_download": True,
            "ignoreerrors": True, "extractor_args": {"youtubetab": {"approximate_date": ["true"]}}}
    # The caption fallback hits the same rate limit as the transcript API, so it
    # needs the same escape hatch (see `_proxy_config`).
    proxy = os.environ.get("YOUTUBE_PROXY_HTTPS") or os.environ.get("YOUTUBE_PROXY_HTTP")
    if proxy:
        base["proxy"] = proxy
    base.update(opts)
    return YoutubeDL(base)


def expand_collection(url: str) -> list[dict]:
    """Flat-expand a playlist or channel URL into [{id, title, url}] (no download)."""
    # For a channel URL, target its uploads tab explicitly.
    if extract_channel_url(url) and not re.search(r"/(videos|streams|featured|playlists)$", url):
        url = url.rstrip("/") + "/videos"
    out: list[dict] = []
    try:
        with _ydl({"extract_flat": "in_playlist"}) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! expand failed {url}: {exc}", file=sys.stderr)
        return out

    def walk(node):
        if not node:
            return
        entries = node.get("entries")
        if entries is None:
            vid = node.get("id")
            if vid and len(vid) == 11:
                out.append({"id": vid, "title": node.get("title"),
                            "url": node.get("url") or f"https://www.youtube.com/watch?v={vid}"})
            return
        for child in entries:
            walk(child)

    walk(info)
    return out


def resolve_query(query: str) -> dict | None:
    """Resolve a free-text title to a video via YouTube search (top hit)."""
    q = re.sub(r"\s*[-–—]\s*YouTube\s*$", "", query, flags=re.I).strip()
    try:
        with _ydl({"extract_flat": True}) as ydl:
            info = ydl.extract_info(f"ytsearch1:{q}", download=False, process=False)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! search failed {q!r}: {exc}", file=sys.stderr)
        return None
    entries = list((info or {}).get("entries") or [])
    if not entries:
        return None
    e = entries[0]
    return {"id": e.get("id"), "title": e.get("title"), "url": e.get("url")}


def _ytdlp_info(url: str) -> dict | None:
    try:
        with _ydl({}) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! metadata failed {url}: {exc}", file=sys.stderr)
        return None


def _meta_from_info(info: dict | None) -> dict | None:
    if not info:
        return None
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "description": (info.get("description") or "")[:1500],
        "tags": info.get("tags") or [],
    }


def fetch_metadata(url: str) -> dict | None:
    return _meta_from_info(_ytdlp_info(url))


# --------------------------------------------------------------------------- #
# youtube-transcript-api
# --------------------------------------------------------------------------- #

class BlockedError(Exception):
    """Raised when YouTube signals rate-limiting / IP blocking."""


def _proxy_config():
    """Route requests through a proxy, if one is configured.

    A YouTube transcript block is tied to the egress IP and outlasts any
    practical backoff — measured on this network, a run gets ~20 videos and then
    nothing until the next day, whatever the pacing. Changing IP is the only
    documented remedy, so honour whichever proxy the environment offers:

      YOUTUBE_PROXY_HTTP / YOUTUBE_PROXY_HTTPS   any http(s) or SOCKS proxy URL
      WEBSHARE_PROXY_USERNAME / …_PASSWORD       Webshare rotating residential

    Returns None when nothing is set, which keeps the direct path unchanged.
    """
    user = os.environ.get("WEBSHARE_PROXY_USERNAME")
    password = os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if user and password:
        from youtube_transcript_api.proxies import WebshareProxyConfig
        print("  [proxy] Webshare rotating residential")
        return WebshareProxyConfig(proxy_username=user, proxy_password=password)
    http = os.environ.get("YOUTUBE_PROXY_HTTP")
    https = os.environ.get("YOUTUBE_PROXY_HTTPS") or http
    if http or https:
        from youtube_transcript_api.proxies import GenericProxyConfig
        print(f"  [proxy] {https or http}")
        return GenericProxyConfig(http_url=http, https_url=https)
    return None


def fetch_transcript(video_id: str, langs: list[str]):
    """Return (snippets, language_code, is_generated).

    Raises BlockedError on block signals; re-raises skip-worthy exceptions.
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi(proxy_config=_proxy_config())
    try:
        tlist = api.list(video_id)
        try:
            tr = tlist.find_transcript(langs)
        except Exception:
            tr = next(iter(tlist), None)
        if tr is None:
            raise RuntimeError("no transcripts available")
        fetched = tr.fetch()
        snippets = [(s.start, s.text) for s in fetched]
        return snippets, tr.language_code, tr.is_generated
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ in _BLOCK_EXC:
            raise BlockedError(str(exc)) from exc
        raise


# --------------------------------------------------------------------------- #
# yt-dlp caption tracks (fallback when the transcript API is IP-blocked)
# --------------------------------------------------------------------------- #

_VTT_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})\s+-->")


def _pick_lang(tracks: dict, prefs: list[str]) -> str | None:
    for want in prefs:
        if not want:
            continue
        for code in tracks:
            if code == want or code.split("-")[0] == want.split("-")[0]:
                return code
    return None


def _select_caption_track(info: dict, langs: list[str]):
    """Pick (track, language_code, is_generated) out of a yt-dlp info dict.

    Manually authored subtitles beat automatic ones, and the video's own
    language beats YouTube's machine translations — the automatic-caption map
    offers ~200 translated variants of the single real track.
    """
    original = info.get("language")
    prefs = ([original] if original else []) + list(langs)
    for tracks, generated in ((info.get("subtitles") or {}, False),
                              (info.get("automatic_captions") or {}, True)):
        if not tracks:
            continue
        code = _pick_lang(tracks, prefs)
        if code is None and not generated:
            code = next(iter(tracks))
        if code:
            return tracks[code], code, generated
    return None, None, False


def _parse_json3(text: str) -> list[tuple[float, str]]:
    out = []
    for ev in (json.loads(text).get("events") or []):
        segs = ev.get("segs")
        if not segs:
            continue
        txt = "".join(s.get("utf8", "") for s in segs)
        if txt.strip():
            out.append((ev.get("tStartMs", 0) / 1000.0, txt))
    return out


def _parse_vtt(text: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    start: float | None = None
    buf: list[str] = []
    for raw in text.splitlines():
        m = _VTT_TS.match(raw.strip())
        if m:
            if start is not None and buf:
                out.append((start, " ".join(buf)))
            h, mnt, s, ms = (int(x) for x in m.groups())
            start, buf = h * 3600 + mnt * 60 + s + ms / 1000.0, []
            continue
        line = re.sub(r"<[^>]+>", "", raw).strip()
        if line and not line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            if not buf or buf[-1] != line:
                buf.append(line)
    if start is not None and buf:
        out.append((start, " ".join(buf)))
    return out


def captions_from_info(info: dict, langs: list[str]):
    """Return (snippets, language_code, is_generated) from yt-dlp caption URLs."""
    track, code, generated = _select_caption_track(info, langs)
    if not track:
        return None
    by_ext = {t.get("ext"): t.get("url") for t in track if t.get("url")}
    for ext, parse in (("json3", _parse_json3), ("vtt", _parse_vtt)):
        url = by_ext.get(ext)
        if not url:
            continue
        try:
            with _ydl({}) as ydl:
                text = ydl.urlopen(url).read().decode("utf-8", "replace")
            snippets = parse(text)
        except Exception as exc:  # noqa: BLE001
            print(f"    ! caption {ext} failed: {str(exc)[:80]}", file=sys.stderr)
            continue
        if snippets:
            return snippets, code, generated
    return None


def obtain_transcript(entry: dict, langs: list[str]):
    """Fetch a transcript, falling back to yt-dlp captions when the transcript
    API is IP-blocked. Returns (snippets, lang, is_generated, meta, via)."""
    vid, url = entry["video_id"], entry["url"]
    try:
        snippets, lang, is_generated = fetch_transcript(vid, langs)
        if not snippets:
            raise RuntimeError("empty transcript")
        return snippets, lang, is_generated, fetch_metadata(url) or {"id": vid}, "api"
    except BlockedError:
        info = _ytdlp_info(url)
        alt = captions_from_info(info, langs) if info else None
        if not alt:
            raise
        snippets, lang, is_generated = alt
        return snippets, lang, is_generated, _meta_from_info(info) or {"id": vid}, "yt-dlp"


# --------------------------------------------------------------------------- #
# Markdown writing
# --------------------------------------------------------------------------- #

def slugify(text: str, max_len: int = 120) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s.,'()&-]", "", text).replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0]
    return text or "untitled"


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def format_transcript_body(snippets: list[tuple[float, str]]) -> str:
    """Group snippets into ~timestamped paragraphs for readable, chunkable text."""
    lines: list[str] = []
    buf: list[str] = []
    buf_start = 0.0
    buf_len = 0
    for start, text in snippets:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if not buf:
            buf_start = start
        buf.append(text)
        buf_len += len(text)
        if buf_len >= 320:
            lines.append(f"[{_fmt_ts(buf_start)}] " + " ".join(buf))
            buf, buf_len = [], 0
    if buf:
        lines.append(f"[{_fmt_ts(buf_start)}] " + " ".join(buf))
    return "\n\n".join(lines)


def existing_path_for(video_id: str) -> Path | None:
    if not TRANSCRIPTS_DIR.exists():
        return None
    for p in TRANSCRIPTS_DIR.rglob(f"*[[]{video_id}[]].md"):
        return p
    return None


def write_transcript_md(meta: dict, snippets, lang: str, is_generated: bool,
                        entry: dict) -> Path:
    vid = meta.get("id") or entry["video_id"]
    url = meta.get("webpage_url") or entry["url"]
    channel = meta.get("channel") or entry.get("channel_hint") or "YouTube"
    title = meta.get("title") or entry.get("title") or vid
    up = meta.get("upload_date")
    published = f"{up[:4]}-{up[4:6]}-{up[6:8]}" if up and len(up) == 8 else "unknown"
    duration = _fmt_ts(meta["duration"]) if meta.get("duration") else "unknown"
    playlists = entry.get("playlists") or []
    pl_line = ", ".join(playlists) if playlists else "—"

    header = [
        f"# {title}",
        "",
        f"- **Video:** {url}",
        f"- **Channel:** {channel}"
        + (f" ({meta['channel_url']})" if meta.get("channel_url") else ""),
        f"- **Published:** {published}",
        f"- **Duration:** {duration}",
        f"- **Transcript language:** {lang}"
        + (" (auto-generated)" if is_generated else ""),
        f"- **Playlists:** {pl_line}",
        f"- **Video ID:** {vid}",
        "",
        f"<!-- youtube: id={vid} url={url} channel={channel!r} "
        f"published={published} lang={lang} generated={is_generated} -->",
        "",
    ]
    if meta.get("description"):
        header += ["## Description", "", meta["description"].strip(), ""]
    body = "## Transcript\n\n" + format_transcript_body(snippets) + "\n"
    content = "\n".join(header) + "\n" + body

    dest_dir = TRANSCRIPTS_DIR / slugify(channel, 60)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slugify(title)} [{vid}].md"
    dest.write_text(content, encoding="utf-8")
    return dest


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_enqueue(args) -> int:
    urls = read_sources(Path(args.sources)) + list(args.urls or [])
    if not urls:
        print("no sources; add URLs to scripts/youtube-sources.txt or pass them", file=sys.stderr)
        return 2
    backlog = load_backlog()
    n_new = 0
    playlists, channels, queries = set(), set(), []
    for u in urls:
        vid = extract_video_id(u)
        pl = extract_playlist_id(u)
        ch = extract_channel_url(u)
        if vid:
            n_new += add_entry(backlog, vid, url=f"https://www.youtube.com/watch?v={vid}")
        if pl:
            playlists.add(pl)
        if ch:
            channels.add(ch)
        if not (vid or pl or ch):
            if re.match(r"https?://", u):
                print(f"    ? unrecognized YouTube URL, skipping: {u}", file=sys.stderr)
            else:
                queries.append(u)  # free-text title -> resolve via search below
    save_backlog(backlog)

    collections = [f"https://www.youtube.com/playlist?list={p}" for p in sorted(playlists)]
    collections += sorted(channels)
    for i, curl in enumerate(collections, 1):
        print(f"[{i}/{len(collections)}] expanding {curl} …")
        vids = expand_collection(curl)
        pid = extract_playlist_id(curl)
        added = 0
        for v in vids:
            added += add_entry(backlog, v["id"], url=v.get("url"),
                               title=v.get("title"), playlist=pid)
        n_new += added
        print(f"    +{added} new ({len(vids)} in collection)")
        save_backlog(backlog)
        if i < len(collections):
            time.sleep(args.expand_sleep)

    for i, q in enumerate(queries, 1):
        print(f"[q {i}/{len(queries)}] search: {q}")
        r = resolve_query(q)
        if r and r.get("id"):
            if add_entry(backlog, r["id"], url=r.get("url"), title=r.get("title")):
                n_new += 1
            print(f"    -> {r['id']}  {r.get('title')}")
        else:
            print("    ! no result", file=sys.stderr)
        save_backlog(backlog)
        time.sleep(args.expand_sleep)

    total = len(backlog["entries"])
    pending = sum(1 for e in backlog["entries"].values() if e["status"] == "pending")
    print(f"\nBacklog: {total} videos ({pending} pending). +{n_new} added this run.")
    print(f"Wrote {BACKLOG_PATH.relative_to(DOCS_ROOT)}")
    return 0


def cmd_status(args) -> int:
    backlog = load_backlog()
    entries = backlog["entries"]
    from collections import Counter
    by = Counter(e["status"] for e in entries.values())
    print(f"backlog: {BACKLOG_PATH.relative_to(DOCS_ROOT)}")
    print(f"updated_at: {backlog.get('updated_at')}")
    print(f"total videos: {len(entries)}")
    for st in ("pending", "done", "skipped", "failed"):
        print(f"  {st:8s} {by.get(st, 0)}")
    if args.errors:
        for e in entries.values():
            if e["status"] in ("failed", "skipped") and e.get("error"):
                print(f"    [{e['status']}] {e['video_id']}: {e['error']}")
    return 0


def cmd_run(args) -> int:
    backlog = load_backlog()
    entries = backlog["entries"]
    pending = [e for e in entries.values() if e["status"] == "pending"]
    if not pending:
        print("nothing pending. Run `enqueue` first.")
        return 0
    print(f"processing up to {args.max or len(pending)} of {len(pending)} pending "
          f"(sleep {args.sleep}s +{args.jitter}s jitter){' [loop]' if args.loop else ''}")

    processed = done = skipped = failed = 0
    consecutive_blocks = 0
    backoff = args.sleep

    while True:
        pending = [e for e in entries.values() if e["status"] == "pending"]
        if not pending:
            print("backlog drained.")
            break
        if args.max and processed >= args.max:
            break
        entry = pending[0]
        vid = entry["video_id"]

        prior = existing_path_for(vid)
        if prior is not None:
            entry["status"] = "done"
            entry["path"] = str(prior.relative_to(DOCS_ROOT))
            save_backlog(backlog)
            continue

        processed += 1
        try:
            snippets, lang, is_generated, meta, via = obtain_transcript(
                entry, args.languages)
            consecutive_blocks = 0
            backoff = args.sleep
            dest = write_transcript_md(meta, snippets, lang, is_generated, entry)
            entry["status"] = "done"
            entry["path"] = str(dest.relative_to(DOCS_ROOT))
            entry["title"] = meta.get("title") or entry.get("title")
            entry["error"] = None
            done += 1
            tag = "" if via == "api" else f"  (via {via})"
            print(f"  [done] {vid}  {dest.relative_to(TRANSCRIPTS_DIR)}{tag}")
        except BlockedError as exc:
            consecutive_blocks += 1
            entry["attempts"] += 1
            backoff = min(backoff * 2 if consecutive_blocks > 1 else max(backoff, 15), 900)
            print(f"  [blocked] {vid}: {exc} — backing off {backoff:.0f}s "
                  f"(consecutive={consecutive_blocks})", file=sys.stderr)
            save_backlog(backlog)
            if consecutive_blocks >= args.max_blocks:
                print(f"  aborting after {consecutive_blocks} consecutive blocks; "
                      f"resume later with `run`.", file=sys.stderr)
                break
            time.sleep(backoff)
            continue
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            entry["attempts"] += 1
            entry["error"] = f"{name}: {exc}"[:300]
            if name in _SKIP_EXC or entry["attempts"] >= args.max_attempts:
                entry["status"] = "skipped" if name in _SKIP_EXC else "failed"
                (skipped, failed) = (skipped + 1, failed) if name in _SKIP_EXC else (skipped, failed + 1)
                print(f"  [{entry['status']}] {vid}: {entry['error']}", file=sys.stderr)
            else:
                print(f"  [retry] {vid}: {entry['error']}", file=sys.stderr)

        save_backlog(backlog)
        time.sleep(args.sleep + random.uniform(0, args.jitter))

    save_backlog(backlog)
    print(f"\nprocessed={processed} done={done} skipped={skipped} failed={failed}")
    remaining = sum(1 for e in entries.values() if e["status"] == "pending")
    print(f"pending remaining: {remaining}")
    if done:
        print("Next: scripts/.venv/bin/python -m search.cli index --roots transcripts")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enqueue", help="expand sources/playlists into the backlog")
    pe.add_argument("urls", nargs="*", help="extra URLs (in addition to the sources file)")
    pe.add_argument("--sources", default=str(SOURCES_PATH))
    pe.add_argument("--expand-sleep", type=float, default=1.5,
                    help="seconds between playlist/channel expansions")
    pe.set_defaults(func=cmd_enqueue)

    ps = sub.add_parser("status", help="show backlog counts")
    ps.add_argument("--errors", action="store_true", help="list failed/skipped reasons")
    ps.set_defaults(func=cmd_status)

    pr = sub.add_parser("run", help="fetch transcripts for pending backlog videos")
    pr.add_argument("--max", type=int, default=None, help="max videos this run (default: all)")
    pr.add_argument("--sleep", type=float, default=2.0, help="base seconds between videos")
    pr.add_argument("--jitter", type=float, default=2.0, help="extra random seconds (0..J)")
    pr.add_argument("--loop", action="store_true",
                    help="keep going until the backlog is drained")
    pr.add_argument("--languages", nargs="*", default=PREFERRED_LANGS)
    pr.add_argument("--max-attempts", type=int, default=3,
                    help="retries before marking a video failed")
    pr.add_argument("--max-blocks", type=int, default=5,
                    help="consecutive block signals before aborting the run")
    pr.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
