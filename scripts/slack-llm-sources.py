#!/usr/bin/env python3
"""Import primary papers and technical posts shared in #llm-paper-sharing.

This is a reproducible snapshot of Slack channel C05CVHZA728 (June 2023 through
July 2026). News stories, product landing pages, social-only links, videos, and
paywalled magazine articles are deliberately excluded.

    scripts/.venv/bin/python scripts/slack-llm-sources.py papers
    scripts/.venv/bin/python scripts/slack-llm-sources.py blogs
    scripts/.venv/bin/python scripts/slack-llm-sources.py all

Papers land in ``Inbox/slack-llm-papers/`` for ``import-downloads.py --only
slack-llm-papers``. Blog posts are converted directly to markdown under
``Literature/Blogs/<Publisher>/`` using the shared blog extractor.
"""

from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paperfetch as pf  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Inbox" / "slack-llm-papers"
REPORT = OUT / "_slack-llm-papers-report.csv"

_blog_spec = importlib.util.spec_from_file_location(
    "import_blogs", Path(__file__).resolve().parent / "import-blogs.py")
_blogs = importlib.util.module_from_spec(_blog_spec)
sys.modules["import_blogs"] = _blogs
_blog_spec.loader.exec_module(_blogs)


# URLs are kept rather than copied titles: arXiv metadata is fetched in one
# batch, while other hosts expose citation_title/citation_pdf_url in the page.
PAPER_URLS = [
    "https://arxiv.org/abs/2606.23991",
    "https://arxiv.org/abs/2507.19457",
    "https://arxiv.org/abs/2507.13334",
    "https://papers.nips.cc/paper_files/paper/2025/file/a6c7515ac435277dc92b75a07bb2257c-Paper-Conference.pdf",
    "https://arxiv.org/abs/2504.21318",
    "https://arxiv.org/abs/2503.13657",
    "https://arxiv.org/abs/2504.00698",
    "https://arxiv.org/abs/2503.16416",
    "https://arxiv.org/abs/2503.07891",
    "https://arxiv.org/abs/2501.19393",
    "https://arxiv.org/abs/2501.13946",
    "https://arxiv.org/abs/2412.14161",
    "https://www.microsoft.com/en-us/research/uploads/prod/2024/12/HCAI_Agents.pdf",
    "https://arxiv.org/abs/2406.13264",
    "https://arxiv.org/abs/2409.14924",
    "https://arxiv.org/abs/2411.00027",
    "https://arxiv.org/abs/2406.09279",
    "https://arxiv.org/abs/2410.11905",
    "https://arxiv.org/abs/2410.12189",
    "https://arxiv.org/abs/2410.05603",
    "https://arxiv.org/abs/2410.05229",
    "https://arxiv.org/abs/2408.08067",
    "https://arxiv.org/abs/2409.13588",
    "https://arxiv.org/abs/2409.00729",
    "https://arxiv.org/abs/2408.15247",
    "https://arxiv.org/abs/2408.10548",
    "https://arxiv.org/abs/2408.08435",
    "https://arxiv.org/abs/2407.21783",
    "https://arxiv.org/abs/2402.02101",
    "https://arxiv.org/abs/2311.04934",
    "https://arxiv.org/abs/2408.04948",
    "https://openreview.net/pdf?id=xOpQFqz6Nf",
    "https://arxiv.org/abs/2311.08718",
    "https://proceedings.mlr.press/v235/murty24a.html",
    "https://arxiv.org/abs/2312.04474",
    "https://proceedings.mlr.press/v235/fey24a.html",
    "https://arxiv.org/abs/2407.11418",
    "https://arxiv.org/abs/2402.01030",
    "https://arxiv.org/abs/2405.19874",
    "https://arxiv.org/abs/2405.10689",
    "https://arxiv.org/abs/2304.03442",
    "https://arxiv.org/abs/2405.03710",
    "https://arxiv.org/abs/2405.04517",
    "https://arxiv.org/abs/2403.16971",
    "https://arxiv.org/abs/2307.07415",
    "https://arxiv.org/abs/2310.06117",
    "https://arxiv.org/abs/2303.17580",
    "https://arxiv.org/abs/2312.16171",
    "https://arxiv.org/abs/2401.12846",
    "https://arxiv.org/abs/2311.02462",
    "https://arxiv.org/abs/2310.20689",
    "https://arxiv.org/abs/2304.04576",
    "https://arxiv.org/abs/2310.07820",
    "https://arxiv.org/abs/2309.12288",
    "https://arxiv.org/abs/2309.00900",
    "https://www.vldb.org/pvldb/vol16/p1534-fu.pdf",
    "https://arxiv.org/abs/2308.10168",
    "https://arxiv.org/abs/2308.05481",
    "https://arxiv.org/abs/2307.16789",
    "https://arxiv.org/abs/2308.03854",
    "https://arxiv.org/abs/2303.01469",
    "https://arxiv.org/abs/2306.03460",
    "https://arxiv.org/abs/2307.03172",
    "https://arxiv.org/abs/2307.09009",
    "https://aclanthology.org/2023.findings-acl.426.pdf",
    "https://arxiv.org/abs/2302.11939",
    "https://arxiv.org/abs/2305.09645",
    "https://arxiv.org/abs/2307.03875",
    "https://arxiv.org/abs/2306.03901",
    "https://arxiv.org/abs/2306.01242",
    "https://arxiv.org/abs/2305.17126",
    "https://arxiv.org/abs/2306.04634",
    "https://arxiv.org/abs/2310.19923",
    "https://arxiv.org/abs/2308.12950",
]


