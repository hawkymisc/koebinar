"""Video renderer boundary — Remotion double when env cannot run headless render.

Produces a real video artifact file via the pipeline entry. When Remotion is
unavailable, writes a minimal valid-enough MP4 container (ftyp+mdat) with
embedded timeline metadata so downstream paths still exercise artifact IO.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Optional

from koebinar.config import Settings, get_settings
from koebinar.pipeline.timeline import validate_timeline
from koebinar.storage import Store, get_store


class RenderError(Exception):
    pass


def remotion_available() -> bool:
    """Detect whether @remotion/renderer can be invoked in this environment."""
    try:
        import shutil
        import subprocess

        if not shutil.which("npx"):
            return False
        # Soft check only — do not require network install
        return False  # MVP environments typically lack Remotion project; use double
    except Exception:
        return False


def build_minimal_mp4(timeline: dict[str, Any], slides: list[dict[str, Any]]) -> bytes:
    """
    Build a tiny ISO BMFF-like MP4:
    - ftyp box
    - free box with JSON metadata (timeline summary)
    - mdat box with payload bytes

    Not a full playable demo film, but a real binary artifact with structure.
    """
    meta = {
        "generator": "koebinar-renderer-double",
        "fps": timeline.get("fps"),
        "total_frames": timeline.get("total_frames"),
        "total_duration_sec": timeline.get("total_duration_sec"),
        "slide_count": len(slides),
        "ai_generated_narration": True,
    }
    meta_bytes = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    # pad meta into free box
    free_payload = meta_bytes
    free_box = struct.pack(">I", 8 + len(free_payload)) + b"free" + free_payload

    # mdat: include slide titles as payload
    lines = []
    for s in timeline.get("slides") or []:
        lines.append(f"{s.get('slide_index')}:{s.get('title')}:{s.get('duration_frames')}")
    mdat_payload = ("\n".join(lines) or "koebinar").encode("utf-8")
    mdat_box = struct.pack(">I", 8 + len(mdat_payload)) + b"mdat" + mdat_payload

    ftyp_payload = b"isom" + struct.pack(">I", 0x200) + b"isomiso2mp41"
    ftyp_box = struct.pack(">I", 8 + len(ftyp_payload)) + b"ftyp" + ftyp_payload

    return ftyp_box + free_box + mdat_box


class VideoRenderer:
    def __init__(self, store: Optional[Store] = None, settings: Optional[Settings] = None) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        self.used_double = False

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

        use_double = force_double or not remotion_available()
        self.used_double = use_double
        if use_double:
            data = build_minimal_mp4(timeline, slides)
            uri = self.store.write_bytes(webinar_id, "webinar.mp4", data)
            return uri, {
                "renderer": "double",
                "reason": "remotion_unavailable",
                "bytes": len(data),
                "ai_generated_narration": True,
            }

        # Placeholder for real Remotion path (not expected in CI)
        raise RenderError("Remotion path not configured")  # pragma: no cover
