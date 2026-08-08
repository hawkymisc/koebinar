"""Pronunciation dictionary application and sentence splitting (pure)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


def load_pronunciation_dict(path: Path | str) -> list[tuple[str, str]]:
    """Load TSV: surface<TAB>reading. Longer surfaces first for greedy replace."""
    p = Path(path)
    if not p.exists():
        return []
    entries: list[tuple[str, str]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        surface, reading = parts[0].strip(), parts[1].strip()
        if surface and reading:
            entries.append((surface, reading))
    entries.sort(key=lambda x: len(x[0]), reverse=True)
    return entries


def apply_pronunciation(text: str, dictionary: Iterable[tuple[str, str]]) -> str:
    result = text or ""
    for surface, reading in dictionary:
        if surface in result:
            result = result.replace(surface, reading)
    return result


_JA_SENTENCE_END = re.compile(r"(?<=[。！？!?])\s*")
_EN_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str, lang: str = "ja") -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if lang == "en":
        parts = _EN_SENTENCE_END.split(text)
    else:
        parts = _JA_SENTENCE_END.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def split_for_tts(text: str, lang: str = "ja") -> list[str]:
    """JA: sentence-level; EN: paragraph-level allowed (split on blank lines then sentences)."""
    if lang == "en":
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text or "") if p.strip()]
        if len(paragraphs) > 1:
            return paragraphs
        return split_sentences(text, lang="en") or ([text.strip()] if text and text.strip() else [])
    return split_sentences(text, lang="ja")


def estimate_tts_credits(text: str) -> int:
    """Simple character-count credit estimate."""
    return len(text or "")
