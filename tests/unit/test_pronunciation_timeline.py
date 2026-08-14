"""Unit tests for pronunciation, TTS helpers, timeline math."""

from pathlib import Path

import pytest

from koebinar.pipeline.pronunciation import (
    apply_pronunciation,
    estimate_tts_credits,
    load_pronunciation_dict,
    split_for_tts,
    split_sentences,
)
from koebinar.pipeline.renderer import build_minimal_mp4, remotion_available
from koebinar.pipeline.timeline import (
    build_timeline,
    frames_to_seconds,
    seconds_to_frames,
    validate_timeline,
)
from koebinar.pipeline.tts import cache_key, estimate_duration_sec, synthesize_silence_wav, wav_duration_sec
from koebinar.qa.confidence import (
    HOLD_MESSAGE_EN,
    HOLD_MESSAGE_JA,
    classify_intent,
    gate_answer,
    score_from_retrieval,
)
from koebinar.models import Answerability, Citation


def test_load_and_apply_dict():
    path = Path(__file__).resolve().parents[2] / "data" / "pronunciation_dict.tsv"
    d = load_pronunciation_dict(path)
    assert d
    text = apply_pronunciation("Koebinar uses OrcaRouter", d)
    assert "コエビナー" in text
    assert "オルカルーター" in text


def test_load_missing_dict():
    assert load_pronunciation_dict("/nonexistent/path.tsv") == []


def test_split_sentences_ja_en():
    ja = split_sentences("こんにちは。今日は良い天気ですね！本当ですか？", "ja")
    assert len(ja) == 3
    en = split_sentences("Hello. How are you? Fine!", "en")
    assert len(en) >= 2
    assert split_sentences("", "ja") == []
    assert split_for_tts("Para one.\n\nPara two.", "en") == ["Para one.", "Para two."]


def test_timeline_math():
    assert seconds_to_frames(1.0, 30) == 30
    assert frames_to_seconds(30, 30) == 1.0
    with pytest.raises(ValueError):
        seconds_to_frames(-1, 30)
    with pytest.raises(ValueError):
        seconds_to_frames(1, 0)
    with pytest.raises(ValueError):
        frames_to_seconds(-1, 30)


def test_build_and_validate_timeline():
    slides = [{"title": "A"}, {"title": "B"}]
    durations = [
        {"slide_index": 0, "sentence_index": 0, "duration_sec": 1.0, "audio_uri": "a.wav"},
        {"slide_index": 1, "sentence_index": 0, "duration_sec": 2.0, "audio_uri": "b.wav"},
    ]
    tl = build_timeline(slides, durations, fps=30)
    assert tl["total_frames"] == 90
    assert validate_timeline(tl) == []
    assert validate_timeline({"fps": 0, "total_frames": 0, "slides": []})


def test_build_timeline_rejects_audio_for_a_missing_slide():
    with pytest.raises(ValueError, match="slide_index out of range"):
        build_timeline(
            [{"title": "Only slide"}],
            [
                {
                    "slide_index": 1,
                    "sentence_index": 0,
                    "duration_sec": 1.0,
                    "audio_uri": "orphan.wav",
                }
            ],
            fps=30,
        )


def test_validate_timeline_rejects_audio_for_a_missing_slide():
    timeline = build_timeline(
        [{"title": "Only slide"}],
        [
            {
                "slide_index": 0,
                "sentence_index": 0,
                "duration_sec": 1.0,
                "audio_uri": "audio.wav",
            }
        ],
        fps=30,
    )
    timeline["audio_clips"][0]["slide_index"] = 1

    assert "audio clip 0 references missing slide 1" in validate_timeline(timeline)


def test_tts_helpers():
    k1 = cache_key("hi", "v1", "m1")
    k2 = cache_key("hi", "v1", "m1")
    k3 = cache_key("yo", "v1", "m1")
    assert k1 == k2 and k1 != k3
    wav = synthesize_silence_wav(0.5)
    assert wav[:4] == b"RIFF"
    assert wav_duration_sec(wav) == pytest.approx(0.5, abs=0.05)
    assert wav_duration_sec(b"not-wav") is None
    assert estimate_duration_sec("abcd", "en") > 0
    assert estimate_tts_credits("abc") == 3


def test_renderer_minimal_mp4():
    tl = build_timeline([{"title": "T"}], [{"slide_index": 0, "duration_sec": 1.0}], fps=30)
    data = build_minimal_mp4(tl, [{"title": "T"}])
    assert data[4:8] == b"ftyp"
    assert b"mdat" in data
    assert isinstance(remotion_available(), bool)


def test_confidence_gate_hold_and_answer():
    text, conf, ability, cites = gate_answer(
        answer_text="ans",
        confidence=0.9,
        citations=[Citation(document_id="d", chunk_id="c", score=0.9)],
        threshold=0.7,
        lang="ja",
    )
    assert ability == Answerability.ANSWERABLE
    assert text == "ans"

    text2, _, ability2, _ = gate_answer(
        answer_text="ans",
        confidence=0.2,
        citations=[Citation(document_id="d", chunk_id="c", score=0.2)],
        threshold=0.7,
        lang="en",
    )
    assert ability2 == Answerability.INSUFFICIENT
    assert text2 == HOLD_MESSAGE_EN

    text3, _, ability3, _ = gate_answer(answer_text="x", confidence=0.9, citations=[], lang="ja")
    assert ability3 == Answerability.INSUFFICIENT
    assert text3 == HOLD_MESSAGE_JA


def test_score_and_intent():
    assert score_from_retrieval([]) == 0.0
    assert score_from_retrieval([0.9, 0.8]) > 0.5
    assert classify_intent("What is the pricing?")["type"] == "pricing"
    assert classify_intent("セキュリティは？")["type"] == "security"
    assert classify_intent("hello")["type"] == "general"
