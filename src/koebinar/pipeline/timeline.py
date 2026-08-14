"""Timeline / frame math (pure)."""

from __future__ import annotations

import math
from typing import Any, Sequence


def seconds_to_frames(seconds: float, fps: int = 30) -> int:
    if seconds < 0:
        raise ValueError("seconds must be non-negative")
    if fps <= 0:
        raise ValueError("fps must be positive")
    return max(0, int(round(seconds * fps)))


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
    # Quantize each audio duration once.  Using one frame cursor avoids the
    # old off-by-one at t=0 and keeps adjacent clips gap/overlap free.
    per_slide_frames: dict[int, int] = {}
    clip_specs: list[tuple[dict[str, Any], int, int]] = []

    for d in durations:
        idx = int(d.get("slide_index", 0))
        if idx < 0 or idx >= len(slides):
            raise ValueError(f"audio slide_index out of range: {idx}")
        dur = float(d.get("duration_sec", 0.0))
        if not math.isfinite(dur) or dur < 0:
            raise ValueError("audio duration must be finite and non-negative")
        frames = seconds_to_frames(dur, fps)
        if dur > 0 and frames == 0:
            frames = 1
        if frames == 0:
            continue
        offset = per_slide_frames.get(idx, 0)
        per_slide_frames[idx] = offset + frames
        clip_specs.append((d, idx, frames))

    # Ensure every slide has a minimum presence
    slide_entries: list[dict[str, Any]] = []
    frame_cursor = 0
    for i, slide in enumerate(slides):
        frames = per_slide_frames.get(i, seconds_to_frames(1.0, fps))
        frames = max(1, frames)
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

    slide_starts = {s["slide_index"]: s["start_frame"] for s in slide_entries}
    slide_offsets: dict[int, int] = {}
    audio_clips: list[dict[str, Any]] = []
    for d, idx, frames in clip_specs:
        start_f = slide_starts[idx] + slide_offsets.get(idx, 0)
        end_f = start_f + frames
        slide_offsets[idx] = slide_offsets.get(idx, 0) + frames
        audio_clips.append(
            {
                "slide_index": idx,
                "sentence_index": d.get("sentence_index", 0),
                "start_frame": start_f,
                "end_frame": end_f,
                "duration_frames": frames,
                "duration_sec": float(d.get("duration_sec", 0.0)),
                "audio_uri": d.get("audio_uri"),
                "audio_rel_path": d.get("audio_rel_path"),
                "audio_src": d.get("audio_src"),
                "codec": d.get("codec"),
                "content_type": d.get("content_type"),
                "text": d.get("text", ""),
            }
        )

    max_audio_end = max((clip["end_frame"] for clip in audio_clips), default=0)
    total_frames = max(frame_cursor, max_audio_end)
    total_frames = total_frames if total_frames > 0 else seconds_to_frames(1.0, fps)
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
    slide_ranges: dict[int, tuple[int, int]] = {}
    for s in slides:
        start = s.get("start_frame", 0)
        end = s.get("end_frame", prev_end)
        if start < prev_end:
            errors.append(f"overlap at slide {s.get('slide_index')}")
        prev_end = end
        slide_index = s.get("slide_index")
        if isinstance(slide_index, int) and isinstance(start, int) and isinstance(end, int):
            slide_ranges[slide_index] = (start, end)
    audio_clips = timeline.get("audio_clips") or []
    if not isinstance(audio_clips, list):
        errors.append("audio_clips must be a list")
    else:
        prev_audio_end = -1
        for index, clip in enumerate(audio_clips):
            if not isinstance(clip, dict):
                errors.append(f"audio clip {index} is not an object")
                continue
            start = clip.get("start_frame")
            end = clip.get("end_frame")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                errors.append(f"audio clip {index} has invalid frame range")
            slide_index = clip.get("slide_index")
            if not isinstance(slide_index, int) or slide_index not in slide_ranges:
                errors.append(f"audio clip {index} references missing slide {slide_index}")
            elif isinstance(start, int) and isinstance(end, int):
                slide_start, slide_end = slide_ranges[slide_index]
                if start < slide_start or end > slide_end:
                    errors.append(f"audio clip {index} is outside slide {slide_index}")
            if start is not None and start < prev_audio_end:
                errors.append(f"audio clip {index} overlaps a previous clip")
            if isinstance(end, int):
                prev_audio_end = end
            if not clip.get("audio_uri"):
                errors.append(f"audio clip {index} is missing audio_uri")
    return errors
