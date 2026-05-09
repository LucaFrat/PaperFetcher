"""ElevenLabs TTS (4-thread parallel) + ffmpeg concat into a single mp3."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError

logger = logging.getLogger(__name__)


def _system_ffmpeg() -> str:
    # Prefer apt-installed ffmpeg over conda's (miniforge3/bin/ffmpeg
    # links to libx264.so.138 which isn't on Ubuntu 24.04).
    for path in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(path).is_file() and os.access(path, os.X_OK):
            return path
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found")
    logger.warning("system ffmpeg missing; falling back to %s", found)
    return found


def _synth_one(client: ElevenLabs, text: str, voice_id: str, model: str,
               output_format: str, out_path: Path,
               prev_text: str | None, next_text: str | None) -> None:
    delay = 1.0
    for attempt in range(3):
        try:
            audio_iter = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=model,
                output_format=output_format,
                previous_text=prev_text,
                next_text=next_text,
            )
            with open(out_path, "wb") as f:
                for chunk in audio_iter:
                    f.write(chunk)
            return
        except ApiError as e:
            if attempt == 2:
                raise
            logger.warning("elevenlabs line failed (attempt %d): %s — retry in %.0fs",
                           attempt + 1, e, delay)
            time.sleep(delay)
            delay *= 2


def _synth_all(client: ElevenLabs, lines: list[dict], voice_a: str, voice_b: str,
               model: str, output_format: str, work: Path) -> list[Path]:
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path | None] = [None] * len(lines)
    total_chars = sum(len(ln["text"]) for ln in lines)
    logger.info("elevenlabs synth: %d lines, %d input chars (model=%s)",
                len(lines), total_chars, model)

    def task(i: int) -> tuple[int, Path]:
        ln = lines[i]
        voice = voice_a if ln["speaker"] == "A" else voice_b
        out = work / f"{i:04d}_{ln['speaker']}.mp3"
        prev_text = lines[i - 1]["text"] if i > 0 else None
        next_text = lines[i + 1]["text"] if i + 1 < len(lines) else None
        _synth_one(client, ln["text"], voice, model, output_format, out,
                   prev_text, next_text)
        return i, out

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(task, i) for i in range(len(lines))]
        for fut in as_completed(futures):
            i, path = fut.result()
            parts[i] = path

    return [p for p in parts if p is not None]


def _ffmpeg_concat(parts: list[Path], out_path: Path) -> None:
    ffmpeg = _system_ffmpeg()
    list_path = out_path.parent / "_concat.txt"
    list_path.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in parts),
        encoding="utf-8",
    )
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(out_path),
    ]
    logger.info("ffmpeg concat (%s) -> %s (%d parts)", ffmpeg, out_path, len(parts))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    list_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[:500]}")


def synthesize(script_path: Path, dest_dir: Path, *, audio_cfg) -> Path:
    """audio_cfg: a paperfatcher.config.AudioCfg instance."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set — export it in your shell or "
            "~/.config/environment.d/ for systemd"
        )
    client = ElevenLabs(api_key=api_key)

    dest_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads(script_path.read_text(encoding="utf-8"))
    lines = data["dialogue"]

    out_mp3 = dest_dir / "digest.mp3"
    with tempfile.TemporaryDirectory(prefix="pf-tts-", dir=str(dest_dir)) as td:
        parts = _synth_all(
            client, lines, audio_cfg.voice_a, audio_cfg.voice_b,
            audio_cfg.elevenlabs_model, audio_cfg.elevenlabs_output_format,
            Path(td),
        )
        _ffmpeg_concat(parts, out_mp3)

    logger.info("audio done: %s (%d bytes)", out_mp3, out_mp3.stat().st_size)
    return out_mp3
