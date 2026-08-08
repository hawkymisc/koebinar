"""Text chunking utilities (pure)."""

from __future__ import annotations

import re
from typing import Iterable


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n+", text or "")
    return [normalize_whitespace(p) for p in parts if normalize_whitespace(p)]


def chunk_text(
    text: str,
    *,
    max_chars: int = 500,
    overlap: int = 50,
) -> list[str]:
    """Split text into overlapping character windows preferring paragraph boundaries."""
    if not text or not text.strip():
        return []
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        paragraphs = [normalize_whitespace(text)]

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if not buf:
            buf = para
        elif len(buf) + 1 + len(para) <= max_chars:
            buf = f"{buf} {para}"
        else:
            chunks.extend(_window(buf, max_chars, overlap))
            buf = para
    if buf:
        chunks.extend(_window(buf, max_chars, overlap))
    return [c for c in chunks if c]


def _window(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    start = 0
    step = max(1, max_chars - max(0, overlap))
    while start < len(text):
        end = min(len(text), start + max_chars)
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start += step
    return [c for c in out if c]


def estimate_section(index: int, total: int) -> str:
    if total <= 0:
        return "body"
    ratio = index / total
    if ratio < 0.2:
        return "intro"
    if ratio > 0.8:
        return "outro"
    return "body"


def extract_text_from_pdf_payload(content: str) -> str:
    """MVP: accept pre-extracted PDF text or a pseudo-PDF marker payload."""
    if content.startswith("%PDF"):
        # Minimal pseudo-PDF: extract text between stream markers or fall back
        m = re.findall(r"BT\s*(.*?)\s*ET", content, flags=re.DOTALL)
        if m:
            return normalize_whitespace(" ".join(m))
        # strip binary-looking noise
        return normalize_whitespace(re.sub(r"[^\x20-\x7E\u3040-\u30ff\u4e00-\u9fff\n]", " ", content))
    return content


def extract_text_from_url_payload(content: str) -> str:
    """MVP: URL source stores fetched/provided body text (not live crawl in unit path)."""
    if content.startswith("http://") or content.startswith("https://"):
        return f"URL content placeholder for {content}"
    return content
