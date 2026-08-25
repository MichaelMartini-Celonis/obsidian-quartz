#!/usr/bin/env python3
"""Import competitor / tool **blog** posts into ``Literature/Blogs/<Company>/``.

Companion to ``import-web-book.py`` (books) and ``import-docs.py`` (documentation).
Each registered source is a company blog; the tool discovers article URLs (from the
site's ``sitemap.xml`` or a listing page), fetches each post, converts the main
content to markdown (reusing the ``import-web-book`` converter), drops
changelogs / release notes / roadmaps / pure launch-PR posts, and writes one
markdown file per post so the search engine ingests them like any other document.

Files are grouped by company so the knowledge graph can attach a ``Company`` node
(see ``search/graph.py``). Runs are idempotent: an already-written post is skipped.

    scripts/.venv/bin/python scripts/import-blogs.py --list
    scripts/.venv/bin/python scripts/import-blogs.py                 # all sources
    scripts/.venv/bin/python scripts/import-blogs.py --only motherduck duckdb
    scripts/.venv/bin/python scripts/import-blogs.py --only gel --limit 5 --dry-run
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import requests
from lxml import html as H

DOCS_ROOT = Path(__file__).resolve().parent.parent
LITERATURE = DOCS_ROOT / "Literature"
BLOGS_DIR = LITERATURE / "Blogs"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
TIMEOUT = 40

# Reuse the battle-tested HTML->markdown converter from import-web-book.py
_spec = importlib.util.spec_from_file_location(
    "iwb", str(Path(__file__).resolve().parent / "import-web-book.py"))
_iwb = importlib.util.module_from_spec(_spec)
sys.modules["iwb"] = _iwb
_spec.loader.exec_module(_iwb)
html_to_markdown = _iwb.html_to_markdown

# Titles/slugs that mark non-substantive posts (changelogs, releases, pure PR).
DROP_RE = re.compile(
    r"(release[ -]?notes?|changelog|what'?s new in|"
    r"\bv?\d+\.\d+(\.\d+)?\b.*(release|is (now )?(live|out|available|ga))|"
    r"roadmap|is now live|now generally available|"
    r"announcing .*(community edition|driver|beta \d|alpha|\bGA\b)|"
    r"we (raised|closed).*(seed|series|funding)|"
    r"is hiring|join us at|we'?re hiring)",
    re.I,
)


@dataclass
class BlogSource:
    key: str
    company: str
    sitemap: str = ""          # sitemap.xml URL (preferred discovery)
    sitemaps: list[str] = field(default_factory=list)  # …or several (site split its blog)
    index_url: str = ""        # fallback: an HTML listing page to scrape links from
    keep_re: str = ""          # a discovered URL must match this to be an article
    drop_url_re: str = ""      # …and must NOT match this
    base: str = ""             # site origin for resolving relative links
    content_xpath: str = ""    # optional explicit content node xpath
    title_xpath: str = ""      # optional title override (sites whose first <h1> is a site header)
    min_chars: int = 500
    extra_drop: str = ""       # source-specific title-drop regex
    category_xpath: str = ""   # xpath yielding the post's own section/category labels
    drop_category_re: str = ""  # …drop the post if any of them matches


SOURCES: list[BlogSource] = [
    BlogSource(
        key="motherduck", company="MotherDuck",
        sitemap="https://motherduck.com/sitemap-0.xml",
        keep_re=r"^https://motherduck\.com/blog/[^/]+/$",
        base="https://motherduck.com",
    ),
    BlogSource(
        key="duckdb", company="DuckDB",
        sitemap="https://duckdb.org/sitemap.xml",
        keep_re=r"^https://duckdb\.org/\d{4}/\d{2}/\d{2}/[^/]+\.html$",
        base="https://duckdb.org",
    ),
    BlogSource(
        key="relationalai", company="RelationalAI",
        sitemap="https://www.relational.ai/sitemap.xml",
        keep_re=r"^https://www\.relational\.ai/post/[^/]+/?$",
        base="https://www.relational.ai",
    ),
    BlogSource(
        key="firebolt", company="Firebolt",
        sitemap="https://www.firebolt.io/sitemap.xml",
        keep_re=r"^https://www\.firebolt\.io/blog/[^/]+/?$",
        drop_url_re=r"/blog/?$|/blog/author|/blog/category",
        base="https://www.firebolt.io",
    ),
    BlogSource(
        key="gel", company="Gel",
        sitemap="https://www.geldata.com/sitemap.xml",
        keep_re=r"^https://www\.geldata\.com/blog/[^/]+/?$",
        base="https://www.geldata.com",
    ),
    BlogSource(
        key="malloy", company="Malloy",
        index_url="https://docs.malloydata.dev/blog/",
        keep_re=r"^/blog/\d{4}-\d{2}-\d{2}-[^/]+$",
        base="https://docs.malloydata.dev",
    ),
    BlogSource(
        key="bauplan", company="Bauplan",
        sitemap="https://bauplanlabs.com/sitemap.xml",
        keep_re=r"^https://bauplanlabs\.com/post/[^/]+/?$",
        base="https://bauplanlabs.com",
    ),
    BlogSource(
        key="cedardb", company="CedarDB",
        sitemap="https://cedardb.com/sitemap.xml",
        keep_re=r"^https://cedardb\.com/blog/[^/]+/$",
        base="https://cedardb.com",
    ),
    BlogSource(
        key="typedb", company="TypeDB",
        sitemap="https://typedb.com/sitemap-main.xml",
        keep_re=r"^https://typedb\.com/blog/[^/]+/?$",
        base="https://typedb.com",
    ),
    # Kuzu Inc. wound down and kuzudb.com no longer resolves; the blog survives only
    # as this GitHub Pages mirror of the site, which is now its citable home.
    BlogSource(
        key="kuzu", company="Kùzu",
        sitemap="https://kuzudb.github.io/blog/sitemap-0.xml",
        keep_re=r"^https://kuzudb\.github\.io/blog/post/[^/]+/?$",
        base="https://kuzudb.github.io",
    ),
    BlogSource(
        key="anchormodeling", company="Anchor Modeling",
        sitemap="https://www.anchormodeling.com/wp-sitemap-posts-post-1.xml",
        keep_re=r"^https://www\.anchormodeling\.com/[^/]+/$",
        base="https://www.anchormodeling.com",
    ),
    BlogSource(
        key="pavlo", company="Andy Pavlo (CMU)",
        index_url="https://www.cs.cmu.edu/~pavlo/blog/index.html",
        keep_re=r"^https://www\.cs\.cmu\.edu/~pavlo/blog/\d{4}/\d{2}/[^/]+\.html$",
        base="https://www.cs.cmu.edu", title_xpath="//title/text()",
    ),
    # Databricks runs the largest blog of any source here (~3,300 posts across the
    # current site and the 2013-2023 legacy archive) and most of it is vertical
    # marketing, exec thought-leadership or SEO glossary pages. Each post names its
    # own section in a breadcrumb, which is a far better filter than any title
    # regex: `engineering`, `platform` and `databricks-ai` carry the lakehouse /
    # Lakebase / Spark / Delta engineering writing, the four dropped sections carry
    # customer stories, partner PR, "What is X?" definitions and CxO essays.
    BlogSource(
        key="databricks", company="Databricks",
        sitemaps=["https://www.databricks.com/en-blog-assets/sitemap/sitemap-0.xml",
                  "https://www.databricks.com/blog-legacy-assets/sitemap/sitemap-0.xml"],
        keep_re=r"^https://www\.databricks\.com/blog/(?:\d{4}/\d{2}/\d{2}/[^/]+|[^/]+)$",
        drop_url_re=r"/blog/(category|author|archive)/",
        base="https://www.databricks.com",
        category_xpath='//nav[contains(@class,"blog-detail-breadcrumb")]'
                       '//a[contains(@href,"/blog/category/")]/@href',
        drop_category_re=r"/category/(company|industries|data-strategy|data-ai-foundations)\b",
        # residual PR inside the kept sections: conference, certification and
        # analyst/partner/people announcements, plus the recurring non-technical
        # series (Application Spotlight, the bi-weekly link digest, eBook launches)
        extra_drop=r"summit|keynote|re:invent|certifi|named a leader|partner awards|"
                   r"brickbuilder|brickster|^welcoming\b|databricks ventures|"
                   r"university alliance|student fellows|strategic partnership|"
                   r"webinar|\bmooc\b|best of databricks blog|most read posts|"
                   r"application spotlight|partners with|partnership with|"
                   r"(selects|chooses) databricks|\bebooks?\b|bi-weekly.*digest|"
                   r"indemnity|survey \d{4} results|spark survey",
    ),
    BlogSource(
        key="senzing", company="Senzing",
        sitemap="https://senzing.com/post-sitemap.xml",
        keep_re=r"^https://senzing\.com/[^/]+/$",
        base="https://senzing.com",
    ),
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(UA)
    return s


def _fetch_doc(session: requests.Session, url: str):
    """Fetch and parse a page, returning the document and the URL it resolved to."""
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return H.fromstring(r.content), r.url  # bytes -> lxml honors meta charset


def _redirected_off_article(url: str, final_url: str) -> bool:
    """Did a redirect walk *up* out of the article, e.g. onto the blog index?

    A site that removes a post may soft-404 it onto its listing page rather than
    returning 404. The result parses fine and is titled after whatever post is
    currently featured, so nothing downstream notices — the post is silently
    replaced by a copy of the index. Landing on an *ancestor* path is what
    identifies that, and it is the only redirect worth refusing: adding a
    trailing slash, dropping a `.html` suffix and renaming a slug are all routine
    and all keep the article.
    """
    def norm(u: str) -> str:
        return re.sub(r"\.(html?|php|aspx?)$", "", urlsplit(u).path.rstrip("/"))

    here, there = norm(url), norm(final_url)
    if here == there:
        return False
    return there in ("", "/") or here.startswith(there + "/")


def discover(session: requests.Session, src: BlogSource) -> list[str]:
    keep = re.compile(src.keep_re) if src.keep_re else None
    drop = re.compile(src.drop_url_re) if src.drop_url_re else None
    urls: list[str] = []
    sitemaps = src.sitemaps or ([src.sitemap] if src.sitemap else [])
    if sitemaps:
        for sm in sitemaps:
            r = session.get(sm, timeout=TIMEOUT)
            r.raise_for_status()
            urls += re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text)
    elif src.index_url:
        doc, _ = _fetch_doc(session, src.index_url)
        hrefs = doc.xpath("//a[@href]")
        urls = [a.get("href") for a in hrefs]
    out, seen = [], set()
    for u in urls:
        u = u.strip()
        if keep and not keep.match(u):
            continue
        if drop and drop.search(u):
            continue
        full = u if u.startswith("http") else src.base.rstrip("/") + u
        if full not in seen:
            seen.add(full)
            out.append(full)
    return sorted(out)


def _p_chars(node) -> int:
    return sum(len(p.text_content()) for p in node.xpath(".//p"))


def _pick_content(doc):
    """Pick the richest content node by total <p> text.

    Gathers <article>, <main>, and content-ish divs (prose/markdown/post/…) as
    candidates and returns the one with the most paragraph text. This is robust
    to sites (e.g. MotherDuck) that wrap the real body in a hashed-class div while
    also emitting small <article> cards for "related posts".
    """
    cands = doc.xpath(
        '//article | //main | '
        '//div[contains(@class,"prose") or contains(@class,"markdown") or '
        'contains(@class,"post-content") or contains(@class,"article-content") or '
        'contains(@class,"blog-content") or contains(@class,"post-body")]'
    )
    cands = [c for c in cands if _p_chars(c) > 0]
    if cands:
        return max(cands, key=_p_chars)
    body = doc.xpath("//body")
    return body[0] if body else doc


def _categories_of(doc, category_xpath: str) -> list[str]:
    out = []
    for node in doc.xpath(category_xpath):
        raw = node if isinstance(node, str) else node.text_content()
        raw = re.sub(r"\s+", " ", raw).strip()
        if raw and raw not in out:
            out.append(raw)
    return out


def _title_of(doc, title_xpath: str = "") -> str:
    if title_xpath:
        for node in doc.xpath(title_xpath):
            raw = node if isinstance(node, str) else node.text_content()
            # take the first segment of "Title // Blog // Site" or "Title | Site"
            t = re.split(r"\s+//\s+|\s+\|\s+", re.sub(r"\s+", " ", raw).strip())[0].strip()
            if t:
                return t
    for h in doc.xpath("//h1"):
        t = re.sub(r"\s+", " ", h.text_content()).strip()
        if t:
            return t
    t = (doc.xpath("//title/text()") or [""])[0]
    return re.sub(r"\s*[|\u2013\u2014-]\s*[^|]*$", "", t).strip()


def slugify(text: str, max_len: int = 150) -> str:
    text = re.sub(r"[^\w\s.,'()&-]", "", text).replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:max_len].rsplit(" ", 1)[0] if len(text) > max_len else text) or "untitled"


def dedup_key(stem: str) -> str:
    """Collapse a filename to what identifies the *post* rather than its spelling.

    Whether a title reaches us as ``Shouldn't`` or ``Shouldn’t`` is a property of
    the site's typography on the day it was fetched, not of the post — but
    ``slugify`` keeps the ASCII apostrophe and drops the typographic one, so the
    same article can land under two names and be imported twice. Comparing on
    letters and digits alone makes the skip-if-held check immune to that (and to
    hyphen, dash and ampersand churn) without renaming what is already filed.
    """
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def import_source(session, src: BlogSource, limit, delay, dry_run) -> dict:
    dest_dir = BLOGS_DIR / src.company
    held = {dedup_key(p.stem) for p in dest_dir.glob("*.md")} if dest_dir.is_dir() else set()
    urls = discover(session, src)
    print(f"[{src.key}] discovered {len(urls)} candidate article URLs "
          f"-> {dest_dir.relative_to(DOCS_ROOT)}")
    extra = re.compile(src.extra_drop, re.I) if src.extra_drop else None
    drop_cat = re.compile(src.drop_category_re, re.I) if src.drop_category_re else None
    kept, dropped, skipped = [], [], []
    n = 0
    for url in urls:
        if limit and n >= limit:
            break
        try:
            doc, final_url = _fetch_doc(session, url)
        except Exception as exc:
            dropped.append((url, f"fetch-fail {exc}"))
            continue
        if _redirected_off_article(url, final_url):
            dropped.append((url, f"redirected off the article -> {final_url}"))
            continue
        title = _title_of(doc, src.title_xpath)
        if not title:
            dropped.append((url, "no-title"))
            continue
        if drop_cat and src.category_xpath:
            cats = _categories_of(doc, src.category_xpath)
            hit = [c for c in cats if drop_cat.search(c)]
            if hit:
                dropped.append((title, f"category {'/'.join(hit)}"))
                continue
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if DROP_RE.search(title) or DROP_RE.search(slug) or (extra and extra.search(title)):
            dropped.append((title, "changelog/release/PR"))
            continue
        out = dest_dir / f"{slugify(title)}.md"
        if dedup_key(out.stem) in held:
            skipped.append(title)
            n += 1
            continue
        node = _pick_content(doc)
        md = html_to_markdown(node)
        if len(md) < src.min_chars:
            dropped.append((title, f"too-short ({len(md)}c)"))
            continue
        header = (f"# {title}\n\n"
                  f"Source: {src.company} blog \u2014 {url}\n\n---\n\n")
        n += 1
        held.add(dedup_key(out.stem))
        if dry_run:
            kept.append(title + "  [dry-run]")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(header + md, encoding="utf-8")
        kept.append(title)
        if delay:
            time.sleep(delay)
    print(f"[{src.key}] kept {len(kept)} | skipped(existing) {len(skipped)} | "
          f"dropped {len(dropped)}")
    for t in kept:
        print(f"   + {t}")
    for t, why in dropped[:40]:
        print(f"   - [{why}] {t}")
    return {"kept": len(kept), "skipped": len(skipped), "dropped": len(dropped)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", metavar="KEY",
                   help=f"import only these sources ({', '.join(s.key for s in SOURCES)})")
    p.add_argument("--limit", type=int, default=None, help="max articles per source")
    p.add_argument("--delay", type=float, default=0.4, help="seconds between fetches")
    p.add_argument("--dry-run", action="store_true", help="discover + filter, write nothing")
    p.add_argument("--list", action="store_true", help="list sources and exit")
    args = p.parse_args(argv)

    if args.list:
        for s in SOURCES:
            print(f"{s.key:14} -> Literature/Blogs/{s.company}/")
        return 0

    sources = SOURCES
    if args.only:
        keys = set(args.only)
        sources = [s for s in SOURCES if s.key in keys]
        if not sources:
            print(f"no matching sources for {args.only}", file=sys.stderr)
            return 2

    session = _session()
    totals = {"kept": 0, "skipped": 0, "dropped": 0}
    for s in sources:
        try:
            r = import_source(session, s, args.limit, args.delay, args.dry_run)
            for k in totals:
                totals[k] += r[k]
        except Exception as exc:
            print(f"[{s.key}] FAILED: {exc}", file=sys.stderr)
    print(f"\nDone. kept {totals['kept']} | skipped {totals['skipped']} | "
          f"dropped {totals['dropped']} across {len(sources)} source(s).")
    if not args.dry_run and totals["kept"]:
        print("Next: scripts/.venv/bin/python -m search.cli index --roots literature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
