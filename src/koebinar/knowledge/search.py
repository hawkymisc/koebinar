"""Lightweight embedding + ranking (pure, deterministic)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Iterable, Sequence

from koebinar.models import Chunk


_TOKEN = re.compile(r"[\w\u3040-\u30ff\u4e00-\u9fff]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def _stable_token_index(tok: str, dim: int) -> int:
    """Process-stable hash index (avoid PYTHONHASHSEED-dependent hash())."""
    digest = hashlib.md5(tok.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % dim


def embed_text(text: str, dim: int = 64) -> list[float]:
    """Hashing-trick bag-of-words embedding into fixed dimension."""
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    counts = Counter(tokens)
    for tok, cnt in counts.items():
        idx = _stable_token_index(tok, dim)
        vec[idx] += float(cnt)
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


_STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "in", "on", "for",
    "and", "or", "how", "what", "when", "where", "who", "which", "do", "does", "did",
    "with", "from", "this", "that", "it", "as", "at", "by", "about", "please",
}


def _stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("ing"):
        return tok[:-3]
    if len(tok) > 3 and tok.endswith("es"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s"):
        return tok[:-1]
    return tok


def lexical_overlap(query: str, text: str) -> float:
    """Overlap on content tokens with light stemming; ignore stopwords."""
    qt = {_stem(t) for t in tokenize(query) if t not in _STOP and len(t) > 1}
    tt = {_stem(t) for t in tokenize(text) if t not in _STOP and len(t) > 1}
    if not qt or not tt:
        return 0.0
    inter = 0
    for q in qt:
        if q in tt or any(q in d or d in q for d in tt if min(len(q), len(d)) >= 3):
            inter += 1
    return inter / float(len(qt))


def hybrid_score(query: str, text: str, emb_q: Sequence[float], emb_doc: Sequence[float]) -> float:
    cos = cosine(emb_q, emb_doc)
    lex = lexical_overlap(query, text)
    # Prefer lexical signal for short technical queries; still use cosine for soft matches.
    return max(0.0, min(1.0, 0.35 * cos + 0.65 * lex))


def rank_chunks(
    query: str,
    chunks: Iterable[Chunk],
    *,
    top_k: int = 10,
) -> list[tuple[Chunk, float]]:
    q = embed_text(query)
    scored: list[tuple[Chunk, float]] = []
    for ch in chunks:
        emb = ch.embedding or embed_text(ch.text)
        scored.append((ch, hybrid_score(query, ch.text, q, emb)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def select_context(scored: Sequence[tuple[Chunk, float]], top_n: int = 5) -> list[tuple[Chunk, float]]:
    return list(scored[:top_n])
