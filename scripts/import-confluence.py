#!/usr/bin/env python3
"""Assemble a Confluence space into one consolidated markdown document.

Companion to ``import-docs.py`` (public vendor docs). Confluence spaces behind
SSO cannot be fetched by an unattended script, so this tool does **not** talk to
Atlassian itself: it consumes the JSON batches returned by the Atlassian MCP
``getPagesInConfluenceSpace`` tool and turns them into the same shape
``import-docs.py`` produces - a single file per space with a
``<!-- source: URL -->`` provenance marker per page.

Capture the batches first (paginate with the ``next`` cursor until it is null),
saving each tool result verbatim, then:

    scripts/.venv/bin/python scripts/import-confluence.py \\
        --batch adf-*.json \\
        --space PQLdevelopment \\
        --title "Celonis PQL Function Library (Development version)"

**Request the batches with ``contentFormat: "adf"``.** The MCP's own markdown
rendering is lossy in two ways that matter: it silently drops tables (which on a
function-reference page are the worked examples), and it enforces a cumulative
512 KB-per-request conversion budget that replaces later page bodies with a
"Body omitted" placeholder. Raw ADF has neither limit, so this script renders
the ADF itself; markdown bodies are still accepted (and placeholders dropped) so
mixed captures degrade gracefully.

Pages are emitted depth-first following the Confluence parent/child hierarchy so
that the document reads in navigation order rather than by page id.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path

from lxml import html as H

DOCS_ROOT = Path(__file__).resolve().parent.parent
INTERNAL = DOCS_ROOT / "Internal"


# --- Confluence storage format (cxhtml) -> markdown --------------------------
# Pages migrated from the old editor keep their macro bodies as raw storage-format
# XHTML inside a "legacy-content" extension. On a function-reference page that is
# where the worked examples live (query + input/output tables), so it has to be
# rendered rather than skipped. lxml exposes the namespaced macro tags verbatim
# ("ac:structured-macro"), which cannot be selected with XPath - hence the manual
# child walking below.

_CX_BLOCK_TAGS = {"div", "p", "table", "ul", "ol", "blockquote",
                  "h1", "h2", "h3", "h4", "h5", "h6",
                  "ac:structured-macro", "ac:rich-text-body"}
_CX_DROP_TAGS = {"ac:parameter", "colgroup", "col", "script", "style"}


def _cx_children(el, tag: str) -> list:
    return [c for c in el if isinstance(c.tag, str) and c.tag == tag]


def _cx_param(el, name: str) -> str:
    for p in _cx_children(el, "ac:parameter"):
        if (p.get("ac:name") or "") == name:
            return (p.text_content() or "").strip()
    return ""


def _cx_inline(el) -> str:
    """Flatten an element to a single line, resolving Confluence link macros."""
    out: list[str] = []
    if el.text:
        out.append(el.text)
    for c in el:
        if not isinstance(c.tag, str) or c.tag in _CX_DROP_TAGS:
            pass
        elif c.tag == "ac:link":
            label = ""
            for kid in c:
                if isinstance(kid.tag, str) and kid.tag == "ac:plain-text-link-body":
                    label = (kid.text_content() or "").strip()
            if not label:
                for kid in c:
                    if isinstance(kid.tag, str) and kid.tag == "ri:page":
                        label = kid.get("ri:content-title") or ""
            out.append(label or (c.text_content() or "").strip())
        elif c.tag in ("b", "strong"):
            t = _cx_inline(c).strip()
            out.append(f"**{t}**" if t else "")
        elif c.tag in ("i", "em"):
            t = _cx_inline(c).strip()
            out.append(f"_{t}_" if t else "")
        elif c.tag in ("code", "tt"):
            t = _cx_inline(c).strip()
            out.append(f"`{t}`" if t else "")
        elif c.tag == "br":
            out.append(" ")
        else:
            out.append(_cx_inline(c))
        if c.tail:
            out.append(c.tail)
    return re.sub(r"[ \t\u00a0]+", " ", "".join(out)).strip()


def _cx_table(el) -> str:
    rows: list[tuple[bool, list[str]]] = []
    for tr in el.iter("tr"):
        cells, header = [], False
        for cell in tr:
            if not isinstance(cell.tag, str) or cell.tag not in ("th", "td"):
                continue
            header = header or cell.tag == "th"
            cells.append(_cx_inline(cell).replace("|", "\\|"))
        if any(cells):
            rows.append((header, cells))
    if not rows:
        return ""
    width = max(len(c) for _, c in rows)
    sep = "|" + "---|" * width
    out: list[str] = []
    if not rows[0][0]:
        out += ["|" + " |" * width, sep]
    for i, (header, cells) in enumerate(rows):
        out.append("| " + " | ".join(cells + [""] * (width - len(cells))) + " |")
        if i == 0 and header:
            out.append(sep)
    return "\n".join(out)


def _cx_macro(el) -> str:
    name = (el.get("ac:name") or "").lower()
    if name in ("code", "noformat"):
        body = ""
        for c in el:
            if isinstance(c.tag, str) and c.tag == "ac:plain-text-body":
                body = c.text_content()
        body = (body or "").strip("\n")
        return f"```{_cx_param(el, 'language')}\n{body}\n```" if body.strip() else ""
    inner = "\n\n".join(p for p in (_cx_blocks(c) for c in el
                                    if isinstance(c.tag, str)
                                    and c.tag == "ac:rich-text-body") if p)
    title = _cx_param(el, "title")
    if title:
        return f"**{title}**\n\n{inner}" if inner else f"**{title}**"
    return inner


def _cx_blocks(el) -> str:
    parts: list[str] = []
    for c in el:
        if not isinstance(c.tag, str) or c.tag in _CX_DROP_TAGS:
            continue
        if c.tag == "ac:structured-macro":
            parts.append(_cx_macro(c))
        elif c.tag == "table":
            parts.append(_cx_table(c))
        elif c.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            t = _cx_inline(c)
            # h5/h6 are used as table captions here, not as document structure.
            parts.append(f"**{t}**" if t else "")
        elif c.tag in ("ul", "ol"):
            ordered = c.tag == "ol"
            items = [_cx_inline(li) for li in c if isinstance(li.tag, str) and li.tag == "li"]
            parts.append("\n".join(f"{i}. {t}" if ordered else f"* {t}"
                                   for i, t in enumerate(items, 1) if t))
        elif c.tag == "pre":
            body = (c.text_content() or "").strip("\n")
            parts.append(f"```\n{body}\n```" if body.strip() else "")
        elif any(isinstance(g.tag, str) and g.tag in _CX_BLOCK_TAGS for g in c):
            parts.append(_cx_blocks(c))       # container: descend
        else:
            parts.append(_cx_inline(c))
        if c.tail and c.tail.strip():
            parts.append(c.tail.strip())
    return "\n\n".join(p for p in parts if p and p.strip())


def cxhtml_to_markdown(cxhtml: str) -> str:
    if not (cxhtml or "").strip():
        return ""
    # Code macros wrap their body in CDATA, which the HTML parser turns into a
    # comment node - escaping it to plain text first keeps the snippet.
    cxhtml = re.sub(r"<!\[CDATA\[(.*?)\]\]>",
                    lambda m: escape(m.group(1), quote=False), cxhtml, flags=re.S)
    try:
        doc = H.fromstring(f"<div>{cxhtml}</div>")
    except Exception:
        return ""
    return re.sub(r"\n{3,}", "\n\n", _cx_blocks(doc)).strip()


# --- ADF (Atlassian Document Format) -> markdown -----------------------------

# Emitted by the MCP in place of a body it declined to convert; never content.
PLACEHOLDER = "Body omitted:"


def _marked(text: str, marks: list[dict]) -> str:
    if not text.strip():
        return text
    kinds = {m.get("type"): (m.get("attrs") or {}) for m in marks or []}
    if "code" in kinds:
        text = f"`{text}`"
    if "strong" in kinds:
        text = f"**{text}**"
    if "em" in kinds:
        text = f"_{text}_"
    if "strike" in kinds:
        text = f"~~{text}~~"
    if "link" in kinds:
        href = kinds["link"].get("href", "")
        text = f"[{text}]({href})" if href else text
    return text


def _media(node: dict) -> str:
    attrs = node.get("attrs") or {}
    alt = (attrs.get("alt") or "").strip()
    url = attrs.get("url") or ""
    if url:
        return f"![{alt}]({url})"
    # Attachments are referenced by opaque id; only the caption carries meaning.
    return f"_[image: {alt}]_" if alt else ""


def _inline(nodes) -> str:
    out: list[str] = []
    for n in nodes or []:
        t = n.get("type")
        attrs = n.get("attrs") or {}
        if t == "text":
            out.append(_marked(n.get("text", ""), n.get("marks")))
        elif t == "hardBreak":
            out.append("  \n")
        elif t == "inlineCard":
            url = attrs.get("url", "")
            out.append(f"<{url}>" if url else "")
        elif t in ("mention", "status"):
            out.append(attrs.get("text", ""))
        elif t == "emoji":
            out.append(attrs.get("text") or attrs.get("shortName") or "")
        elif t == "date":
            out.append(attrs.get("timestamp", ""))
        elif t in ("media", "mediaInline"):
            out.append(_media(n))
        else:
            out.append(_inline(n.get("content")))
    return "".join(out)


def _list(node: dict) -> str:
    ordered = node.get("type") == "orderedList"
    start = int((node.get("attrs") or {}).get("order") or 1)
    out: list[str] = []
    n = 0
    for item in node.get("content") or []:
        body = _blocks(item.get("content")).strip("\n")
        if not body:
            continue
        marker = f"{start + n}." if ordered else "*"
        n += 1
        pad = " " * (len(marker) + 1)
        lines = body.split("\n")
        # Continuation lines carry the indent, which is also what nests sublists.
        out.append("\n".join([f"{marker} {lines[0]}"]
                             + [pad + l if l else "" for l in lines[1:]]))
    return "\n".join(out)


def _table(node: dict) -> str:
    rows: list[tuple[bool, list[str]]] = []
    for row in node.get("content") or []:
        if row.get("type") != "tableRow":
            continue
        cells, header = [], bool(row.get("content"))
        for cell in row.get("content") or []:
            if cell.get("type") != "tableHeader":
                header = False
            # Markdown cells are single-line: flatten and escape the delimiter.
            txt = re.sub(r"\s+", " ", _blocks(cell.get("content")).strip())
            cells.append(txt.replace("|", "\\|"))
        rows.append((header, cells))
    rows = [(h, c) for h, c in rows if any(x for x in c)]
    if not rows:
        return ""
    width = max(len(c) for _, c in rows)
    sep = "|" + "---|" * width
    out: list[str] = []
    if not rows[0][0]:                      # no header row: emit an empty one
        out += ["|" + " |" * width, sep]
    for i, (header, cells) in enumerate(rows):
        out.append("| " + " | ".join(cells + [""] * (width - len(cells))) + " |")
        if i == 0 and header:
            out.append(sep)
    return "\n".join(out)


def _quote(inner: str, prefix: str = "") -> str:
    lines = [f"> {l}" if l else ">" for l in inner.split("\n")]
    return "\n".join(([f"> {prefix}"] if prefix else []) + lines)


def _block(node: dict) -> str:
    t = node.get("type")
    attrs = node.get("attrs") or {}
    if t == "paragraph":
        return _inline(node.get("content")).strip()
    if t == "heading":
        level = min(max(int(attrs.get("level", 1)), 1), 6)
        return f"{'#' * level} {_inline(node.get('content')).strip()}"
    if t == "codeBlock":
        body = "".join(c.get("text", "") for c in node.get("content") or [])
        return f"```{attrs.get('language') or ''}\n{body}\n```"
    if t in ("bulletList", "orderedList"):
        return _list(node)
    if t == "table":
        return _table(node)
    if t == "blockquote":
        return _quote(_blocks(node.get("content")))
    if t == "panel":
        return _quote(_blocks(node.get("content")),
                      f"**{str(attrs.get('panelType') or 'info').title()}**")
    if t == "rule":
        return "---"
    if t in ("expand", "nestedExpand"):
        title = attrs.get("title") or "Details"
        return f"**{title}**\n\n{_blocks(node.get('content'))}"
    if t == "caption":
        inner = _inline(node.get("content")).strip()
        return f"_{inner}_" if inner else ""
    if t in ("media", "mediaInline"):
        return _media(node)
    if t == "taskList":
        return "\n".join(f"- [ ] {_inline(i.get('content')).strip()}"
                         for i in node.get("content") or [])
    if t == "decisionList":
        return "\n".join(f"- {_inline(i.get('content')).strip()}"
                         for i in node.get("content") or [])
    if t in ("extension", "bodiedExtension", "inlineExtension"):
        return _extension(node)
    # doc, layoutSection/Column, mediaSingle/Group, …
    return _blocks(node.get("content"))


def _extension(node: dict) -> str:
    """Render a Confluence macro node (its body is not plain ADF)."""
    attrs = node.get("attrs") or {}
    params = attrs.get("parameters") or {}
    if attrs.get("extensionKey") == "legacy-content":
        # Prefer the raw storage format: the partial ADF in "nestedContent"
        # drops the tables that make up the worked examples.
        md = cxhtml_to_markdown(params.get("cxhtml") or "")
        if md:
            return md
        nested = params.get("nestedContent") or {}
        return _blocks(nested.get("content")) if nested else ""
    inner = _blocks(node.get("content"))
    title = (((params.get("macroMetadata") or {}).get("title")) or "")
    # A bare "Panel"/"Section" wrapper title carries no information.
    if title and title.lower() not in ("panel", "section", "column") and inner:
        return f"**{title}**\n\n{inner}"
    return inner


def _blocks(nodes) -> str:
    parts = [p for p in (_block(n) for n in nodes or []) if p and p.strip()]
    return "\n\n".join(parts)


def adf_to_markdown(body: dict) -> str:
    text = _blocks(body.get("content"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def render_body(page: dict) -> str:
    """Return the page body as markdown, whatever format the MCP returned."""
    body = page.get("body")
    if isinstance(body, dict):
        return adf_to_markdown(body)
    text = (body or "").strip()
    return "" if text.startswith(PLACEHOLDER) else text


def load_pages(batches: list[Path]) -> list[dict]:
    """Read MCP batch files, keeping the richest body seen for each page id."""
    by_id: dict[str, dict] = {}
    for b in batches:
        data = json.loads(b.read_text(encoding="utf-8"))
        results = data.get("results") if isinstance(data, dict) else data
        for page in results or []:
            pid = str(page.get("id"))
            page = {**page, "body": render_body(page)}
            prev = by_id.get(pid)
            if prev is None or len(page["body"]) > len(prev["body"]):
                by_id[pid] = page
    return list(by_id.values())


def order_pages(pages: list[dict]) -> list[tuple[int, dict]]:
    """Depth-first walk of the page tree; returns (depth, page) pairs.

    Pages whose parent is outside the batch (typically the space homepage, whose
    own parent is the space) are treated as roots.
    """
    by_id = {str(p["id"]): p for p in pages}
    children: dict[str | None, list[dict]] = defaultdict(list)
    for p in pages:
        parent = str(p.get("parentId")) if p.get("parentId") else None
        children[parent if parent in by_id else None].append(p)
    for group in children.values():
        group.sort(key=lambda p: (p.get("title") or "").lower())

    out: list[tuple[int, dict]] = []
    seen: set[str] = set()

    def walk(page: dict, depth: int) -> None:
        pid = str(page["id"])
        if pid in seen:                       # defensive: parent cycles
            return
        seen.add(pid)
        out.append((depth, page))
        for child in children.get(pid, []):
            walk(child, depth + 1)

    for root in children[None]:
        walk(root, 0)
    for p in pages:                            # anything orphaned by a cycle
        if str(p["id"]) not in seen:
            out.append((0, p))
    return out


def demote_headings(md: str, by: int) -> str:
    """Shift ATX headings down ``by`` levels so page bodies nest under their title."""
    if by <= 0:
        return md
    def sub(m: re.Match) -> str:
        level = min(len(m.group(1)) + by, 6)
        return "#" * level + " "
    # Skip fenced code blocks so shell comments are not rewritten.
    parts = re.split(r"(```.*?```|~~~.*?~~~)", md, flags=re.S)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"^(#{1,6})\s+", sub, parts[i], flags=re.M)
    return "".join(parts)


def build(pages: list[dict], args) -> tuple[int, str]:
    base = args.site.rstrip("/")
    parts: list[str] = []
    kept = 0
    for depth, page in order_pages(pages):
        body = (page.get("body") or "").strip()
        if len(body) < args.min_chars:
            continue
        title = page.get("title") or str(page.get("id"))
        url = f"{base}/spaces/{args.space}/pages/{page['id']}"
        level = min(depth + 2, 6)              # h1 is the document title
        parts.append(f"\n\n<!-- source: {url} -->\n")
        parts.append(f"{'#' * level} {title}\n\n")
        parts.append(demote_headings(body, level))
        parts.append("\n")
        kept += 1
    return kept, "".join(parts)


def header(args, n: int) -> str:
    return (
        f"# {args.title}\n\n"
        f"**Company/Tool:** {args.company}  \n"
        f"**Source:** {args.site.rstrip('/')}/spaces/{args.space}  \n"
        f"**Confluence space:** `{args.space}`  \n"
        f"**Retrieved:** {date.today().isoformat()} "
        f"(exported via the Atlassian MCP; {n} pages)\n\n"
        "> Internal Celonis working material, mirrored for offline reading and "
        "semantic search. Do not redistribute outside Celonis.\n\n---\n\n"
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--batch", nargs="+", required=True, type=Path,
                   help="JSON file(s) captured from getPagesInConfluenceSpace")
    p.add_argument("--space", required=True, help="Confluence space key")
    p.add_argument("--title", required=True, help="document title")
    p.add_argument("--site", default="https://celonis.atlassian.net/wiki",
                   help="Confluence base URL (default: %(default)s)")
    p.add_argument("--company", default="Celonis")
    p.add_argument("--collection", default="",
                   help="optional subfolder under Internal/ (default: company name only)")
    p.add_argument("--out-name", default="", help="output filename (default: '<title>.md')")
    p.add_argument("--min-chars", type=int, default=80,
                   help="skip pages with a shorter body (default: %(default)s)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    missing = [b for b in args.batch if not b.exists()]
    if missing:
        print(f"missing batch file(s): {', '.join(map(str, missing))}", file=sys.stderr)
        return 2

    pages = load_pages(args.batch)
    n, body = build(pages, args)
    print(f"[{args.space}] {len(pages)} pages loaded, {n} with content")
    if not body.strip():
        print(f"[{args.space}] no content extracted", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"[{args.space}] dry-run: would write ~{len(body) / 1024:.0f} KB")
        return 0

    name = args.out_name or f"{args.title}.md"
    dest_root = INTERNAL / args.collection if args.collection else INTERNAL
    dest = dest_root / args.company / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(header(args, n) + body, encoding="utf-8")
    print(f"[{args.space}] wrote {dest.relative_to(DOCS_ROOT)} "
          f"({n} pages, {dest.stat().st_size / 1024:.0f} KB)")
    print("Next: scripts/.venv/bin/python -m search.cli index --roots literature")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
