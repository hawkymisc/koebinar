"""Video renderer — Remotion worker invoke with honest double fallback.

The pipeline video step always goes through VideoRenderer.render(). When
Remotion is configured and available, it shells out to the local remotion
project. Otherwise (or on invoke failure) it writes a minimal MP4 via the
same entry so artifacts remain durable.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlparse

from koebinar.config import Settings, get_settings
from koebinar.pipeline.audio_format import AudioFormatError, load_audio_format
from koebinar.pipeline.media import probe_media
from koebinar.pipeline.timeline import validate_timeline
from koebinar.storage import Store, get_store

# Injectable subprocess runner for unit tests
SubprocessRunner = Callable[..., subprocess.CompletedProcess]
MediaProbe = Callable[..., dict[str, Any]]


class RenderError(Exception):
    pass


def _audio_source_path(uri: str) -> Path:
    raw = str(uri)
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        return Path(unquote(parsed.path))
    return Path(raw)


def _stage_audio_assets(
    timeline: dict[str, Any],
    *,
    artifacts_root: Path,
    public_dir: Path,
) -> dict[str, Any]:
    """Copy validated local audio into a private public directory for Remotion.

    Chromium cannot dereference arbitrary server-side paths.  Only files below
    the artifact root are accepted, and Remotion receives generated relative
    URLs (``audio/clip-N.<actual-extension>``), never user-controlled paths.
    """
    clips = timeline.get("audio_clips") or []
    if not isinstance(clips, list):
        raise RenderError("timeline audio_clips must be a list")
    if not clips:
        return deepcopy(timeline)

    root = artifacts_root.resolve()
    audio_dir = public_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    staged_timeline = deepcopy(timeline)
    staged_clips = staged_timeline["audio_clips"]
    for index, clip in enumerate(staged_clips):
        if not isinstance(clip, dict):
            raise RenderError(f"audio clip {index} is not an object")
        uri = clip.get("audio_uri")
        if not uri:
            raise RenderError(f"audio clip {index} is missing audio_uri")
        source = _audio_source_path(str(uri))
        try:
            resolved = source.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise RenderError(f"audio clip {index} is outside artifact root: {uri}") from exc
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            raise RenderError(f"audio clip {index} is missing or empty: {uri}")
        try:
            audio_format = load_audio_format(resolved)
        except AudioFormatError as exc:
            raise RenderError(f"audio clip {index} is invalid: {exc}") from exc

        filename = f"clip-{index}{audio_format.extension}"
        destination = audio_dir / filename
        shutil.copyfile(resolved, destination)
        if destination.stat().st_size <= 0:
            raise RenderError(f"audio clip {index} staging produced an empty file")
        src = f"audio/{filename}"
        clip["src"] = src
        clip["audio_src"] = src
        clip["codec"] = audio_format.codec
        clip["content_type"] = audio_format.content_type
        clip["extension"] = audio_format.extension
        clip["sample_rate"] = audio_format.sample_rate
        clip["channels"] = audio_format.channels
        clip["duration_sec"] = audio_format.duration_sec
        start = clip.get("start_frame")
        end = clip.get("end_frame")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise RenderError(f"audio clip {index} has invalid frame range")
        clip["duration_frames"] = end - start
    return staged_timeline


def _expected_duration_sec(timeline: dict[str, Any]) -> float | None:
    value = timeline.get("total_duration_sec")
    try:
        if value is not None:
            result = float(value)
            if result >= 0:
                return result
    except (TypeError, ValueError):
        pass
    try:
        fps = float(timeline.get("fps"))
        frames = float(timeline.get("total_frames"))
        return frames / fps if fps > 0 and frames >= 0 else None
    except (TypeError, ValueError):
        return None


def _expected_audio_duration_sec(timeline: dict[str, Any]) -> float | None:
    if not timeline.get("audio_clips"):
        return None
    # Remotion renders one composition-wide audio stream. When the final clip
    # ends before the video, the muxed AAC track is padded with trailing silence
    # to the composition boundary (plus normal codec padding). Comparing it to
    # the final clip boundary therefore rejects otherwise valid media.
    return _expected_duration_sec(timeline)


def _probe_errors(
    probe_result: dict[str, Any],
    *,
    timeline: dict[str, Any],
    tolerance_sec: float,
    require_audio: bool,
) -> list[str]:
    errors = list(probe_result.get("errors") or [])
    if probe_result.get("ok") is not True and not errors:
        errors.append("probe_not_ok")
    expected = _expected_duration_sec(timeline)
    actual = probe_result.get("duration_sec")
    if actual is None:
        actual = probe_result.get("video_duration_sec")
    if expected is not None:
        try:
            actual_value = float(actual)
        except (TypeError, ValueError):
            actual_value = None
        if actual_value is None:
            errors.append("media_duration_missing")
        elif abs(actual_value - expected) > max(0.0, tolerance_sec):
            errors.append(
                f"media_duration_out_of_range:{actual_value:.3f}!={expected:.3f}"
            )
    if require_audio:
        audio_duration = probe_result.get("audio_duration_sec")
        expected_audio = _expected_audio_duration_sec(timeline)
        if audio_duration is None:
            errors.append("audio_duration_missing")
        elif expected_audio is not None:
            try:
                audio_value = float(audio_duration)
            except (TypeError, ValueError):
                audio_value = None
            if audio_value is None or abs(audio_value - expected_audio) > max(0.0, tolerance_sec):
                errors.append("audio_duration_out_of_range")
    return errors


def remotion_project_ready(project_dir: Path) -> bool:
    """True when remotion project files + node_modules look installable/runnable."""
    if not project_dir.is_dir():
        return False
    pkg = project_dir / "package.json"
    entry = project_dir / "src" / "Root.tsx"
    render_js = project_dir / "render.mjs"
    if not (pkg.exists() and entry.exists() and render_js.exists()):
        return False
    # node_modules optional for "ready" structure; invoke will fail without install
    return True


def remotion_available(settings: Optional[Settings] = None) -> bool:
    """Detect whether Remotion can be invoked in this environment."""
    try:
        settings = settings or get_settings()
        if settings.force_render_double:
            return False
        if not shutil.which("node"):
            return False
        project = Path(settings.remotion_project_dir)
        if not remotion_project_ready(project):
            return False
        # Prefer installed @remotion/renderer
        renderer_pkg = project / "node_modules" / "@remotion" / "renderer"
        if not renderer_pkg.exists():
            return False
        return True
    except Exception:
        return False


def build_minimal_mp4(timeline: dict[str, Any], slides: list[dict[str, Any]]) -> bytes:
    """Build a tiny ISO BMFF-like MP4 (ftyp + free meta + mdat)."""
    meta = {
        "generator": "koebinar-renderer-double",
        "fps": timeline.get("fps"),
        "total_frames": timeline.get("total_frames"),
        "total_duration_sec": timeline.get("total_duration_sec"),
        "slide_count": len(slides),
        "ai_generated_narration": True,
    }
    meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    free_box = struct.pack(">I", 8 + len(meta_bytes)) + b"free" + meta_bytes
    lines = []
    for s in timeline.get("slides") or []:
        lines.append(f"{s.get('slide_index')}:{s.get('title')}:{s.get('duration_frames')}")
    mdat_payload = ("\n".join(lines) or "koebinar").encode("utf-8")
    mdat_box = struct.pack(">I", 8 + len(mdat_payload)) + b"mdat" + mdat_payload
    ftyp_payload = b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41"
    ftyp_box = struct.pack(">I", 8 + len(ftyp_payload)) + b"ftyp" + ftyp_payload
    return ftyp_box + free_box + mdat_box


def invoke_remotion_render(
    *,
    project_dir: Path,
    props: dict[str, Any],
    output_path: Path,
    timeout_sec: float = 900.0,
    runner: Optional[SubprocessRunner] = None,
    public_dir: Optional[Path] = None,
    probe: Optional[MediaProbe] = None,
    timeline: Optional[dict[str, Any]] = None,
    audio_duration_tolerance_sec: float = 0.5,
) -> dict[str, Any]:
    """
    Invoke local remotion/render.mjs.

    Returns metadata dict on success. Raises RenderError on failure.
    """
    runner = runner or subprocess.run
    render_js = project_dir / "render.mjs"
    if not render_js.exists():
        raise RenderError(f"missing render entry: {render_js}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".mp4",
        dir=str(output_path.parent),
    )
    os.close(fd)
    temp_output = Path(temp_name)
    props_path = temp_output.with_suffix(".props.json")
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    render_timeline = timeline or props.get("timeline") or {}
    require_audio = bool(render_timeline.get("audio_clips"))
    probe = probe or probe_media
    cmd = [
        "node",
        str(render_js),
        "--props",
        str(props_path),
        "--output",
        str(temp_output),
    ]
    if public_dir is not None:
        cmd.extend(["--public-dir", str(public_dir)])
    try:
        try:
            proc = runner(
                cmd,
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env={**os.environ, "NODE_ENV": "production"},
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or exc.output or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            render_state: dict[str, Any] = {}
            for line in str(stdout).splitlines():
                try:
                    event = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(event, dict) and event.get("phase"):
                    render_state = event
            phase = str(render_state.get("phase") or "unknown")
            progress = render_state.get("progress_percent")
            progress_suffix = f", progress={progress}%" if isinstance(progress, int) else ""
            raise RenderError(
                f"remotion render timed out after {timeout_sec}s "
                f"(phase={phase}{progress_suffix})"
            ) from exc
        except FileNotFoundError as exc:
            raise RenderError("node not found for remotion render") from exc
        except Exception as exc:
            raise RenderError(f"remotion invoke failed: {exc}") from exc

        if proc.returncode != 0:
            stderr = (proc.stderr or "")[-2000:]
            stdout = (proc.stdout or "")[-1000:]
            raise RenderError(f"remotion exit {proc.returncode}: {stderr or stdout}")
        if not temp_output.exists() or temp_output.stat().st_size == 0:
            raise RenderError("remotion completed but output file missing/empty")
        probe_result = probe(temp_output, require_audio=require_audio)
        errors = _probe_errors(
            probe_result,
            timeline=render_timeline,
            tolerance_sec=audio_duration_tolerance_sec,
            require_audio=require_audio,
        )
        if errors:
            raise RenderError(f"media probe failed: {', '.join(errors)}")
        os.replace(temp_output, output_path)
        return {
            "renderer": "remotion",
            "test_only": False,
            "publishable": True,
            "bytes": output_path.stat().st_size,
            "stdout_tail": (proc.stdout or "")[-500:],
            "ai_generated_narration": True,
            "audio_required": require_audio,
            "probe": {**probe_result, "path": str(output_path)},
        }
    finally:
        temp_output.unlink(missing_ok=True)
        props_path.unlink(missing_ok=True)


class VideoRenderer:
    def __init__(
        self,
        store: Optional[Store] = None,
        settings: Optional[Settings] = None,
        *,
        runner: Optional[SubprocessRunner] = None,
        probe: Optional[MediaProbe] = None,
    ) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        self.runner = runner
        self.probe = probe
        self.used_double = False
        self.last_error: Optional[str] = None

    def render(
        self,
        webinar_id: str,
        timeline: dict[str, Any],
        slides: list[dict[str, Any]],
        *,
        force_double: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        errors = validate_timeline(timeline)
        if errors:
            raise RenderError("; ".join(errors))

        prefer_remotion = (
            not force_double
            and not self.settings.force_render_double
            and remotion_available(self.settings)
        )
        if not prefer_remotion:
            self.last_error = "remotion unavailable; production rendering is fail-closed"
            if force_double or self.settings.force_render_double:
                return self._render_double(webinar_id, timeline, slides, reason="explicit_test_double")
            raise RenderError(self.last_error)
        try:
            return self._render_remotion(webinar_id, timeline, slides)
        except RenderError as exc:
            self.last_error = str(exc)
            raise

    def _render_remotion(
        self,
        webinar_id: str,
        timeline: dict[str, Any],
        slides: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        out = self.store.artifact_path(webinar_id, "webinar.mp4")
        stage = None
        try:
            render_timeline = timeline
            public_dir = None
            if timeline.get("audio_clips"):
                stage = tempfile.TemporaryDirectory(
                    prefix=".koebinar-remotion-assets-",
                    dir=str(Path(self.settings.artifacts_dir).resolve()),
                )
                public_dir = Path(stage.name)
                render_timeline = _stage_audio_assets(
                    timeline,
                    artifacts_root=Path(self.settings.artifacts_dir),
                    public_dir=public_dir,
                )
            props = {
                "timeline": render_timeline,
                "slides": slides,
                "fps": render_timeline.get("fps") or self.settings.fps,
                "width": (render_timeline.get("resolution") or {}).get("width", 1920),
                "height": (render_timeline.get("resolution") or {}).get("height", 1080),
            }
            meta = invoke_remotion_render(
                project_dir=Path(self.settings.remotion_project_dir),
                props=props,
                output_path=out,
                timeout_sec=self.settings.remotion_timeout_sec,
                runner=self.runner,
                public_dir=public_dir,
                timeline=render_timeline,
                audio_duration_tolerance_sec=self.settings.audio_duration_tolerance_sec,
                probe=getattr(self, "probe", None),
            )
        finally:
            if stage is not None:
                stage.cleanup()
        self.used_double = False
        return str(out), meta

    def _render_double(
        self,
        webinar_id: str,
        timeline: dict[str, Any],
        slides: list[dict[str, Any]],
        *,
        reason: str,
    ) -> tuple[str, dict[str, Any]]:
        data = build_minimal_mp4(timeline, slides)
        uri = self.store.write_bytes_atomic(webinar_id, "webinar.mp4", data)
        probe_result = (self.probe or probe_media)(
            Path(uri), require_audio=bool(timeline.get("audio_clips"))
        )
        self.used_double = True
        return uri, {
            "renderer": "double",
            "test_only": True,
            "publishable": False,
            "reason": reason,
            "bytes": len(data),
            "ai_generated_narration": True,
            "audio_required": bool(timeline.get("audio_clips")),
            "probe": probe_result,
        }
