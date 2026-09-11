"""Phase B of `DESIGN-ocr-metadata.md`: OCR image-only and thin-text PDFs locally.

The stage is deliberately **not** part of `index`. It is three orders of magnitude
slower than `pypdf`, so burying it in `index_file()` would make every routine
re-index unpredictable. Instead it writes to the `doc_ocr` cache, and `index`
merely *prefers* that cache when a document's own text layer is missing or thin
(`prefer_ocr` below). Re-indexing therefore never re-OCRs, and a `--reset`
rebuild re-promotes cached pages instead of re-paying for them — the same
property `embedding_cache` and `doc_enrichment` already have.

Inference runs in a **separate interpreter** (`config.OCR_PYTHON`, a venv holding
`mlx-vlm` + `pypdfium2`) driven as a worker subprocess, so this venv stays free of
a GPU stack. The default model, `PaddleOCR-VL-1.5` converted to MLX, runs on
Metal at ~300 tok/s ≈ 5 s/page on an M4 Max: nothing leaves the machine, which is
what makes the stage usable on `Internal/` documents at all.

Usage::

    scripts/.venv/bin/python -m search.cli ocr --only-empty
    scripts/.venv/bin/python -m search.cli ocr --low-density --dpi 300
    scripts/.venv/bin/python -m search.cli ocr --status
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue

from . import config

# How much better a fresh reading has to be before it displaces an existing text
# layer. Above 1 so that noise never flips the choice, low enough that a layer
# with any real damage loses: the two are measured on the same scale, and a
# healthy born-digital PDF beats its own OCR comfortably.
QUALITY_MARGIN = 1.15

# Every backend here runs locally. `mode` maps to the prompt each model expects:
# "text" for reading-order text, "layout" for text plus box tokens.
BACKENDS: dict[str, dict] = {
    "mlx-paddleocr-vl": {
        "model": "mlx-community/PaddleOCR-VL-1.5-bf16",
        "prompts": {"text": "OCR:", "layout": "Spotting:", "table": "Table Recognition:"},
    },
    "mlx-glm-ocr": {
        "model": "mlx-community/GLM-OCR-bf16",
        "prompts": {"text": "OCR:", "layout": "Spotting:"},
    },
    "mlx-deepseek-ocr-2": {
        "model": "mlx-community/DeepSeek-OCR-2-bf16",
        "prompts": {"text": "<image>\nFree OCR.",
                    "layout": "<image>\nConvert the document to markdown."},
    },
    "mlx-granite-docling": {
        "model": "ibm-granite/granite-docling-258M-mlx",
        "prompts": {"text": "Convert this page to docling.",
                    "layout": "Convert this page to docling."},
    },
}

# Box tokens PaddleOCR-VL emits in layout mode. Stripped for the plain-text
# reduction that gets chunked and embedded; kept in `markdown` for later use.
_LOC_RE = re.compile(r"<\|LOC_\d+\|>")
_MIN_PAGE_CHARS = 40
_BLANK_INK = 0.005          # below this the page really is empty paper
_MAX_REPETITION = 0.30      # share of duplicated 10-grams before output is rejected


def backend_config(name: str | None = None) -> tuple[str, dict]:
    name = (name or config.OCR_BACKEND).strip().lower()
    if name not in BACKENDS:
        raise SystemExit(f"unknown OCR backend {name!r}; known: {', '.join(BACKENDS)}")
    spec = dict(BACKENDS[name])
    if config.OCR_MODEL:
        spec["model"] = config.OCR_MODEL
    return name, spec


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def ensure_schema(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_ocr (
            doc_id TEXT,
            page INTEGER,
            backend TEXT,
            model TEXT,
            dpi INTEGER,
            mode TEXT,
            text TEXT,
            markdown TEXT,
            ocr_status TEXT,
            repetition_ratio DOUBLE,
            ink_coverage DOUBLE,
            n_chars INTEGER,
            seconds DOUBLE,
            created_at TIMESTAMP,
            PRIMARY KEY (doc_id, page, model, dpi)
        )
        """
    )


