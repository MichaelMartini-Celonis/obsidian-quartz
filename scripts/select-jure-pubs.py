#!/usr/bin/env python3
"""Parse Jure Leskovec's Stanford publications page and collect the paper PDFs.

The page (https://cs.stanford.edu/people/jure/pubs/) lists every paper as
``<li class="R"><a href="...pdf">Title</a>`` grouped under ``<h2>`` section
headers (``Preprints``, then one per year). We take *all* linked paper PDFs,
resolve relative links to absolute URLs, and write them to
``imports/jure-selected.txt`` for scripts/fetch-papers.py to download.

    scripts/.venv/bin/python scripts/select-jure-pubs.py
    scripts/.venv/bin/python scripts/fetch-papers.py --file imports/jure-selected.txt
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import requests

PUBS_URL = "https://cs.stanford.edu/people/jure/pubs/"
OUT = Path("imports/jure-selected.txt")
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")}

# <h2>Section</h2> markers and <li class="R"><a href="...pdf">Title</a> entries.
TOKEN_RE = re.compile(
    r'<h2>(?P<sec>[^<]+)</h2>|'
    r'<li class="R">\s*<a href="(?P<pdf>[^"]+\.pdf)"[^>]*>(?P<title>.*?)</a>',
    re.S | re.I)


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse(html: str) -> list[dict]:
    out, section = [], "unknown"
    for m in TOKEN_RE.finditer(html):
        if m.group("sec") is not None:
            section = strip_tags(m.group("sec"))
            continue
        out.append({
            "section": section,
            "title": strip_tags(m.group("title")),
            "pdf": urljoin(PUBS_URL, m.group("pdf")),
        })
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", type=int, default=None,
                   help="optional: only sections whose year >= this (Preprints always kept)")
    args = p.parse_args(argv)

    html = requests.get(PUBS_URL, headers=HEADERS, timeout=60).text
    entries = parse(html)

    if args.since is not None:
        def keep(sec: str) -> bool:
            m = re.search(r"(19|20)\d{2}", sec)
            return (not m) or int(m.group(0)) >= args.since
        entries = [e for e in entries if keep(e["section"])]

    # de-dup by PDF URL, preserve order
    seen, uniq = set(), []
    for e in entries:
        if e["pdf"] in seen:
            continue
        seen.add(e["pdf"])
        uniq.append(e)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(e["pdf"] for e in uniq) + "\n", encoding="utf-8")

    by_sec = Counter(e["section"] for e in uniq)
    ext = sum(1 for e in uniq if not e["pdf"].startswith(PUBS_URL))
    print(f"parsed paper PDFs: {len(uniq)}  (external hosts: {ext})  -> {OUT}")
    for sec, n in sorted(by_sec.items(),
                         key=lambda x: (x[0] != "Preprints", x[0]), reverse=False):
        print(f"    {n:4d}  {sec}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
