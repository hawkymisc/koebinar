"""Confidence gate pure logic for Q&A."""

from __future__ import annotations

from typing import Any, Sequence

from koebinar.models import Answerability, Citation


HOLD_MESSAGE_JA = "ご質問ありがとうございます。現時点では資料から十分な根拠を確認できなかったため、担当者が確認のうえ回答します。"
HOLD_MESSAGE_EN = "Thank you for your question. We could not find sufficient evidence in the knowledge base, so a human will follow up."


def gate_answer(
    *,
    answer_text: str,
    confidence: float,
    citations: Sequence[Citation] | Sequence[dict[str, Any]],
    threshold: float = 0.7,
    lang: str = "ja",
) -> tuple[str, float, Answerability, list[Citation]]:
    """Apply confidence gate: no citations or low confidence → hold."""
    cites = _normalize_citations(citations)
    conf = _clamp(confidence)
    if not cites or conf < threshold:
        msg = HOLD_MESSAGE_EN if lang == "en" else HOLD_MESSAGE_JA
        return msg, conf if cites else min(conf, 0.0), Answerability.INSUFFICIENT, list(cites)
    return answer_text, conf, Answerability.ANSWERABLE, list(cites)


def score_from_retrieval(scores: Sequence[float], *, empty_confidence: float = 0.0) -> float:
    if not scores:
        return empty_confidence
    # blend top score with coverage of top-5
    top = max(scores)
    mean_top = sum(sorted(scores, reverse=True)[:5]) / min(5, len(scores))
    return _clamp(0.6 * top + 0.4 * mean_top)


def classify_intent(message: str) -> dict[str, Any]:
    """Lightweight keyword intent classification (MVP)."""
    m = (message or "").lower()
    rules = [
        ("pricing", ["price", "pricing", "cost", "料金", "価格", "費用"]),
        ("security", ["security", "soc2", "iso", "セキュリティ", "暗号化"]),
        ("timeline", ["when", "timeline", "schedule", "いつ", "時期", "スケジュール"]),
        ("technical_fit", ["api", "integrate", "sdk", "連携", "技術", "実装"]),
        ("competition", ["competitor", "vs", "比較", "競合"]),
        ("decision_process", ["decision", "approve", "決裁", "導入判断"]),
        ("problem", ["problem", "pain", "課題", "困って"]),
        ("negative", ["not interested", "cancel", "不要", "やめる"]),
    ]
    for label, kws in rules:
        if any(k in m for k in kws):
            return {"type": label, "value": label, "confidence": 0.7}
    return {"type": "general", "value": "general", "confidence": 0.4}


def _normalize_citations(citations: Sequence[Any]) -> list[Citation]:
    out: list[Citation] = []
    for c in citations:
        if isinstance(c, Citation):
            out.append(c)
        elif isinstance(c, dict):
            out.append(
                Citation(
                    document_id=str(c.get("document_id", "")),
                    chunk_id=str(c.get("chunk_id", "")),
                    score=float(c.get("score") or 0.0),
                )
            )
    return [c for c in out if c.document_id or c.chunk_id]


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))