# ---------------------------------------------------------------------------
# selection policy
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    doc_id: str
    path: Path
    rel_path: str
    n_pages: int
    chars_per_page: float | None
    reason: str

    @property
    def pages(self) -> list[int]:
        return list(range(max(self.n_pages, 1)))


def candidates(con, only_empty: bool = False, low_density: bool = False,
               front_matter: bool = False, doc_id: str | None = None,
               limit: int | None = None) -> list[Candidate]:
    """OCR candidates, newest policy from the design.

    The `filetype = '.pdf'` guard is load-bearing, not decoration: without it the
    low-density rule sweeps up short `.md`, `.docx`, `.pptx` and `.bpmn` files
    that are simply brief, not scanned.
    """
    from . import metadata as metamod

    metamod.ensure_schema(con)
    where = ["filetype = '.pdf'"]
    if doc_id:
        where.append("doc_id = ?")
        params = [doc_id]
    else:
        params = []
        rules = []
        if only_empty or not (low_density or front_matter):
            # A garbled layer belongs here rather than under `low_density`: the
            # page has plenty of extractable characters, none of them language,
            # so by volume it looks healthy while being just as unreadable as a
            # scan.
            rules.append("(is_image_only OR n_chunks = 0 OR has_text_layer = FALSE"
                         " OR text_garbled)")
        if low_density:
            rules.append(f"(chars_per_page < {config.OCR_MIN_CHARS_PER_PAGE})")
        if front_matter:
            rules.append("TRUE")
        where.append("(" + " OR ".join(rules) + ")")

    sql = (f"SELECT doc_id, path, rel_path, coalesce(n_pages, 0), chars_per_page, "
           f"coalesce(is_image_only, FALSE), coalesce(text_garbled, FALSE) "
           f"FROM documents WHERE {' AND '.join(where)} "
           f"ORDER BY coalesce(n_pages, 0)")
    if limit:
        sql += f" LIMIT {int(limit)}"

    out = []
    for (did, path, rel, n_pages, cpp, image_only,
         garbled) in con.execute(sql, params).fetchall():
        reason = ("image-only" if image_only else
                  "garbled text layer" if garbled else
                  "no text layer" if not cpp else f"{cpp:.0f} chars/page")
        out.append(Candidate(did, Path(path), rel, n_pages, cpp, reason))
    return out


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def repetition_ratio(text: str, n: int = 10) -> float:
    """Share of word n-grams that are duplicates.

    Degeneration into a repeated phrase is a documented property of this model
    class, not an edge case, so output is checked rather than trusted.
    """
    words = text.split()
    if len(words) < n * 2:
        return 0.0
    grams = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
    return 1.0 - (len(set(grams)) / len(grams))


def classify(text: str, ink: float | None) -> tuple[str, float]:
    rep = repetition_ratio(text)
    stripped = _LOC_RE.sub("", text).strip()
    if rep > _MAX_REPETITION:
        return "repetition", rep
    if len(stripped) < _MIN_PAGE_CHARS:
        if ink is not None and ink < _BLANK_INK:
            return "blank", rep
        return "low_yield", rep
    return "ok", rep


