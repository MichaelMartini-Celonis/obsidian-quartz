#!/usr/bin/env python3
"""Best-effort downloader for open-access paper PDFs into ``Inbox/``.

Reads URLs (CLI args and/or ``--file``), follows redirects, and saves anything
that is actually a PDF. Landing pages / paywalled links (ScienceDirect, IEEE,
gated Springer, ResearchGate, …) simply fail with a reason and are reported, so
you know what still needs a manual drop into ``Inbox/``.

    scripts/.venv/bin/python scripts/fetch-papers.py --file imports/paper-urls.txt
    scripts/.venv/bin/python scripts/fetch-papers.py https://arxiv.org/abs/2209.01219

Then import + index as usual:
    scripts/.venv/bin/python scripts/import-downloads.py
    scripts/.venv/bin/python -m search.cli index --roots literature
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

DOCS_ROOT = Path(__file__).resolve().parent.parent
INBOX = DOCS_ROOT / "Inbox"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
}


def normalize(url: str) -> str:
    url = url.strip()
    m = re.match(r"https?://arxiv\.org/abs/([^?#]+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    # Drop tracking / access tokens that confuse some hosts.
    url = re.sub(r"([?&])casa_token=[^&]*", r"\1", url).rstrip("?&")
    return url


def filename_for(url: str, resp: requests.Response) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^"\;]+)', cd)
    name = unquote(m.group(1)) if m else Path(urlparse(url).path).name
    name = unquote(name).strip() or "paper"
    name = re.sub(r"[^\w.\-() ]+", "_", name)
    if not name.lower().endswith(".pdf"):
        name = re.sub(r"\.(html?|ashx)$", "", name, flags=re.I) + ".pdf"
    return name


def unique_path(name: str) -> Path:
    dest = INBOX / name
    stem, suf = dest.stem, dest.suffix
    i = 2
    while dest.exists():
        dest = INBOX / f"{stem} ({i}){suf}"
        i += 1
    return dest


def fetch(url: str, session: requests.Session) -> tuple[bool, str]:
    target = normalize(url)
    try:
        r = session.get(target, headers=HEADERS, timeout=45, allow_redirects=True)
        data = r.content  # full body in memory (papers are small)
    except Exception as exc:  # noqa: BLE001
        return False, f"request error: {type(exc).__name__}: {str(exc)[:120]}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    ctype = r.headers.get("Content-Type", "").lower()
    if not ("pdf" in ctype or data[:5].startswith(b"%PDF")):
        return False, f"not a PDF (Content-Type: {ctype or 'unknown'})"
    if len(data) < 2000:
        return False, f"suspiciously small ({len(data)} bytes) — likely not a real PDF"
    dest = unique_path(filename_for(target, r))
    dest.write_bytes(data)
    return True, f"{dest.name}  ({len(data)/1024:.0f} KB)"


def read_urls(args) -> list[str]:
    urls = list(args.urls or [])
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    # de-dup preserving order
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("urls", nargs="*")
    p.add_argument("--file", help="text file with one URL per line (# comments allowed)")
    p.add_argument("--sleep", type=float, default=1.0)
    args = p.parse_args(argv)

    INBOX.mkdir(parents=True, exist_ok=True)
    urls = read_urls(args)
    if not urls:
        print("no URLs", file=sys.stderr)
        return 2

    session = requests.Session()
    saved, failed, skipped = [], [], 0
    existing = {p.name for p in INBOX.glob("*.pdf")}
    for i, url in enumerate(urls, 1):
        # Resume support: skip if a file with this basename was already fetched.
        base = re.sub(r"[^\w.\-() ]+", "_", Path(urlparse(normalize(url)).path).name)
        if base and base in existing:
            skipped += 1
            continue
        print(f"[{i}/{len(urls)}] {url}")
        ok, msg = fetch(url, session)
        if ok:
            existing.add(Path(msg.split("  (")[0]).name)
        print(("    OK  " if ok else "    --  ") + msg)
        (saved if ok else failed).append((url, msg))
        time.sleep(args.sleep)

    print(f"\n=== saved {len(saved)} PDFs to Inbox/  (skipped {skipped} already present) ===")
    print(f"=== {len(failed)} not downloadable (need manual drop) ===")
    for url, msg in failed:
        print(f"  - {url}\n      {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
