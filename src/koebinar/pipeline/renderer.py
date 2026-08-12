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
from pathlib import Path
from typing import Any, Callable, Optional

from koebinar.config import Settings, get_settings
from koebinar.pipeline.timeline import validate_timeline
from koebinar.storage import Store, get_store

# Injectable subprocess runner for unit tests
SubprocessRunner = Callable[..., subprocess.CompletedProcess]


class RenderError(Exception):
    pass


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
    timeout_sec: float = 180.0,
    runner: Optional[SubprocessRunner] = None,
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
    props_path = output_path.with_suffix(".props.json")
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    cmd = [
        "node",
        str(render_js),
        "--props",
        str(props_path),
        "--output",
        str(output_path),
    ]
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
        raise RenderError(f"remotion render timed out after {timeout_sec}s") from exc
    except FileNotFoundError as exc:
        raise RenderError("node not found for remotion render") from exc
    except Exception as exc:
        raise RenderError(f"remotion invoke failed: {exc}") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "")[-2000:]
        stdout = (proc.stdout or "")[-1000:]
        raise RenderError(f"remotion exit {proc.returncode}: {stderr or stdout}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RenderError("remotion completed but output file missing/empty")
    return {
        "renderer": "remotion",
        "bytes": output_path.stat().st_size,
        "stdout_tail": (proc.stdout or "")[-500:],
        "ai_generated_narration": True,
    }


class VideoRenderer:
    def __init__(
        self,
        store: Optional[Store] = None,
        settings: Optional[Settings] = None,
        *,
        runner: Optional[SubprocessRunner] = None,
    ) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        self.runner = runner
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
        if prefer_remotion:
            try:
                return self._render_remotion(webinar_id, timeline, slides)
            except RenderError as exc:
                self.last_error = str(exc)
                # fall through to double

        return self._render_double(webinar_id, timeline, slides, reason=self.last_error or "remotion_unavailable")

    def _render_remotion(
        self,
        webinar_id: str,
        timeline: dict[str, Any],
        slides: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        out = self.store.artifact_path(webinar_id, "webinar.mp4")
        props = {
            "timeline": timeline,
            "slides": slides,
            "fps": timeline.get("fps") or self.settings.fps,
            "width": 1920,
            "height": 1080,
        }
        meta = invoke_remotion_render(
            project_dir=Path(self.settings.remotion_project_dir),
            props=props,
            output_path=out,
            timeout_sec=self.settings.remotion_timeout_sec,
            runner=self.runner,
        )
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
        uri = self.store.write_bytes(webinar_id, "webinar.mp4", data)
        self.used_double = True
        return uri, {
            "renderer": "double",
            "reason": reason,
            "bytes": len(data),
            "ai_generated_narration": True,
        }
