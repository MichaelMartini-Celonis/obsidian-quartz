#!/usr/bin/env python3
"""Import free, online HTML books into the ``Literature/`` library as markdown.

Some canonical references (e.g. the Google SRE books) are published only as
per-chapter HTML. This tool walks a book's table-of-contents page, fetches each
chapter, converts the main content to clean markdown, and writes **one markdown
file per book** into ``Literature/`` — so the search engine can ingest them like
any other document.

Books are registered in ``BOOKS`` below. Run all, or a subset with ``--only``::

    scripts/.venv/bin/python scripts/import-web-book.py                 # all
    scripts/.venv/bin/python scripts/import-web-book.py --only sre-book
    scripts/.venv/bin/python scripts/import-web-book.py --list

Requires network (the Celonis VPN is not needed; these are public sites).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests
from lxml import etree
from lxml import html as H

DOCS_ROOT = Path(__file__).resolve().parent.parent
LITERATURE = DOCS_ROOT / "Literature"
UA = {"User-Agent": "Mozilla/5.0 (compatible; docs-library-indexer/1.0)"}
TIMEOUT = 30


@dataclass
class Book:
    key: str
    title: str
    authors: str
    license: str
    toc_url: str
    link_re: str          # regex a chapter href must match (after # is stripped)
    content_xpath: str     # xpath to the main content node on a chapter page
    out_name: str          # filename under LITERATURE / folder
    folder: str = "Site Reliability Engineering"
    exclude_re: str = r"table-of-contents|/toc\.html|/index\.html$"

    def dest(self) -> Path:
        return LITERATURE / self.folder / self.out_name


BOOKS: list[Book] = [
    Book(
        key="sre-book",
        title="Site Reliability Engineering: How Google Runs Production Systems",
        authors="Betsy Beyer, Chris Jones, Jennifer Petoff, Niall Richard Murphy (eds.)",
        license="CC BY-NC-ND 4.0 — © 2017 Google, Inc. (O'Reilly)",
        toc_url="https://sre.google/sre-book/table-of-contents/",
        link_re=r"^https://sre\.google/sre-book/.+/",
        content_xpath="//div[@class='content'] | //main",
        out_name="Beyer et al. - Site Reliability Engineering.md",
    ),
    Book(
        key="workbook",
        title="The Site Reliability Workbook: Practical Ways to Implement SRE",
        authors="Betsy Beyer, Niall Richard Murphy, David K. Rensin, Kent Kawahara, Stephen Thorne (eds.)",
        license="CC BY-NC-ND 4.0 — © 2018 Google, Inc. (O'Reilly)",
        toc_url="https://sre.google/workbook/table-of-contents/",
        link_re=r"^https://sre\.google/workbook/.+/",
        content_xpath="//div[@class='content'] | //main",
        out_name="Beyer et al. - The Site Reliability Workbook.md",
    ),
    Book(
        key="bsrs",
        title="Building Secure and Reliable Systems",
        authors="Heather Adkins, Betsy Beyer, Paul Blankinship, Piotr Lewandowski, Ana Oprea, Adam Stubblefield",
        license="CC BY-NC-ND 4.0 — © 2020 Google LLC (O'Reilly)",
        toc_url="https://google.github.io/building-secure-and-reliable-systems/raw/toc.html",
        link_re=r"^https://google\.github\.io/building-secure-and-reliable-systems/raw/.+\.html$",
        content_xpath="//section[@data-type='chapter'] | //body",
        out_name="Adkins et al. - Building Secure and Reliable Systems.md",
    ),
    Book(
        key="ohdsi",
        title="The Book of OHDSI",
        authors="Observational Health Data Sciences and Informatics",
        license="CC BY 4.0 — © 2021 OHDSI",
        toc_url="https://ohdsi.github.io/TheBookOfOhdsi/",
        link_re=r"^https://ohdsi\.github\.io/TheBookOfOhdsi/[A-Za-z0-9-]+\.html$",
        content_xpath="//div[@id='content'] | //section[contains(@class,'level1')] | //main",
        out_name="OHDSI - The Book of OHDSI.md",
        folder="Clinical Informatics",
    ),
]

# Elements that are never content.
_DROP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form",
              "noscript", "svg", "button", "iframe"}
# Elements whose text is not content at all, and which therefore have to be
# removed from the tree rather than merely skipped while walking it (see
# ``strip_noise``).
_NOISE_TAGS = ("script", "style", "noscript")
# Elements that *are* the content by definition, whatever their class says. An
# element cannot be both the article and the site furniture around it, and
# Atlassian's product docs wrap the whole page body in
# ``<article class="content-with-sidebars">`` — where matching "sidebars" as a
# substring discards every page. Same failure as the two notes below, arriving
# through an ordinary semantic class name rather than a framework's.
_CONTENT_TAGS = {"article", "main"}
_BLOCK = {"p", "div", "section", "article", "header", "figcaption", "blockquote"}
# class/id substrings that mark site chrome (nav, dropdowns, cookie banners, …).
# ``nav-`` must not swallow ``nav-content``: Sphinx's ReadTheDocs theme — the
# most common Python doc theme there is — names its *content* column
# ``wy-nav-content``, and matching that drops the entire page as navigation.
_SKIP_ATTR_RE = re.compile(
    r"dropdown|expands|breadcrumb|pagination|menu|sidebar|site-?nav|"
    r"nav-(?!content)|"
    r"cookie|consent|banner|toolbar|social|share|skip-link|search-box|"
    r"footer|pager|pagination|prev-next",
    re.I,
)
# Utility-CSS classes that merely *mention* chrome. Tailwind encodes variants and
# arbitrary values in the class name itself, so a content column can legitimately
# carry `layout-wide:no-sidebar:lg:max-xl:pb-20` — matching "sidebar" as a
# substring there drops the article. Tokens holding any of these characters are
# framework utilities, never semantic role names, so they are not chrome
# evidence.
_UTILITY_TOKEN_RE = re.compile(r"[:\[\]()/&!]")


def strip_noise(node) -> None:
    """Delete ``<script>``/``<style>`` elements from a subtree, keeping tails.

    ``_emit`` already skips these tags, but every string this module reads comes
    from ``text_content()``, which walks *into* them. A server-rendered
    CSS-in-JS page (Emotion, styled-components) emits a ``<style>`` next to the
    component it styles rather than in the head, so a heading arrives as
    ``<h1>Database schema<style>.css-1afrefi{display:inline-block;…}</style></h1>``
    and the stylesheet ends up glued to the title, to table cells and to
    paragraphs alike. Removing the elements up front is the one place that fixes
    all of those at once — and it has to happen before the *title* is read, not
    just before the body is converted.
    """
    etree.strip_elements(node, *_NOISE_TAGS, with_tail=False)


def _is_chrome(el) -> bool:
    """True if the element's class/id names it as site chrome rather than content."""
    for token in ((el.get("class") or "") + " " + (el.get("id") or "")).split():
        if _UTILITY_TOKEN_RE.search(token):
            continue
        if _SKIP_ATTR_RE.search(token):
            return True
    return False


