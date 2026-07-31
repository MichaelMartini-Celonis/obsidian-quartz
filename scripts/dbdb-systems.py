#!/usr/bin/env python3
"""Mirror the CMU dbdb.io "Database of Databases" into indexable markdown, and
derive a controlled **tag taxonomy** for database papers from its categorization.

Two things live here:

  1. ``taxonomy`` - read the dbdb.io Django fixtures
     (``cmu-db/dbdb.io/data/fixtures/core_features.json`` +
     ``core_attributes.json``) and emit the categorization schema as
       * ``scripts/dbdb-taxonomy.json``      (machine-readable controlled vocab)
       * ``db_systems/dbdb/_taxonomy.md``    (human-readable, indexed)
     dbdb models a system along **24 technical *features*** (Data Model, Storage
     Model, Concurrency Control, Indexes, ... grouped into 4 categories) and
     **7 *attributes*** (Project Type, License, Operating System, Programming
     Language, ...). Those dimensions + their option values are exactly the tag
     vocabulary we align database papers to.

  2. ``scrape`` - crawl https://dbdb.io/browse (all ~1200 systems on one page),
     fetch each system page, and write ``db_systems/dbdb/<slug>.md`` with YAML
     front-matter carrying the tags plus the readable prose (history + every
     feature section). The ``db_systems`` tree is a first-class search root, so
     the tags become searchable text and every system's categorization is
     queryable alongside the papers.

Usage:
  scripts/.venv/bin/python scripts/dbdb-systems.py all
  scripts/.venv/bin/python scripts/dbdb-systems.py taxonomy
  scripts/.venv/bin/python scripts/dbdb-systems.py gather
  scripts/.venv/bin/python scripts/dbdb-systems.py scrape --limit 50
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import paperfetch as pf

DOCS_ROOT = Path(__file__).resolve().parent.parent
SITE = "https://dbdb.io"
BROWSE_URL = "https://dbdb.io/browse"
OUT_DIR = DOCS_ROOT / "db_systems" / "dbdb"
FIX_DIR = DOCS_ROOT / "Inbox" / "dbdb" / "_fixtures"
FIX_BASE = "https://raw.githubusercontent.com/cmu-db/dbdb.io/master/data/fixtures"
TAXONOMY_JSON = Path(__file__).resolve().parent / "dbdb-taxonomy.json"
CKPT = OUT_DIR / "_dbdb.json"
PAGE_SLEEP = 0.35

# The four feature categories dbdb groups its 24 technical features into.
CATEGORY_NAMES = {
    1: "Data & Storage",
    2: "Query Processing",
    3: "Transactions & Recovery",
    4: "Distributed Architecture",
}
# Non-feature /browse keys we also want to capture from a system page.
ATTR_KEYS = ["tag", "project-type", "license", "os", "programming-language",
             "governance", "stock-exchange", "country"]
REL_KEYS = ["derived", "compatible", "embeds", "inspired"]

ATTR_LABELS = {
    "tag": "Tags", "project-type": "Project Type", "license": "License",
    "os": "Operating Systems", "programming-language": "Written In",
    "governance": "Governing Foundation", "stock-exchange": "Stock Exchange",
    "country": "Country",
}
REL_LABELS = {
    "derived": "Derived From", "compatible": "Compatible With",
    "embeds": "Embeds", "inspired": "Inspired By",
}


# ---------------------------------------------------------------------------
# fixtures -> taxonomy
# ---------------------------------------------------------------------------

def ensure_fixtures() -> None:
    FIX_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("core_features", "core_attributes"):
        dest = FIX_DIR / f"{name}.json"
        if dest.exists() and dest.stat().st_size > 1000:
            continue
        r = pf.requests.get(f"{FIX_BASE}/{name}.json", headers=pf.HEADERS, timeout=60)
        r.raise_for_status()
        dest.write_text(r.text, encoding="utf-8")


def build_taxonomy() -> dict:
    ensure_fixtures()
    feat = json.loads((FIX_DIR / "core_features.json").read_text(encoding="utf-8"))
    attr = json.loads((FIX_DIR / "core_attributes.json").read_text(encoding="utf-8"))

    features = {x["pk"]: x["fields"] for x in feat if x["model"] == "core.feature"}
    fopts: dict[int, list] = {}
    for x in feat:
        if x["model"] == "core.featureoption":
            f = x["fields"]
            fopts.setdefault(f["feature"], []).append(
                {"slug": f["slug"], "value": f.get("value") or f["slug"]})

    by_category: dict[str, list] = {}
    for pk, f in features.items():
        cat = CATEGORY_NAMES.get(f.get("category"), "Other")
        by_category.setdefault(cat, []).append({
            "slug": f["slug"],
            "label": f["label"],
            "multivalued": f.get("multivalued", True),
            "options": sorted(fopts.get(pk, []), key=lambda o: o["value"].lower()),
        })
    for cat in by_category:
        by_category[cat].sort(key=lambda d: d["label"].lower())

    attributes = {x["pk"]: x["fields"] for x in attr if x["model"] == "core.attribute"}
    aopts: dict[int, list] = {}
    for x in attr:
        if x["model"] == "core.attributeoption":
            f = x["fields"]
            aopts.setdefault(f["attribute"], []).append(
                {"slug": f["slug"], "name": f.get("name") or f["slug"]})
    attr_list = []
    for pk, a in attributes.items():
        attr_list.append({
            "slug": a["slug"],
            "name": a["name"],
            "sv_field": a.get("sv_field") or "",
            "options": sorted(aopts.get(pk, []), key=lambda o: o["name"].lower()),
        })
    attr_list.sort(key=lambda d: d["name"].lower())

    return {
        "source": "https://github.com/cmu-db/dbdb.io/tree/master/data/fixtures",
        "site": SITE,
        "categories": list(CATEGORY_NAMES.values()),
        "features": by_category,
        "attributes": attr_list,
        "relationships": [REL_LABELS[k] for k in REL_KEYS],
    }


def write_taxonomy(tax: dict) -> None:
    TAXONOMY_JSON.write_text(json.dumps(tax, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Database systems tag taxonomy (dbdb.io-aligned)",
        "",
        "A controlled vocabulary for tagging and organizing **database systems and "
        "database papers**, derived from the CMU [Database of Databases](https://dbdb.io) "
        "categorization (its Django fixtures at "
        "[`cmu-db/dbdb.io/data/fixtures`](https://github.com/cmu-db/dbdb.io/tree/master/data/fixtures)).",
        "",
        "A system/paper is tagged along **technical features** (grouped in four "
        "categories) and **metadata attributes**. Each dimension draws its values "
        "from the controlled option lists below. The machine-readable version is "
        "`scripts/dbdb-taxonomy.json`.",
        "",
        f"- **{sum(len(v) for v in tax['features'].values())} technical features** "
        f"in {len(tax['features'])} categories",
        f"- **{len(tax['attributes'])} metadata attributes**",
        f"- **relationships:** {', '.join(tax['relationships'])}",
        "",
        "## Technical features",
        "",
    ]
    for cat in tax["categories"]:
        feats = tax["features"].get(cat, [])
        if not feats:
            continue
        lines.append(f"### {cat}")
        lines.append("")
        for f in feats:
            opts = ", ".join(o["value"] for o in f["options"]) or "(free text)"
            lines.append(f"- **{f['label']}** (`{f['slug']}`): {opts}")
        lines.append("")
    lines.append("## Metadata attributes")
    lines.append("")
    for a in tax["attributes"]:
        opts = ", ".join(o["name"] for o in a["options"])
        opts = (opts[:400] + " ...") if len(opts) > 400 else (opts or "(free text)")
        lines.append(f"- **{a['name']}** (`{a['slug']}`): {opts}")
    lines.append("")
    (OUT_DIR / "_taxonomy.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {TAXONOMY_JSON.relative_to(DOCS_ROOT)} and "
          f"{(OUT_DIR / '_taxonomy.md').relative_to(DOCS_ROOT)}")


# ---------------------------------------------------------------------------
# browse -> slugs
# ---------------------------------------------------------------------------

def fetch_browse(sess) -> list[str]:
    r = sess.get(BROWSE_URL, timeout=60)
    r.raise_for_status()
    slugs = re.findall(r'href="/db/([^"/?]+)"', r.text)
    uniq = sorted(dict.fromkeys(slugs))
    print(f"browse: {len(uniq)} unique systems")
    return uniq


# ---------------------------------------------------------------------------
# system page -> record -> markdown
# ---------------------------------------------------------------------------

SECTION_RE = re.compile(r'<div id="(?P<id>[^"]+)" class="entry-section">(?P<body>.*?)'
                        r'(?=<div id="[^"]+" class="entry-section">|<div class="citations"|'
                        r'<footer|</main)', re.S)
H2_RE = re.compile(r"<h2[^>]*>(?P<h>.*?)</h2>", re.S)
BADGE_RE = re.compile(r'<a class="badge-section"[^>]*>(?P<t>.*?)</a>', re.S)
P_RE = re.compile(r"<p[^>]*>(?P<p>.*?)</p>", re.S)
BROWSE_LINK_RE = re.compile(
    r'<a[^>]*href="/browse\?(?P<key>[a-z\-]+)=(?P<val>[^"&]+)"[^>]*>(?P<label>.*?)</a>',
    re.S | re.I)
H1_RE = re.compile(r"<h1[^>]*>(?P<h>.*?)</h1>", re.S)
OG_RE = re.compile(r'<meta property="og:description" content="(?P<c>[^"]*)"')


def _txt(s: str) -> str:
    return pf.clean(s)


def parse_system(html: str, slug: str) -> dict:
    name_m = H1_RE.search(html)
    name = _txt(name_m.group("h")) if name_m else slug
    og_m = OG_RE.search(html)
    og = _txt(og_m.group("c")) if og_m else ""
    yr = re.search(r"\(Since\s*(\d{4})(?:\s*[-\u2013]\s*(\d{4}))?\)", og)
    start_year = int(yr.group(1)) if yr else None
    end_year = int(yr.group(2)) if (yr and yr.group(2)) else None

    # all categorization links (features badges + attributes + relationships)
    links: dict[str, "dict[str,str]"] = {}
    for m in BROWSE_LINK_RE.finditer(html):
        key = m.group("key").lower()
        val = m.group("val")
        label = _txt(m.group("label"))
        # dbdb collapses long relationship lists into a "View All (N)" link;
        # that's a UI affordance, not a value, so drop it.
        if not label or re.match(r"View All\b", label, re.I):
            continue
        links.setdefault(key, {})[val] = label

    # prose per section (id -> (label, prose))
    sections: list[tuple[str, str, str]] = []
    for sm in SECTION_RE.finditer(html):
        sid = sm.group("id")
        body = sm.group("body")
        h2 = H2_RE.search(body)
        label = re.sub(r'<span class="cites">.*?</span>', "", h2.group("h"), flags=re.S) if h2 else sid
        label = _txt(label)
        prose = " ".join(_txt(p) for p in P_RE.findall(body)).strip()
        prose = re.sub(r"\s+", " ", prose)
        sections.append((sid, label, prose))

    return {
        "slug": slug,
        "name": name,
        "url": f"{SITE}/db/{slug}",
        "summary": og,
        "start_year": start_year,
        "end_year": end_year,
        "links": links,
        "sections": sections,
    }


def _yaml_list(vals: list[str]) -> str:
    return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in vals) + "]"


def to_markdown(rec: dict, tax: dict) -> str:
    links = rec["links"]
    feature_slugs = {f["slug"] for feats in tax["features"].values() for f in feats}

    fm = ["---", f"system: {json.dumps(rec['name'], ensure_ascii=False)}",
          f"slug: {rec['slug']}", f"source: {rec['url']}"]
    if rec["start_year"]:
        fm.append(f"start_year: {rec['start_year']}")
    if rec["end_year"]:
        fm.append(f"end_year: {rec['end_year']}")
    # metadata attributes
    for k in ATTR_KEYS:
        if links.get(k):
            fm.append(f"{k.replace('-', '_')}: {_yaml_list(sorted(links[k].values()))}")
    # relationships
    for k in REL_KEYS:
        if links.get(k):
            fm.append(f"{k}: {_yaml_list(sorted(links[k].values()))}")
    # technical features
    feat_present = {k: v for k, v in links.items() if k in feature_slugs}
    if feat_present:
        fm.append("features:")
        for k in sorted(feat_present):
            fm.append(f"  {k}: {_yaml_list(sorted(feat_present[k].values()))}")
    fm.append("---")

    out = ["\n".join(fm), "", f"# {rec['name']}", ""]
    if rec["summary"]:
        out += [f"> {rec['summary']}", ""]
    out += [f"**Source:** {rec['url']}  ", ""]

    # Categorization table (tags rendered as readable text for retrieval).
    rows = []
    yr = None
    if rec["start_year"]:
        yr = str(rec["start_year"]) + (f"\u2013{rec['end_year']}" if rec["end_year"] else "")
    if yr:
        rows.append(("Start Year", yr))
    for k in ATTR_KEYS:
        if links.get(k):
            rows.append((ATTR_LABELS[k], ", ".join(sorted(links[k].values()))))
    for k in REL_KEYS:
        if links.get(k):
            rows.append((REL_LABELS[k], ", ".join(sorted(links[k].values()))))
    for feats in tax["features"].values():
        for f in feats:
            if links.get(f["slug"]):
                rows.append((f["label"], ", ".join(sorted(links[f["slug"]].values()))))
    if rows:
        out += ["## Categorization", "", "| Dimension | Values |", "|---|---|"]
        for k, v in rows:
            out.append(f"| {k} | {v} |")
        out.append("")

    # Prose sections (history first, then features that carry description text).
    for sid, label, prose in rec["sections"]:
        if not prose:
            continue
        out += [f"## {label}", "", prose, ""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# scrape driver (resumable)
# ---------------------------------------------------------------------------

def load_ckpt() -> dict:
    return json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else {}


def save_ckpt(state: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def scrape(limit: int | None, force: bool) -> None:
    tax = build_taxonomy()
    sess = pf.session()
    state = load_ckpt()
    slugs = state.get("slugs") or fetch_browse(sess)
    state["slugs"] = slugs
    done = state.setdefault("done", {})
    todo = [s for s in slugs if force or s not in done]
    if limit:
        todo = todo[:limit]
    print(f"scraping {len(todo)} system pages -> {OUT_DIR}")
    ok = fail = 0
    for i, slug in enumerate(todo, 1):
        try:
            r = sess.get(f"{SITE}/db/{slug}", timeout=45)
            if r.status_code != 200:
                done[slug] = f"HTTP {r.status_code}"; fail += 1; continue
            rec = parse_system(r.text, slug)
            md = to_markdown(rec, tax)
            (OUT_DIR / f"{slug}.md").write_text(md, encoding="utf-8")
            done[slug] = "ok"; ok += 1
            if i % 25 == 0:
                save_ckpt(state)
                print(f"  [{i}/{len(todo)}] {slug} (+{ok} ok)")
        except Exception as exc:  # noqa: BLE001
            done[slug] = f"ERR {type(exc).__name__}"; fail += 1
            print(f"  [{i}/{len(todo)}] {slug}: {exc}")
        time.sleep(PAGE_SLEEP)
    save_ckpt(state)
    print(f"\n=== scraped {ok} ok, {fail} failed; "
          f"{sum(1 for v in done.values() if v == 'ok')}/{len(slugs)} total on disk ===")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", nargs="?", default="all",
                   choices=["taxonomy", "gather", "scrape", "all"])
    p.add_argument("--limit", type=int, default=None, help="max system pages this run")
    p.add_argument("--force", action="store_true", help="re-scrape systems already done")
    args = p.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "taxonomy":
        write_taxonomy(build_taxonomy()); return 0
    if args.cmd == "gather":
        state = load_ckpt(); state["slugs"] = fetch_browse(pf.session())
        save_ckpt(state); return 0
    if args.cmd == "scrape":
        scrape(args.limit, args.force); return 0
    write_taxonomy(build_taxonomy())
    scrape(args.limit, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
