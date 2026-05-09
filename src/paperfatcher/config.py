"""TOML settings loader and interests.md frontmatter parser."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FetchCfg:
    window_hours: int
    request_delay_seconds: float


@dataclass(frozen=True)
class RankCfg:
    shortlist_size: int
    embedding_model: str


@dataclass(frozen=True)
class ScriptCfg:
    target_minutes: int


@dataclass(frozen=True)
class AudioCfg:
    backend: str
    voice_a: str
    voice_b: str
    elevenlabs_model: str = "eleven_turbo_v2_5"
    elevenlabs_output_format: str = "mp3_44100_128"


@dataclass(frozen=True)
class DeliverCfg:
    rclone_remote: str
    local_fallback: str


@dataclass(frozen=True)
class PathsCfg:
    output_dir: Path
    state_file: Path
    logs_dir: Path
    interests: Path


@dataclass(frozen=True)
class Settings:
    fetch: FetchCfg
    rank: RankCfg
    script: ScriptCfg
    audio: AudioCfg
    deliver: DeliverCfg
    paths: PathsCfg
    repo_root: Path


def load_settings(repo_root: Path | None = None) -> Settings:
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    with (repo_root / "config" / "settings.toml").open("rb") as f:
        raw = tomllib.load(f)

    def p(rel: str) -> Path:
        return (repo_root / rel).resolve() if not Path(rel).is_absolute() else Path(rel)

    return Settings(
        fetch=FetchCfg(**raw["fetch"]),
        rank=RankCfg(**raw["rank"]),
        script=ScriptCfg(**raw.get("script", {"target_minutes": 10})),
        audio=AudioCfg(**raw["audio"]),
        deliver=DeliverCfg(**raw["deliver"]),
        paths=PathsCfg(
            output_dir=p(raw["paths"]["output_dir"]),
            state_file=p(raw["paths"]["state_file"]),
            logs_dir=p(raw["paths"]["logs_dir"]),
            interests=p(raw["paths"]["interests"]),
        ),
        repo_root=repo_root,
    )


def parse_interests(path: Path) -> tuple[list[str], str]:
    text = path.read_text(encoding="utf-8")
    categories: list[str] = []
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            front = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            for line in front.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    if k.strip().lower() == "categories":
                        categories = [c.strip() for c in v.split(",") if c.strip()]
    return categories, body.strip()