def _text(el) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", (el.text_content() or "")).strip()


def _emit(el, out: list[str], root: bool = False) -> None:
    """Recursively serialize an lxml element into markdown lines (in ``out``)."""
    tag = el.tag
    if not isinstance(tag, str):
        return
    tag = tag.lower()
    if tag in _DROP_TAGS:
        return
    # The caller already decided the root *is* the content, so the chrome tests
    # only apply below it. Otherwise one unlucky class name on the wrapper
    # discards the whole page and the importer reports "no content extracted"
    # for a source that is in fact perfectly readable.
    if not root:
        if el.get("role") == "navigation":
            return
        if tag not in _CONTENT_TAGS and el.get("role") != "main" and _is_chrome(el):
            return

    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        lvl = int(tag[1])
        t = _text(el)
        if t:
            out.append("\n" + "#" * lvl + " " + t + "\n")
        return
    if tag in {"p", "figcaption", "dt", "dd"}:
        # A paragraph flows its inline children (links/emphasis) as one block —
        # don't recurse, or inline markup fragments the sentence across lines.
        t = _text(el)
        if t:
            out.append(t)
        return
    if tag == "pre":
        code = el.text_content().rstrip("\n")
        if code.strip():
            out.append("\n```\n" + code + "\n```\n")
        return
    if tag in {"ul", "ol"}:
        ordered = tag == "ol"
        for i, li in enumerate(el.xpath("./li"), 1):
            t = _text(li)
            if t:
                out.append(f"{i}. {t}" if ordered else f"- {t}")
        out.append("")
        return
    if tag == "table":
        for tr in el.xpath(".//tr"):
            cells = [_text(c) for c in tr.xpath("./th|./td")]
            if any(cells):
                out.append(" | ".join(cells))
        out.append("")
        return
    if tag == "blockquote":
        t = _text(el)
        if t:
            out.append("\n> " + t.replace("\n", "\n> ") + "\n")
        return

    # Container: recurse into children; capture leading text.
    lead = (el.text or "").strip()
    if lead and tag in _BLOCK:
        out.append(lead)
    child_elems = [c for c in el.iterchildren() if isinstance(c.tag, str)]
    if not child_elems:
        if tag in _BLOCK:
            t = _text(el)
            if t and (not lead or t != lead):
                out.append(t)
        return
    for c in child_elems:
        _emit(c, out)
        tail = (c.tail or "").strip()
        if tail:
            out.append(tail)


