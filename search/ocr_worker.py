"""OCR worker: rasterize PDF pages and run a local document-parsing VLM on them.

This file is executed by a **different interpreter** than the rest of the search
package — `scripts/.venv-ocr/bin/python`, which has `mlx-vlm` and `pypdfium2`
installed (see `config.OCR_PYTHON`). It therefore imports nothing from `search`
and must stay standalone.

Protocol: one JSON request per line on stdin, one JSON response per line on
stdout. Responses stream *per page*, so the parent can checkpoint a long book
without waiting for the whole request. Anything the model libraries print goes to
stderr, keeping stdout a clean JSON channel.

    -> {"pdf": "/path/x.pdf", "pages": [0,1], "dpi": 200, "prompt": "OCR:"}
    <- {"type":"page","page":0,"text":"…","seconds":4.6,"tps":310.4}
    <- {"type":"page","page":1,"error":"…"}
    <- {"type":"done"}

The model is loaded on first use and kept resident: a warm load is ~1 s against
~170 s for the initial download, so one worker per run matters.
"""

import json
import sys
import time
import traceback
from pathlib import Path

_STATE: dict = {}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _load(model_path: str):
    if "model" not in _STATE:
        t0 = time.time()
        from mlx_vlm import load

        model, processor = _STATE["loaded"] = load(model_path)
        _STATE["model"], _STATE["processor"] = model, processor
        _log(f"[worker] loaded {model_path} in {time.time() - t0:.1f}s")
    return _STATE["model"], _STATE["processor"]


def _render(pdf: Path, page: int, dpi: int, max_edge: int, out: Path) -> tuple[int, int]:
    import pypdfium2 as pdfium

    doc = _STATE.get("pdfium_doc")
    if _STATE.get("pdfium_path") != str(pdf) or doc is None:
        if doc is not None:
            doc.close()
        doc = pdfium.PdfDocument(str(pdf))
        _STATE["pdfium_doc"], _STATE["pdfium_path"] = doc, str(pdf)
    pg = doc[page]
    scale = dpi / 72
    # Clamp the long edge: rendering a poster-sized page at 200 dpi wastes both
    # rasterizer time and vision tokens for no gain in legibility.
    width_pt, height_pt = pg.get_size()
    longest = max(width_pt, height_pt) * scale
    if longest > max_edge:
        scale *= max_edge / longest
    image = pg.render(scale=scale).to_pil().convert("RGB")
    image.save(out)
    _STATE["ink"] = _ink_coverage(image)
    return image.size


def _ink_coverage(image) -> float:
    """Fraction of non-white pixels, downsampled.

    Lets the parent tell a genuinely blank page (skip it) from a page that has
    ink the model failed to read (retry it at higher dpi) — the distinction the
    yield guard in the design needs and cannot make from text length alone.
    """
    small = image.convert("L").resize((200, 260))
    histogram = small.histogram()
    return round(sum(histogram[:200]) / (200 * 260), 5)


def _generate(model, processor, image: Path, prompt: str, max_tokens: int):
    """Generate for one page, retrying once through a Metal command-buffer timeout.

    `kIOGPUCommandBufferCallbackErrorTimeout` is the macOS GPU watchdog firing,
    not a bad page: it shows up when a long generation coincides with other GPU
    work. Dropping MLX's buffer cache and retrying recovers the page, and pages
    that genuinely provoke it (the model looping on a noisy scan) are caught
    afterwards by the repetition guard.
    """
    import mlx.core as mx
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    cfg = getattr(model, "config", {})
    templated = apply_chat_template(processor, cfg, prompt, num_images=1)
    for attempt in (0, 1):
        try:
            result = generate(model, processor, templated, image=[str(image)],
                              max_tokens=max_tokens, temperature=0.0, verbose=False)
            break
        except RuntimeError as exc:
            if "METAL" not in str(exc) or attempt == 1:
                raise
            _log(f"[worker] Metal timeout, clearing cache and retrying: {exc}")
            mx.clear_cache()
            time.sleep(2.0)
    text = result.text if hasattr(result, "text") else str(result)
    # Page images are large; without this the buffer cache grows across a long
    # book until allocation pressure starts causing the very timeouts above.
    mx.clear_cache()
    return text, getattr(result, "generation_tps", None)


def handle(req: dict) -> None:
    pdf = Path(req["pdf"])
    dpi = int(req.get("dpi", 200))
    max_edge = int(req.get("max_edge", 2200))
    prompt = req.get("prompt", "OCR:")
    max_tokens = int(req.get("max_tokens", 6144))
    model, processor = _load(req["model"])
    tmp = Path(req.get("tmp_dir", "/tmp")) / "search-ocr-page.png"

    req_id = req.get("req_id")
    for page in req["pages"]:
        out: dict = {"type": "page", "req_id": req_id, "page": page}
        t0 = time.time()
        try:
            size = _render(pdf, page, dpi, max_edge, tmp)
            text, tps = _generate(model, processor, tmp, prompt, max_tokens)
            out.update(text=text, tps=tps, width=size[0], height=size[1],
                       ink=_STATE.get("ink"))
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
            _log(traceback.format_exc())
        out["seconds"] = round(time.time() - t0, 2)
        print(json.dumps(out, ensure_ascii=False), flush=True)
    print(json.dumps({"type": "done", "req_id": req_id}), flush=True)


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"type": "fatal", "error": f"bad request: {exc}"}), flush=True)
            continue
        if req.get("cmd") == "quit":
            doc = _STATE.pop("pdfium_doc", None)
            if doc is not None:
                doc.close()
            return 0
        try:
            handle(req)
        except Exception as exc:  # noqa: BLE001
            _log(traceback.format_exc())
            print(json.dumps({"type": "fatal", "req_id": req.get("req_id"),
                              "error": f"{type(exc).__name__}: {exc}"}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
