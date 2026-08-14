"""API-compatible mock servers for OrcaRouter and ElevenLabs."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

import httpx
import respx

from koebinar.pipeline.tts import estimate_duration_sec, synthesize_silence_wav


VALID_ORCA_KEY = "sk-orca-valid-test-key-0001"
INVALID_ORCA_KEY = "sk-orca-invalid"
VALID_EL_KEY = "xi-el-valid-test-key-0001"
INVALID_EL_KEY = "xi-el-invalid"
FREE_EL_KEY = "xi-el-free-tier-key-0001"


def _auth_bearer(request: httpx.Request) -> str:
    h = request.headers.get("authorization") or ""
    if h.lower().startswith("bearer "):
        return h.split(" ", 1)[1].strip()
    return ""


def _xi_key(request: httpx.Request) -> str:
    return request.headers.get("xi-api-key") or ""


def install_mocks(
    *,
    orca_base: str = "https://api.orcarouter.ai/v1",
    el_base: str = "https://api.elevenlabs.io/v1",
    orca_handler: Optional[Callable[[httpx.Request], httpx.Response]] = None,
) -> respx.MockRouter:
    """Register respx routes. Caller should use as context manager or start()."""
    router = respx.mock(assert_all_called=False)

    models_route = router.get(url__regex=re.compile(rf"{re.escape(orca_base)}/models/?$"))

    def models_side_effect(request: httpx.Request) -> httpx.Response:
        key = _auth_bearer(request)
        if key != VALID_ORCA_KEY:
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "orcarouter/auto", "object": "model"},
                    {"id": "gpt-mock", "object": "model"},
                ],
            },
        )

    models_route.side_effect = models_side_effect

    chat_route = router.post(url__regex=re.compile(rf"{re.escape(orca_base)}/chat/completions/?$"))

    def chat_side_effect(request: httpx.Request) -> httpx.Response:
        key = _auth_bearer(request)
        if key != VALID_ORCA_KEY:
            return httpx.Response(401, json={"error": {"message": "invalid api key"}})
        body = json.loads(request.content.decode("utf-8"))
        if body.get("model") != "orcarouter/auto":
            return httpx.Response(
                401,
                json={
                    "error": {
                        "code": "invalid_model",
                        "message": "Use the orcarouter/auto router model.",
                    }
                },
            )
        if orca_handler:
            return orca_handler(request)
        content = _smart_llm_response(body)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": body.get("model", "orcarouter/auto"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    chat_route.side_effect = chat_side_effect

    sub_route = router.get(url__regex=re.compile(rf"{re.escape(el_base)}/user/subscription/?$"))

    def sub_side_effect(request: httpx.Request) -> httpx.Response:
        key = _xi_key(request)
        if key == FREE_EL_KEY:
            return httpx.Response(
                200,
                json={
                    "tier": "free",
                    "status": "active",
                    "character_count": 100,
                    "character_limit": 10000,
                },
            )
        if key != VALID_EL_KEY:
            return httpx.Response(401, json={"detail": "invalid api key"})
        return httpx.Response(
            200,
            json={
                "tier": "starter",
                "status": "active",
                "character_count": 1200,
                "character_limit": 100000,
            },
        )

    sub_route.side_effect = sub_side_effect

    voices_route = router.get(url__regex=re.compile(rf"{re.escape(el_base)}/voices/?$"))

    def voices_side_effect(request: httpx.Request) -> httpx.Response:
        key = _xi_key(request)
        if key not in (VALID_EL_KEY, FREE_EL_KEY):
            return httpx.Response(401, json={"detail": "invalid api key"})
        return httpx.Response(
            200,
            json={
                "voices": [
                    {
                        "voice_id": "voice_clone_ja_en_01",
                        "name": "Clone Speaker",
                        "category": "cloned",
                        "labels": {"lang": "multilingual"},
                    },
                    {
                        "voice_id": "voice_system_demo",
                        "name": "Demo Voice",
                        "category": "premade",
                    },
                ]
            },
        )

    voices_route.side_effect = voices_side_effect

    tts_route = router.post(url__regex=re.compile(rf"{re.escape(el_base)}/text-to-speech/[^/]+/?$"))

    def tts_side_effect(request: httpx.Request) -> httpx.Response:
        key = _xi_key(request)
        if key not in (VALID_EL_KEY, FREE_EL_KEY):
            return httpx.Response(401, json={"detail": "invalid api key"})
        body = json.loads(request.content.decode("utf-8"))
        text = body.get("text") or ""
        audio = synthesize_silence_wav(estimate_duration_sec(text, "ja"))
        return httpx.Response(200, content=audio, headers={"content-type": "audio/wav"})

    tts_route.side_effect = tts_side_effect

    return router


def _smart_llm_response(body: dict[str, Any]) -> str:
    """Return structured JSON content based on prompt purpose heuristics."""
    messages = body.get("messages") or []
    blob = json.dumps(messages, ensure_ascii=False)
    user = ""
    for m in messages:
        if m.get("role") == "user":
            user = m.get("content") or ""
    try:
        user_obj = json.loads(user) if user.strip().startswith("{") else {}
    except json.JSONDecodeError:
        user_obj = {}

    # Q&A
    if "answer_text" in blob or "answerability" in blob or ("question" in user_obj and "kb" in user_obj):
        kb = user_obj.get("kb") or []
        q = str(user_obj.get("question") or "")
        if not kb:
            return json.dumps(
                {
                    "answer_text": "",
                    "confidence": 0.1,
                    "citations": [],
                    "answerability": "insufficient",
                    "intent": {"type": "general", "value": "general", "confidence": 0.4},
                },
                ensure_ascii=False,
            )
        # build grounded answer from first chunk text
        first = kb[0]
        snippet = str(first.get("text") or "")[:200]
        return json.dumps(
            {
                "answer_text": f"Based on the knowledge base: {snippet}",
                "confidence": max(0.75, float(first.get("score") or 0.8)),
                "citations": [
                    {
                        "document_id": first.get("document_id"),
                        "chunk_id": first.get("chunk_id"),
                        "score": first.get("score", 0.8),
                    }
                ],
                "answerability": "answerable",
                "intent": {"type": "technical_fit" if "api" in q.lower() else "general", "value": "auto", "confidence": 0.7},
            },
            ensure_ascii=False,
        )

    # Outline
    if "outline" in blob.lower() or "sections" in blob or "duration_min" in user_obj:
        theme = user_obj.get("theme") or "Webinar"
        lang = user_obj.get("lang") or "ja"
        n = max(3, min(6, int(user_obj.get("duration_min") or 5)))
        sections = [
            {"index": i, "title": f"{theme} #{i+1}", "purpose": "cover topic", "kb_refs": []}
            for i in range(n)
        ]
        return json.dumps({"theme": theme, "sections": sections, "lang": lang}, ensure_ascii=False)

    # Slides
    if "template" in user_obj and "outline" in user_obj:
        outline = user_obj.get("outline") or {}
        slides = []
        for sec in outline.get("sections") or [{"title": "Intro", "purpose": "start"}]:
            slides.append(
                {
                    "title": sec.get("title", "Slide"),
                    "bullets": [sec.get("purpose", "point"), "detail"],
                    "layout": "title_bullets",
                    "theme": user_obj.get("template", "tech"),
                }
            )
        return json.dumps({"slides": slides, "template": user_obj.get("template", "tech")}, ensure_ascii=False)

    # Script
    if "slides" in user_obj and ("kb" in user_obj or "narration" in blob):
        lang = user_obj.get("lang") or "ja"
        kb = user_obj.get("kb") or []
        refs = [k.get("document_id") for k in kb[:2] if k.get("document_id")]
        slides_out = []
        for i, s in enumerate(user_obj.get("slides") or []):
            title = s.get("title", "Slide")
            if lang == "en":
                narration = f"Let's discuss {title}. This section explains the key ideas clearly."
            else:
                narration = f"{title}について説明します。要点をわかりやすくお伝えします。"
            slides_out.append(
                {
                    "slide_index": i,
                    "title": title,
                    "narration": narration,
                    "references": refs,
                    "grounded": bool(refs),
                }
            )
        return json.dumps({"slides": slides_out, "lang": lang}, ensure_ascii=False)

    # generic
    return json.dumps({"ok": True, "echo": user_obj or user[:200]}, ensure_ascii=False)
