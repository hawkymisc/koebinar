"""ffprobe-backed validation for rendered media artifacts."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

SubprocessRunner = Callable[..., subprocess.CompletedProcess]


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _stream_summary(stream: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "index",
        "codec_type",
        "codec_name",
        "profile",
        "width",
        "height",
        "sample_rate",
        "channels",
        "duration",
    )
    return {field: stream[field] for field in fields if field in stream}


def probe_media(
    path: Path | str,
    *,
    require_audio: bool = False,
    runner: Optional[SubprocessRunner] = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    """Probe an MP4 and return a JSON-safe structural validation result."""
    target = Path(path)
    result: dict[str, Any] = {
        "ok": False,
        "path": str(target),
        "size_bytes": target.stat().st_size if target.exists() else 0,
        "format_name": None,
        "duration_sec": None,
        "video_streams": 0,
        "audio_streams": 0,
        "video": None,
        "audio": None,
        "errors": [],
    }
    errors: list[str] = result["errors"]
    if not target.exists():
        errors.append("file_missing")
        return result
    if result["size_bytes"] <= 0:
        errors.append("file_empty")
        return result

    runner = runner or subprocess.run
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(target),
    ]
    try:
        proc = runner(cmd, capture_output=True, text=True, timeout=timeout_sec, check=False)
    except FileNotFoundError:
        errors.append("ffprobe_unavailable")
        return result
    except subprocess.TimeoutExpired:
        errors.append("ffprobe_timeout")
        return result
    except Exception as exc:
        errors.append(f"ffprobe_error:{exc}")
        return result

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
        errors.append("ffprobe_invalid_json")

    streams = payload.get("streams") or []
    format_data = payload.get("format") or {}
    format_name = format_data.get("format_name")
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    container_duration = _float_or_none(format_data.get("duration"))
    result.update(
        {
            "format_name": format_name,
            "duration_sec": container_duration,
            "video_streams": len(video),
            "audio_streams": len(audio),
            "video": _stream_summary(video[0]) if video else None,
            "audio": _stream_summary(audio[0]) if audio else None,
            "video_duration_sec": _float_or_none(video[0].get("duration")) if video else None,
            "audio_duration_sec": _float_or_none(audio[0].get("duration")) if audio else None,
        }
    )
    if result["audio_duration_sec"] is None and audio:
        result["audio_duration_sec"] = container_duration
    if proc.returncode != 0:
        errors.append(f"ffprobe_exit:{proc.returncode}")
    valid_containers = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}
    if not format_name or not valid_containers.intersection(set(str(format_name).split(","))):
        errors.append("not_mp4_container")
    if not video:
        errors.append("video_stream_missing")
    if require_audio and not audio:
        errors.append("audio_stream_missing")
    result["ok"] = not errors
    return result
