"""Validated audio artifact format contract.

TTS providers may return a different container than the requested format and
some successful HTTP responses contain an empty/error payload.  This module
keeps those bytes out of the artifact store and derives the persisted suffix,
MIME type and duration from the actual payload.
"""

from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional


class AudioFormatError(Exception):
    """Audio payload is empty, unsupported, truncated or undecodable."""


@dataclass(frozen=True)
class AudioFormat:
    codec: str
    content_type: str
    extension: str
    duration_sec: float
    sample_rate: int
    channels: int

    def as_dict(self) -> dict[str, object]:
        return {
            "codec": self.codec,
            "content_type": self.content_type,
            "extension": self.extension,
            "duration_sec": self.duration_sec,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }


SUPPORTED_CODECS: dict[str, tuple[str, str]] = {
    "pcm_wav": ("audio/wav", ".wav"),
    "mp3": ("audio/mpeg", ".mp3"),
}

# Headerless PCM/μ-law formats do not carry enough information to be safely
# handed to Chromium.  Request a self-describing format by default.
ELEVENLABS_OUTPUT_FORMATS: dict[str, str] = {
    "mp3_22050_32": "mp3",
    "mp3_44100_32": "mp3",
    "mp3_44100_64": "mp3",
    "mp3_44100_96": "mp3",
    "mp3_44100_128": "mp3",
    "mp3_44100_192": "mp3",
}


def extension_for(codec: str) -> str:
    try:
        return SUPPORTED_CODECS[codec][1]
    except KeyError as exc:
        raise AudioFormatError(f"unsupported audio codec: {codec}") from exc


def content_type_for(codec: str) -> str:
    try:
        return SUPPORTED_CODECS[codec][0]
    except KeyError as exc:
        raise AudioFormatError(f"unsupported audio codec: {codec}") from exc


def _wav_format(data: bytes) -> AudioFormat:
    try:
        with wave.open(BytesIO(data), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.getnframes()
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            compression = wf.getcomptype()
    except Exception as exc:
        raise AudioFormatError(f"undecodable WAV payload: {exc}") from exc
    if compression != "NONE":
        raise AudioFormatError(f"unsupported WAV compression: {compression}")
    if rate <= 0 or frames <= 0 or channels <= 0 or sample_width <= 0:
        raise AudioFormatError("WAV payload has no usable audio frames")
    duration = frames / float(rate)
    if not math.isfinite(duration) or duration <= 0:
        raise AudioFormatError("WAV payload has invalid duration")
    content_type, extension = SUPPORTED_CODECS["pcm_wav"]
    return AudioFormat("pcm_wav", content_type, extension, duration, rate, channels)


# MPEG version id: 3=MPEG1, 2=MPEG2, 0=MPEG2.5.  Layer III only.
_MP3_BITRATES: dict[int, list[int]] = {
    0: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    1: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_MP3_SAMPLE_RATES: dict[int, list[int]] = {
    3: [44100, 48000, 32000, 0],
    2: [22050, 24000, 16000, 0],
    0: [11025, 12000, 8000, 0],
}
_MP3_SAMPLES_PER_FRAME = {3: 1152, 2: 576, 0: 576}


def _id3_size(data: bytes) -> int:
    if len(data) < 10 or data[:3] != b"ID3":
        return 0
    size_bytes = data[6:10]
    if any(byte & 0x80 for byte in size_bytes):
        raise AudioFormatError("invalid ID3v2 size")
    size = 0
    for byte in size_bytes:
        size = (size << 7) | byte
    end = 10 + size
    if end > len(data):
        raise AudioFormatError("truncated ID3v2 tag")
    return end


def _mp3_format(data: bytes) -> AudioFormat:
    offset = _id3_size(data)
    total_samples = 0
    sample_rate = 0
    channels = 0
    frame_count = 0

    while offset + 4 <= len(data):
        header = data[offset : offset + 4]
        if header[0] != 0xFF or (header[1] & 0xE0) != 0xE0:
            if frame_count:
                # ID3v1/LAME tags and padding may follow the valid stream.
                break
            offset += 1
            continue

        version_id = (header[1] >> 3) & 0x03
        layer = (header[1] >> 1) & 0x03
        bitrate_index = (header[2] >> 4) & 0x0F
        rate_index = (header[2] >> 2) & 0x03
        padding = (header[2] >> 1) & 0x01
        channel_mode = (header[3] >> 6) & 0x03
        if version_id == 1 or layer != 1:
            raise AudioFormatError("unsupported MPEG audio layer/version")
        rates = _MP3_SAMPLE_RATES.get(version_id)
        if rates is None:
            raise AudioFormatError("unsupported MPEG audio version")
        rate = rates[rate_index]
        bitrate = _MP3_BITRATES[0 if version_id == 3 else 1][bitrate_index]
        if rate <= 0 or bitrate <= 0:
            raise AudioFormatError("invalid MP3 frame header")
        samples = _MP3_SAMPLES_PER_FRAME[version_id]
        frame_length = int((samples // 8) * bitrate * 1000 / rate) + padding
        if frame_length <= 4 or offset + frame_length > len(data):
            raise AudioFormatError("truncated MP3 frame")
        if sample_rate and sample_rate != rate:
            raise AudioFormatError("MP3 sample rate changes within stream")
        sample_rate = rate
        channels = 1 if channel_mode == 3 else 2
        total_samples += samples
        frame_count += 1
        offset += frame_length

    if frame_count == 0 or sample_rate <= 0:
        raise AudioFormatError("undecodable MP3 payload: no audio frames found")
    duration = total_samples / float(sample_rate)
    if not math.isfinite(duration) or duration <= 0:
        raise AudioFormatError("MP3 payload has invalid duration")
    content_type, extension = SUPPORTED_CODECS["mp3"]
    return AudioFormat("mp3", content_type, extension, duration, sample_rate, channels)


def _looks_like_mp3(data: bytes) -> bool:
    return data[:3] == b"ID3" or (
        len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
    )


def detect_audio_format(data: bytes, *, declared_content_type: Optional[str] = None) -> AudioFormat:
    """Resolve the real codec and duration from audio bytes."""
    if not data:
        raise AudioFormatError("empty audio payload")
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WAVE":
        return _wav_format(data)
    if _looks_like_mp3(data):
        return _mp3_format(data)
    declared = f" (declared content-type: {declared_content_type})" if declared_content_type else ""
    raise AudioFormatError(f"unsupported audio payload{declared}: leading bytes {data[:8].hex()}")


def load_audio_format(path: Path | str) -> AudioFormat:
    """Validate and re-derive the format of a persisted artifact."""
    target = Path(path)
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise AudioFormatError(f"audio artifact unreadable: {target} ({exc})") from exc
    return detect_audio_format(data)


def silence_wav(duration_sec: float, sample_rate: int = 22050) -> bytes:
    """Create a valid WAV fixture; never used as a provider fallback."""
    n_frames = max(1, int(duration_sec * sample_rate))
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def tone_wav(
    duration_sec: float,
    *,
    freq: float = 440.0,
    sample_rate: int = 22050,
    amplitude: float = 0.4,
) -> bytes:
    """Create an audible WAV fixture for media-track integration tests."""
    n_frames = max(1, int(duration_sec * sample_rate))
    peak = int(max(0.0, min(1.0, amplitude)) * 32767)
    payload = bytearray()
    for index in range(n_frames):
        value = int(peak * math.sin(2.0 * math.pi * freq * index / sample_rate))
        payload += struct.pack("<h", value)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(payload))
    return buf.getvalue()