def html_to_markdown(node) -> str:
    strip_noise(node)
    out: list[str] = []
    _emit(node, out, root=True)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)          # collapse blank runs
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text.strip() + "\n"


def chapter_links(session: requests.Session, book: Book) -> list[tuple[str, str]]:
    r = session.get(book.toc_url, timeout=TIMEOUT)
    r.raise_for_status()
    doc = H.fromstring(r.content)  # bytes → lxml honors the meta charset (avoids mojibake)
    doc.make_links_absolute(book.toc_url)
    keep = re.compile(book.link_re)
    drop = re.compile(book.exclude_re)
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for a in doc.xpath("//a[@href]"):
        href = a.get("href").split("#")[0]
        if keep.match(href) and not drop.search(href) and href not in seen:
            seen.add(href)
            links.append((_text(a) or href, href))
    return links


def fetch_chapter(session: requests.Session, url: str, xpath: str) -> str:
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    doc = H.fromstring(r.content)  # bytes → correct UTF-8 decoding
    nodes = doc.xpath(xpath)
    node = nodes[0] if nodes else doc.xpath("//body")[0]
    return html_to_markdown(node)


def import_book(session: requests.Session, book: Book, delay: float) -> Path:
    links = chapter_links(session, book)
    if not links:
        raise RuntimeError(f"no chapter links found for {book.key} at {book.toc_url}")
    print(f"[{book.key}] {len(links)} chapters")

    parts: list[str] = [
        f"# {book.title}",
        "",
        f"**Authors:** {book.authors}  ",
        f"**Source:** {book.toc_url}  ",
        f"**License:** {book.license}  ",
        f"**Retrieved:** {date.today().isoformat()} (imported as markdown for local search indexing)",
        "",
        "> Full text of a freely-published online book, assembled from its per-chapter HTML "
        "for offline reading and semantic search. All rights remain with the original authors/publisher.",
        "",
        "---",
        "",
    ]
    for i, (title, url) in enumerate(links, 1):
        try:
            md = fetch_chapter(session, url, book.content_xpath)
        except Exception as exc:
            print(f"  ! chapter {i} failed ({url}): {exc}", file=sys.stderr)
            continue
        parts.append(f"\n\n<!-- chapter source: {url} -->\n")
        # Only add a synthetic heading if the content doesn't already start with one.
        if not md.lstrip().startswith("#"):
            parts.append(f"## {title}\n")
        parts.append(md)
        print(f"  [{i:>2}/{len(links)}] {title[:70]}")
        if delay:
            time.sleep(delay)

    dest = book.dest()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(parts))
    kb = dest.stat().st_size / 1024
    print(f"[{book.key}] wrote {dest.relative_to(DOCS_ROOT)} ({kb:.0f} KB)")
    return dest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", metavar="KEY",
                   help=f"import only these book keys ({', '.join(b.key for b in BOOKS)})")
    p.add_argument("--delay", type=float, default=0.4, help="seconds between chapter fetches")
    p.add_argument("--list", action="store_true", help="list registered books and exit")
    args = p.parse_args(argv)

    if args.list:
        for b in BOOKS:
            print(f"{b.key:10} {b.title}\n           -> {b.dest().relative_to(DOCS_ROOT)}")
        return 0

    books = BOOKS
    if args.only:
        keys = set(args.only)
        books = [b for b in BOOKS if b.key in keys]
        if not books:
            print(f"no matching books for {args.only}", file=sys.stderr)
            return 2

    session = requests.Session()
    session.headers.update(UA)
    written = []
    for b in books:
        try:
            written.append(import_book(session, b, args.delay))
        except Exception as exc:
            print(f"[{b.key}] FAILED: {exc}", file=sys.stderr)
    print(f"\nDone. {len(written)} book(s) written under {LITERATURE.name}/{BOOKS[0].folder}/")
    print("Next: scripts/.venv/bin/python -m search.cli index --roots literature")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
