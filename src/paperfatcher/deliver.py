"""rclone push to Google Drive, with a local-copy fallback on failure."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def deliver(source_dir: Path, *, rclone_remote: str,
            local_fallback: str) -> tuple[str, bool]:
    """Push source_dir to rclone_remote. Returns (final_location, used_remote).
    Falls back to a local copy if rclone is unavailable or fails."""
    if shutil.which("rclone"):
        target = f"{rclone_remote}/{source_dir.name}"
        cmd = ["rclone", "copy", str(source_dir), target,
               "--transfers", "4", "--checkers", "4"]
        logger.info("rclone copy -> %s", target)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                           timeout=600)
            return target, True
        except subprocess.CalledProcessError as e:
            logger.warning("rclone failed (rc=%d): %s — falling back to local",
                           e.returncode, e.stderr[:300])
        except subprocess.TimeoutExpired:
            logger.warning("rclone timed out — falling back to local")
    else:
        logger.warning("rclone not on PATH — falling back to local")

    fallback_root = Path(local_fallback).expanduser()
    fallback_root.mkdir(parents=True, exist_ok=True)
    final_path = fallback_root / source_dir.name
    if final_path.exists():
        shutil.rmtree(final_path)
    shutil.copytree(source_dir, final_path)
    logger.info("local copy -> %s", final_path)
    return str(final_path), False