BLOG_POSTS = [
    ("Google Research", "https://research.google/blog/introducing-tabfm-a-zero-shot-foundation-model-for-tabular-data/"),
    ("Google Research", "https://research.google/blog/chain-of-table-evolving-tables-in-the-reasoning-chain-for-table-understanding/"),
    ("Google Research", "https://research.google/blog/few-shot-tool-use-doesnt-really-work-yet/"),
    ("Anthropic", "https://www.anthropic.com/research/small-samples-poison"),
    ("Anthropic", "https://www.anthropic.com/research/project-vend-1"),
    ("Anthropic", "https://www.anthropic.com/engineering/multi-agent-research-system"),
    ("Anthropic", "https://www.anthropic.com/news/model-context-protocol"),
    ("Mistral AI", "https://mistral.ai/news/our-contribution-to-a-global-environmental-standard-for-ai"),
    ("Ayoub Ait Lachgar", "https://ayoubaitlachgar.com/writing/n8n-vs-bpmn/"),
    ("Bruce Schneier", "https://www.schneier.com/blog/archives/2025/10/agentic-ais-ooda-loop-problem.html"),
    ("METR", "https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/"),
    ("Philipp Schmid", "https://www.philschmid.de/context-engineering"),
    ("Snowflake", "https://www.snowflake.com/en/blog/ai-sql-query-language/"),
    ("Calvin French-Owen", "https://calv.info/openai-reflections"),
    ("Chip Huyen", "https://huyenchip.com/2025/01/07/agents.html"),
    ("Jay Alammar", "https://newsletter.languagemodels.co/p/the-illustrated-deepseek-r1"),
    ("Wiz", "https://www.wiz.io/blog/wiz-research-uncovers-exposed-deepseek-database-leak"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/"),
    ("Berkeley AI Research", "https://bairblog.github.io/2024/02/18/compound-ai-systems/"),
    ("Uber", "https://www.uber.com/in/en/blog/query-gpt/"),
    ("Chroma", "https://research.trychroma.com/embedding-adapters"),
    ("dottxt", "https://blog.dottxt.co/coalescence.html"),
    ("Foundation Capital", "https://foundationcapital.com/system-of-agents/"),
    ("Sequoia Capital", "https://www.sequoiacap.com/article/generative-ais-act-o1/"),
    ("Nabeel Qureshi", "https://nabeelqu.substack.com/p/reflections-on-palantir"),
    ("Hugging Face", "https://huggingface.co/blog/hugs"),
    ("Microsoft AutoGen", "https://microsoft.github.io/autogen/0.2/blog/2024/10/02/new-autogen-architecture-preview/"),
    ("IBM", "https://www.ibm.com/blog/building-ai-for-business-ibms-granite-foundation-models/"),
    ("Apache Doris", "https://doris.apache.org/blog/Tencent-LLM/"),
    ("Snorkel AI", "https://snorkel.ai/beyond-prompting-getting-production-quality-llm-performance-with-snorkel-flow/"),
    ("Snowflake", "https://www.snowflake.com/blog/meta-code-llama-testing/"),
    ("Snowflake", "https://www.snowflake.com/blog/running-llama-llm-snowpark/"),
    ("SAP", "https://community.sap.com/t5/technology-blog-posts-by-sap/large-process-models-process-management-in-the-age-of-generative-ai/ba-p/13564312"),
    ("SemiAnalysis", "https://www.semianalysis.com/p/gpt-4-architecture-infrastructure"),
    ("Microsoft TypeChat", "https://raw.githubusercontent.com/microsoft/TypeChat/main/site/src/blog/introducing-typechat.md"),
    ("Meta AI", "https://ai.meta.com/blog/code-llama-large-language-model-coding/"),
    ("Cohere", "https://cohere.com/blog/multilingual"),
    ("Cohere", "https://cohere.com/blog/chat-with-rag"),
]

BLOG_TITLES = {
    "https://ayoubaitlachgar.com/writing/n8n-vs-bpmn/":
        "n8n vs BPMN Systems: What Actually Differs",
    "https://www.schneier.com/blog/archives/2025/10/agentic-ais-ooda-loop-problem.html":
        "Agentic AI's OODA Loop Problem",
    "https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/":
        "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity",
    "https://newsletter.languagemodels.co/p/the-illustrated-deepseek-r1":
        "The Illustrated DeepSeek-R1",
    "https://www.wiz.io/blog/wiz-research-uncovers-exposed-deepseek-database-leak":
        "Wiz Research Uncovers Exposed DeepSeek Database Leaking Sensitive Information",
    "https://bairblog.github.io/2024/02/18/compound-ai-systems/":
        "The Shift from Models to Compound AI Systems",
    "https://www.sequoiacap.com/article/generative-ais-act-o1/":
        "Generative AI's Act o1",
    "https://nabeelqu.substack.com/p/reflections-on-palantir":
        "Reflections on Palantir",
    "https://raw.githubusercontent.com/microsoft/TypeChat/main/site/src/blog/introducing-typechat.md":
        "Introducing TypeChat",
}


def _arxiv_id(url: str) -> str:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#/]+)", url)
    return re.sub(r"\.pdf$", "", m.group(1)) if m else ""


def _arxiv_metadata(sess, urls: list[str]) -> dict[str, tuple[str, list[str], str]]:
    ids = [_arxiv_id(u) for u in urls if _arxiv_id(u)]
    out: dict[str, tuple[str, list[str], str]] = {}
    for start in range(0, len(ids), 40):
        r = sess.get("https://export.arxiv.org/api/query",
                     params={"id_list": ",".join(ids[start:start + 40])}, timeout=90)
        r.raise_for_status()
        for entry in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
            ident = re.search(r"<id>.*?/abs/([^<]+)", entry)
            title = re.search(r"<title>(.*?)</title>", entry, re.S)
            if not ident or not title:
                continue
            authors = []
            for raw in re.findall(r"<name>(.*?)</name>", entry):
                name = html.unescape(raw).strip()
                # arXiv commonly serializes names as "Surname, Given"; the
                # shared filename helper expects ordinary "Given Surname".
                if "," in name:
                    surname, given = (part.strip() for part in name.split(",", 1))
                    name = f"{given} {surname}".strip()
                authors.append(name)
            clean_title = re.sub(r"\s+", " ", html.unescape(title.group(1))).strip()
            arxiv_id = ident.group(1)
            out[arxiv_id] = (clean_title, authors, f"https://arxiv.org/pdf/{arxiv_id}")
    return out


def _citation_metadata(sess, url: str) -> tuple[str, list[str], str]:
    if url.lower().endswith(".pdf") or "/pdf?" in url or "/doi/pdf/" in url:
        return "", [], url
    try:
        r = sess.get(url, timeout=60)
        r.raise_for_status()
    except Exception:
        return "", [], url
    text = r.text
    def meta(name: str) -> list[str]:
        return [html.unescape(x).strip() for x in re.findall(
            rf'<meta[^>]+name=["\']{name}["\'][^>]+content=["\']([^"\']+)',
            text, re.I)]
    title = (meta("citation_title") or [""])[0]
    authors = meta("citation_author")
    pdf = (meta("citation_pdf_url") or [url])[0]
    return title, authors, pdf


def import_papers(limit: int | None = None, offset: int = 0) -> dict[str, int]:
    OUT.mkdir(parents=True, exist_ok=True)
    sess = pf.session()
    held = pf.IndexDedup()
    urls = PAPER_URLS[offset:]
    urls = urls[:limit] if limit else urls
    arxiv = _arxiv_metadata(sess, urls)
    rows = []
    counts = {"downloaded": 0, "held": 0, "failed": 0}
    for url in urls:
        aid = _arxiv_id(url)
        if aid and aid in arxiv:
            title, authors, pdf_url = arxiv[aid]
        else:
            title, authors, pdf_url = _citation_metadata(sess, url)
        if title and held.contains(title):
            status, detail, path = "held", "index title match", None
        else:
            fallback = aid or parse_qs(urlsplit(url).query).get("id", [""])[0]
            fallback = fallback or Path(urlsplit(url).path).stem or "paper"
            stem = pf.safe_stem(authors, title) if title else f"Slack LLM channel - {fallback}"
            path = OUT / f"{stem}.pdf"
            ok, detail = pf.download_pdf(sess, pdf_url, path)
            status = "downloaded" if ok else "failed"
        counts[status] += 1
        print(f"[{status:>10}] {(title or url)[:90]} ({detail})")
        rows.append({
            "source_url": url, "title": title, "status": status, "detail": detail,
            "file": str(path.relative_to(ROOT)) if path and path.exists() else "",
        })
    with REPORT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {REPORT.relative_to(ROOT)}")
    return counts


def import_blogs(limit: int | None = None, dry_run: bool = False,
                 offset: int = 0) -> dict[str, int]:
    sess = _blogs._session()
    posts = BLOG_POSTS[offset:]
    posts = posts[:limit] if limit else posts
    totals = {"kept": 0, "skipped": 0, "dropped": 0}
    for i, (company, url) in enumerate(posts):
        source = _blogs.BlogSource(
            key=f"slack-{i}", company=company, urls=[url],
            keep_re=r"^https?://", base=f"{urlsplit(url).scheme}://{urlsplit(url).netloc}",
            title_xpath="//article//h1 | //main//h1",
            title_override=BLOG_TITLES.get(url, ""),
            raw_markdown="raw.githubusercontent.com" in url,
            min_chars=300,
        )
        result = _blogs.import_source(sess, source, None, 0, dry_run)
        for key in totals:
            totals[key] += result[key]
    return totals


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("papers", "blogs", "all"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0,
                        help="skip this many manifest entries (resume/testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="blogs only: discover and extract without writing")
    args = parser.parse_args(argv)
    if args.command in ("papers", "all"):
        print("Papers:", import_papers(args.limit, args.offset))
    if args.command in ("blogs", "all"):
        print("Blogs:", import_blogs(args.limit, args.dry_run, args.offset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