def plain_text(raw: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", _LOC_RE.sub("", raw)).strip()


# ---------------------------------------------------------------------------
# worker
# ---------------------------------------------------------------------------


class Worker:
    """The OCR interpreter, spawned once and kept warm.

    A model load costs ~1 s warm and ~3 minutes cold (weights download), so the
    process outlives individual documents. It is restarted only when a page
    exceeds `config.OCR_PAGE_TIMEOUT`, since MLX generation cannot be interrupted
    from outside.
    """

    def __init__(self, model: str):
        self.model = model
        self.proc: subprocess.Popen | None = None
        self.queue: Queue = Queue()
        self.req_id = 0

    def start(self) -> None:
        if not config.OCR_PYTHON.exists():
            raise SystemExit(
                f"OCR interpreter not found: {config.OCR_PYTHON}\n"
                f"  create it with:  uv venv --python 3.13 scripts/.venv-ocr && "
                f"uv pip install --python scripts/.venv-ocr/bin/python mlx-vlm pypdfium2")
        script = Path(__file__).with_name("ocr_worker.py")
        self.proc = subprocess.Popen(
            [str(config.OCR_PYTHON), str(script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            text=True, bufsize=1)
        self.queue = Queue()
        threading.Thread(target=self._pump, args=(self.proc,), daemon=True).start()

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if line:
                self.queue.put(line)
        self.queue.put(None)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")  # type: ignore[union-attr]
                self.proc.stdin.flush()  # type: ignore[union-attr]
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        self.proc = None

    def restart(self) -> None:
        if self.proc:
            self.proc.kill()
            self.proc = None
        self.start()

    def pages(self, pdf: Path, pages: list[int], dpi: int, prompt: str):
        """Yield one result dict per page, restarting the worker on a timeout.

        The loop runs until the worker's `done` sentinel arrives, **not** until
        the expected pages have been seen. Returning early on the latter leaves
        the sentinel in the queue, and every later document then reads one
        message behind — silently storing each document's text against its
        predecessor. `req_id` makes that class of desynchronization detectable
        instead of merely unlikely: a message from a previous request is dropped
        rather than attributed to the current document.
        """
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        self.req_id += 1
        req_id = self.req_id
        request = {"req_id": req_id, "pdf": str(pdf), "pages": pages, "dpi": dpi,
                   "prompt": prompt, "model": self.model,
                   "max_tokens": config.OCR_MAX_TOKENS, "max_edge": config.OCR_MAX_EDGE}
        self.proc.stdin.write(json.dumps(request) + "\n")  # type: ignore[union-attr]
        self.proc.stdin.flush()  # type: ignore[union-attr]

        pending = list(pages)
        while True:
            try:
                line = self.queue.get(timeout=config.OCR_PAGE_TIMEOUT)
            except Empty:
                yield {"type": "page", "page": pending[0] if pending else None,
                       "error": f"timeout after {config.OCR_PAGE_TIMEOUT:.0f}s"}
                self.restart()
                return
            if line is None:
                yield {"type": "page", "page": pending[0] if pending else None,
                       "error": "worker exited"}
                self.restart()
                return
            msg = json.loads(line)
            if msg.get("req_id") not in (None, req_id):
                continue  # stale message from an abandoned request
            if msg.get("type") == "done":
                return
            if msg.get("type") == "fatal":
                yield {"type": "page", "page": pending[0] if pending else None,
                       "error": msg.get("error", "fatal")}
                self.restart()
                return
            if msg.get("page") in pending:
                pending.remove(msg["page"])
            yield msg


# ---------------------------------------------------------------------------
# the stage
# ---------------------------------------------------------------------------


def done_pages(con, doc_id: str, model: str, dpi: int) -> set[int]:
    rows = con.execute(
        "SELECT page FROM doc_ocr WHERE doc_id = ? AND model = ? AND dpi = ?",
        [doc_id, model, dpi]).fetchall()
    return {r[0] for r in rows}


def failed_pages(con, doc_id: str, model: str, dpi: int,
                 statuses: tuple[str, ...] = ("error",)) -> list[int]:
    """Pages a previous run could not read, for a targeted retry.

    Only `error` by default. `blank` is a correct answer about an empty page, and
    `repetition` at temperature 0 would reproduce itself — that one needs a
    different dpi or backend, not a repeat.
    """
    marks = ",".join("?" * len(statuses))
    rows = con.execute(
        f"""SELECT page FROM doc_ocr WHERE doc_id = ? AND model = ? AND dpi = ?
            AND ocr_status IN ({marks}) ORDER BY page""",
        [doc_id, model, dpi, *statuses]).fetchall()
    return [r[0] for r in rows]


def run(con, only_empty: bool = False, low_density: bool = False,
        front_matter: bool = False, doc_id: str | None = None,
        mode: str = "text", dpi: int | None = None, backend: str | None = None,
        limit: int | None = None, max_pages: int | None = None,
        redo: bool = False, retry_failed: bool = False) -> dict:
    ensure_schema(con)
    name, spec = backend_config(backend)
    model, dpi = spec["model"], dpi or config.OCR_DPI
    prompt = spec["prompts"].get(mode) or spec["prompts"]["text"]

    todo = candidates(con, only_empty, low_density, front_matter, doc_id, limit)
    if front_matter:
        for c in todo:
            c.n_pages = min(c.n_pages or 2, 2)

    total_pages = sum(min(len(c.pages), max_pages or 10**6) for c in todo)
    print(f"OCR backend={name} model={model} dpi={dpi} mode={mode}")
    print(f"{len(todo)} documents, up to {total_pages} pages\n")

    stats = {"documents": 0, "pages": 0, "ok": 0, "blank": 0, "low_yield": 0,
             "repetition": 0, "error": 0, "skipped_pages": 0, "chars": 0, "seconds": 0.0}
    worker = Worker(model)
    try:
        for i, cand in enumerate(todo, 1):
            if not cand.path.exists():
                print(f"[{i}/{len(todo)}] missing file: {cand.rel_path}")
                continue
            if retry_failed:
                pages = failed_pages(con, cand.doc_id, model, dpi)
            else:
                pages = cand.pages[:max_pages] if max_pages else cand.pages
                if not redo:
                    already = done_pages(con, cand.doc_id, model, dpi)
                    stats["skipped_pages"] += len(already & set(pages))
                    pages = [p for p in pages if p not in already]
            if not pages:
                continue
            print(f"[{i}/{len(todo)}] {cand.rel_path[:76]}\n"
                  f"          {len(pages)} pages ({cand.reason})")
            stats["documents"] += 1

            for msg in worker.pages(cand.path, pages, dpi, prompt):
                page = msg.get("page")
                if msg.get("error"):
                    status, raw, text, rep, ink, secs = (
                        "error", msg["error"], "", None, None, msg.get("seconds", 0.0))
                else:
                    raw = msg.get("text") or ""
                    ink = msg.get("ink")
                    status, rep = classify(raw, ink)
                    text = plain_text(raw)
                    secs = msg.get("seconds", 0.0)
                con.execute(
                    """
                    INSERT OR REPLACE INTO doc_ocr
                        (doc_id, page, backend, model, dpi, mode, text, markdown,
                         ocr_status, repetition_ratio, ink_coverage, n_chars,
                         seconds, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
                    """,
                    [cand.doc_id, page, name, model, dpi, mode, text, raw, status,
                     rep, ink, len(text), secs],
                )
                stats["pages"] += 1
                stats[status] = stats.get(status, 0) + 1
                stats["chars"] += len(text)
                stats["seconds"] += secs or 0.0
                flag = " " if status == "ok" else "!"
                print(f"   {flag} p{(page or 0) + 1:<4} {status:10s} {len(text):>6d} chars"
                      f"  {secs:5.1f}s" + (f"  {msg['error'][:60]}" if msg.get("error") else ""))
    finally:
        worker.stop()

    per_page = stats["seconds"] / stats["pages"] if stats["pages"] else 0
    print(f"\ndocuments={stats['documents']} pages={stats['pages']} ok={stats['ok']} "
          f"blank={stats['blank']} low_yield={stats['low_yield']} "
          f"repetition={stats['repetition']} error={stats['error']} "
          f"skipped={stats['skipped_pages']}")
    print(f"{stats['chars']:,} chars in {stats['seconds'] / 60:.1f} min "
          f"({per_page:.1f}s/page)")
    return stats


# ---------------------------------------------------------------------------
# promotion into the index
# ---------------------------------------------------------------------------


def cached_pages(con, doc_id: str) -> list[tuple[int, str]]:
    """Usable OCR text for a document as `(page_no, text)`, 1-based like extract."""
    try:
        rows = con.execute(
            """
            SELECT page, text FROM doc_ocr
            WHERE doc_id = ? AND ocr_status = 'ok' AND text IS NOT NULL
            ORDER BY dpi DESC, page
            """, [doc_id]).fetchall()
    except Exception:  # noqa: BLE001  — table absent on a fresh index
        return []
    best: dict[int, str] = {}
    for page, text in rows:
        best.setdefault(page, text)
    return [(p + 1, best[p]) for p in sorted(best)]


def prefer_ocr(con, doc_id: str, ex) -> bool:
    """Substitute cached OCR text into an `ExtractedDoc` whose own text is thin.

    Called from `index_file`. Only a document that the text layer failed on is
    overridden, so a born-digital PDF is never displaced by a model's reading of
    a picture of itself.

    "Failed" is decided by *comparing the two texts*, not by testing the existing
    one against a threshold. Thresholds belong to candidate selection, where the
    question is absolute; here the question is relative, and a threshold answers
    it badly — a document near the bar keeps its unusable layer whenever the
    flagging stage and this one sample it differently, silently wasting the OCR
    that was already paid for. Volume still settles the *thin* case, where there
    is no readable text on either side to compare.
    """
    from . import metadata as metamod

    ocr = cached_pages(con, doc_id)
    if not ocr:
        return False
    own_chars = sum(len(t) for _, t in ex.pages)
    if own_chars / max(ex.n_pages, 1) < config.OCR_MIN_CHARS_PER_PAGE:
        if sum(len(t) for _, t in ocr) <= own_chars:
            return False
    else:
        own = metamod.readability(metamod.spread_sample([t for _, t in ex.pages]))
        fresh = metamod.readability(metamod.spread_sample([t for _, t in ocr]))
        if fresh is None or (own is not None and fresh <= own * QUALITY_MARGIN):
            return False
    ex.pages = ocr
    ex.n_pages = max(ex.n_pages, max(p for p, _ in ocr))
    if not ex.abstract:
        ex.abstract = metamod.abstract_from_text("\n".join(t for _, t in ocr[:3]))
    return True


def status(con) -> list[tuple[str, str]]:
    ensure_schema(con)
    rows = [
        ("documents with OCR", "SELECT count(DISTINCT doc_id) FROM doc_ocr"),
        ("pages OCR'd", "SELECT count(*) FROM doc_ocr"),
        ("  ok", "SELECT count(*) FROM doc_ocr WHERE ocr_status = 'ok'"),
        ("  blank", "SELECT count(*) FROM doc_ocr WHERE ocr_status = 'blank'"),
        ("  low_yield", "SELECT count(*) FROM doc_ocr WHERE ocr_status = 'low_yield'"),
        ("  repetition", "SELECT count(*) FROM doc_ocr WHERE ocr_status = 'repetition'"),
        ("  error", "SELECT count(*) FROM doc_ocr WHERE ocr_status = 'error'"),
        ("chars recovered", "SELECT coalesce(sum(n_chars), 0) FROM doc_ocr"),
        ("minutes of inference", "SELECT round(coalesce(sum(seconds), 0) / 60, 1) FROM doc_ocr"),
        ("candidates still untouched",
         """SELECT count(*) FROM documents d WHERE d.filetype = '.pdf'
            AND (d.is_image_only OR d.text_garbled OR d.chars_per_page < """
         f"""{config.OCR_MIN_CHARS_PER_PAGE})
            AND NOT EXISTS (SELECT 1 FROM doc_ocr o WHERE o.doc_id = d.doc_id)"""),
    ]
    out = []
    for label, sql in rows:
        try:
            value = con.execute(sql).fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            value = f"n/a ({exc})"
        out.append((label, f"{value:,}" if isinstance(value, int) else str(value)))
    return out
