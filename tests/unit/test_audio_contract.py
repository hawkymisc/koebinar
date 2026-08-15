"""Regression tests for the A-001 audio handoff contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from koebinar.integrations.elevenlabs import ElevenLabsError
from koebinar.pipeline.audio_format import AudioFormatError, detect_audio_format, silence_wav
from koebinar.pipeline.renderer import VideoRenderer, _probe_errors
from koebinar.pipeline.tts import TTSAdapter
from tests.helpers import seed_attested_voice_ref


def test_audio_format_is_derived_from_bytes_and_invalid_payloads_are_rejected():
    fmt = detect_audio_format(silence_wav(0.5))

    assert fmt.codec == "pcm_wav"
    assert fmt.extension == ".wav"
    assert fmt.content_type == "audio/wav"
    assert fmt.duration_sec == pytest.approx(0.5, abs=0.01)

    for payload in (b"", b"NOT_AUDIO"):
        with pytest.raises(AudioFormatError):
            detect_audio_format(payload)


def test_tts_does_not_persist_an_empty_provider_payload(settings, store):
    settings.allow_system_tts_key = True
    settings.elevenlabs_api_key = "system-test-key"

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"", headers={"content-type": "audio/mpeg"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    tts = TTSAdapter(store=store, settings=settings, http_client=client)
    seed_attested_voice_ref(store, "voice-invalid-audio")

    with pytest.raises(ElevenLabsError, match="empty audio payload"):
        tts.synthesize_script(
            "web-invalid-audio",
            {"slides": [{"slide_index": 0, "sentences": ["hello"]}]},
            "voice-invalid-audio",
            "en",
        )

    assert not list((settings.artifacts_dir / "web-invalid-audio").glob("audio/*"))
    client.close()


def test_renderer_stages_audio_for_remotion_and_probes_audio_track(settings, store, monkeypatch):
    settings.force_render_double = False
    audio_path = store.artifact_path("web-audio", "audio/source.wav")
    audio_path.write_bytes(silence_wav(1.0))
    timeline = {
        "fps": 30,
        "total_frames": 30,
        "total_duration_sec": 1.0,
        "slides": [{"slide_index": 0, "start_frame": 0, "end_frame": 30, "duration_frames": 30}],
        "audio_clips": [
            {
                "slide_index": 0,
                "sentence_index": 0,
                "start_frame": 0,
                "end_frame": 30,
                "audio_uri": str(audio_path),
            }
        ],
    }
    captured: dict[str, object] = {}

    def fake_probe(path: Path, *, require_audio: bool = False) -> dict:
        assert require_audio is True
        return {
            "ok": True,
            "path": str(path),
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration_sec": 1.0,
            "video_duration_sec": 1.0,
            "audio_duration_sec": 1.0,
            "video_streams": 1,
            "audio_streams": 1,
            "errors": [],
        }

    def fake_runner(cmd, **kwargs):
        props_path = Path(cmd[cmd.index("--props") + 1])
        public_dir = Path(cmd[cmd.index("--public-dir") + 1])
        props = json.loads(props_path.read_text(encoding="utf-8"))
        staged = public_dir / "audio" / "clip-0.wav"
        assert staged.is_file() and staged.stat().st_size > 0
        captured["props"] = props
        output = Path(cmd[cmd.index("--output") + 1])
        output.write_bytes(b"fake-remotion-output")
        return subprocess.CompletedProcess(cmd, 0, stdout="done", stderr="")

    monkeypatch.setattr("koebinar.pipeline.renderer.remotion_available", lambda _settings=None: True)
    renderer = VideoRenderer(store=store, settings=settings, runner=fake_runner, probe=fake_probe)

    uri, meta = renderer.render("web-audio", timeline, [{"title": "Audio"}])

    staged_timeline = captured["props"]["timeline"]
    assert staged_timeline["audio_clips"][0]["src"] == "audio/clip-0.wav"
    assert timeline["audio_clips"][0]["audio_uri"] == str(audio_path)
    assert meta["renderer"] == "remotion"
    assert meta["publishable"] is True
    assert Path(uri).is_file()


def test_probe_accepts_audio_stream_padded_to_the_full_composition():
    """Remotion muxes trailing silence into AAC until the video ends."""
    timeline = {
        "fps": 30,
        "total_frames": 60,
        "total_duration_sec": 2.0,
        "slides": [
            {"slide_index": 0, "start_frame": 0, "end_frame": 30},
            {"slide_index": 1, "start_frame": 30, "end_frame": 60},
        ],
        "audio_clips": [
            {
                "slide_index": 0,
                "start_frame": 0,
                "end_frame": 30,
                "audio_uri": "/audio.wav",
            }
        ],
    }
    probe = {
        "ok": True,
        "duration_sec": 2.048,
        "video_duration_sec": 2.0,
        "audio_duration_sec": 2.048,
        "video_streams": 1,
        "audio_streams": 1,
        "errors": [],
    }

    assert _probe_errors(
        probe,
        timeline=timeline,
        tolerance_sec=0.5,
        require_audio=True,
    ) == []
