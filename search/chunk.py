"""Paragraph-aware, character-bounded chunking with overlap."""

from __future__ import annotations

import re


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for para in paragraphs:
        if len(para) > size:
            flush()
            step = max(1, size - overlap)
            for i in range(0, len(para), step):
                chunks.append(para[i : i + size])
            continue
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}" if current else para
        else:
            flush()
            current = para
    flush()

    # Prepend a small tail of the previous chunk for continuity.
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            tail = prev[-overlap:]
            overlapped.append(f"{tail} {cur}" if tail else cur)
        chunks = overlapped

    return chunks
