"""Pipeline orchestrator: fetch → rank → digest → script → audio → deliver → state.add.

CLI flags: --dry-run / --no-audio / --no-deliver each short-circuit later stages.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import audio as audio_mod
from . import deliver as deliver_mod
from . import digest as digest_mod
from . import fetch as fetch_mod
from . import rank as rank_mod
from . import script as script_mod
from . import state as state_mod
from .config import load_settings, parse_interests

logger = logging.getLogger("paperfatcher")


def _setup_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(logs_dir / "pipeline.log", encoding="utf-8"),
        ],
    )


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="paperfatcher")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch + rank only; skip download/digest/audio/deliver")
    parser.add_argument("--no-audio", action="store_true",
                        help="skip TTS synthesis")
    parser.add_argument("--no-deliver", action="store_true",
                        help="skip rclone push (local-only run)")
    args = parser.parse_args(argv)

    settings = load_settings()
    _setup_logging(settings.paths.logs_dir)
    logger.info("=== PaperFatcher run %s ===", _today())
    logger.info("flags: dry_run=%s no_audio=%s no_deliver=%s",
                args.dry_run, args.no_audio, args.no_deliver)

    # Fail fast on missing API key — otherwise we'd waste 5+ min of fetch
    # and Claude work before audio synth discovers the missing key.
    if (not args.no_audio and not args.dry_run
            and settings.audio.backend == "elevenlabs"
            and not os.environ.get("ELEVENLABS_API_KEY")):
        logger.error(
            "ELEVENLABS_API_KEY not set but [audio] backend = elevenlabs. "
            "Set it for systemd via ~/.config/environment.d/, or switch the "
            "backend to 'edge_tts' in config/settings.toml.")
        return 4

    interests_body = parse_interests(settings.paths.interests)
    if not interests_body:
        logger.error("interests.md is empty: %s", settings.paths.interests)
        return 2
    logger.info("categories: %s", fetch_mod.DEFAULT_CATEGORIES)

    excluded = state_mod.load(settings.paths.state_file)
    logger.info("picked.json holds %d ids", len(excluded))

    papers = fetch_mod.fetch_recent(
        categories=fetch_mod.DEFAULT_CATEGORIES,
        window_hours=settings.fetch.window_hours,
        request_delay_seconds=settings.fetch.request_delay_seconds,
        exclude_ids=excluded,
    )
    if not papers:
        logger.warning("no papers after fetch+exclude — nothing to do")
        return 0

    paper = rank_mod.pick_top(
        papers,
        interests_body=interests_body,
        embedding_model=settings.rank.embedding_model,
        shortlist_size=settings.rank.shortlist_size,
    )
    if paper is None:
        logger.error("ranker returned no pick")
        return 3
    logger.info("PICKED %s — %s", paper.id, paper.title)

    if args.dry_run:
        logger.info("dry-run complete")
        return 0

    day_dir = settings.paths.output_dir / _today()
    day_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = digest_mod.download_pdf(paper, day_dir)
    paper_text = digest_mod.extract_text(pdf_path)
    digest_mod.write_digest(paper, paper_text, day_dir)

    script_path = script_mod.generate(
        paper, paper_text, day_dir,
        target_minutes=settings.script.target_minutes,
    )

    if not args.no_audio:
        audio_mod.synthesize(script_path, day_dir, audio_cfg=settings.audio)
    else:
        logger.info("skipping audio synthesis (--no-audio)")

    if not args.no_deliver:
        location, used_remote = deliver_mod.deliver(
            day_dir,
            rclone_remote=settings.deliver.rclone_remote,
            local_fallback=settings.deliver.local_fallback,
        )
        logger.info("delivered to %s (remote=%s)", location, used_remote)
    else:
        logger.info("skipping delivery (--no-deliver)")

    if not args.no_audio and not args.no_deliver:
        state_mod.add(settings.paths.state_file, paper.id)
        logger.info("recorded %s in %s", paper.id, settings.paths.state_file)
    else:
        logger.info("skipping picked.json record (partial run)")
    logger.info("=== run complete ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
