"""Timeline / frame math (pure)."""

from __future__ import annotations

from typing import Any, Sequence


def seconds_to_frames(seconds: float, fps: int = 30) -> int:
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    if fps <= 0:
        raise ValueError("fps must be positive")
    return max(1, int(round(seconds * fps)))


def frames_to_seconds(frames: int, fps: int = 30) -> float:
    if frames < 0:
        raise ValueError("frames must be non-negative")
    if fps <= 0:
        raise ValueError("fps must be positive")
    return frames / float(fps)


def build_timeline(
    slides: Sequence[dict[str, Any]],
    durations: Sequence[dict[str, Any]],
    *,
    fps: int = 30,
) -> dict[str, Any]:
    """
    Build timeline.json mapping slides to frame ranges and audio clips.

    durations entries: {slide_index, sentence_index, duration_sec, audio_uri?}
    """
    # Aggregate duration per slide
    per_slide: dict[int, float] = {}
    audio_clips: list[dict[str, Any]] = []
    cursor_sec = 0.0

    for d in durations:
        idx = int(d.get("slide_index", 0))
        dur = float(d.get("duration_sec", 0.0))
        per_slide[idx] = per_slide.get(idx, 0.0) + dur
        start_f = seconds_to_frames(cursor_sec, fps)
        end_f = seconds_to_frames(cursor_sec + dur, fps)
        audio_clips.append(
            {
                "slide_index": idx,
                "sentence_index": d.get("sentence_index", 0),
                "start_frame": start_f,
                "end_frame": end_f,
                "duration_sec": dur,
                "audio_uri": d.get("audio_uri"),
                "text": d.get("text", ""),
            }
        )
        cursor_sec += dur

    # Ensure every slide has a minimum presence
    slide_entries: list[dict[str, Any]] = []
    frame_cursor = 0
    for i, slide in enumerate(slides):
        sec = per_slide.get(i, 1.0)
        if sec <= 0:
            sec = 1.0
        frames = seconds_to_frames(sec, fps)
        slide_entries.append(
            {
                "slide_index": i,
                "title": slide.get("title", f"Slide {i + 1}"),
                "start_frame": frame_cursor,
                "end_frame": frame_cursor + frames,
                "duration_frames": frames,
                "duration_sec": frames_to_seconds(frames, fps),
                "props": slide,
            }
        )
        frame_cursor += frames

    total_frames = frame_cursor if frame_cursor > 0 else seconds_to_frames(1.0, fps)
    return {
        "fps": fps,
        "total_frames": total_frames,
        "total_duration_sec": frames_to_seconds(total_frames, fps),
        "slides": slide_entries,
        "audio_clips": audio_clips,
        "resolution": {"width": 1920, "height": 1080},
    }


def validate_timeline(timeline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if timeline.get("fps", 0) <= 0:
        errors.append("fps must be positive")
    if timeline.get("total_frames", 0) <= 0:
        errors.append("total_frames must be positive")
    slides = timeline.get("slides") or []
    if not slides:
        errors.append("slides must not be empty")
    prev_end = 0
    for s in slides:
        if s.get("start_frame", 0) < prev_end:
            errors.append(f"overlap at slide {s.get('slide_index')}")
        prev_end = s.get("end_frame", prev_end)
    return errors
