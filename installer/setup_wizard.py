"""Interactive PaperFetcher setup wizard. Runs after install.sh's bash bootstrap."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).resolve().parent / "templates"

EDGE_VOICES = [
    ("Aria   (US, female, warm newsreader)",  "en-US-AriaNeural"),
    ("Guy    (US, male, clear)",              "en-US-GuyNeural"),
    ("Jenny  (US, female, conversational)",   "en-US-JennyNeural"),
    ("Davis  (US, male, friendly)",           "en-US-DavisNeural"),
    ("Sonia  (UK, female, BBC tone)",         "en-GB-SoniaNeural"),
    ("Ryan   (UK, male, BBC tone)",           "en-GB-RyanNeural"),
]

ELEVENLABS_MODELS = [
    ("eleven_turbo_v2_5      (recommended, half-cost)",        "eleven_turbo_v2_5"),
    ("eleven_multilingual_v2 (highest quality, 2x cost)",      "eleven_multilingual_v2"),
]


# ---------- gum wrappers ----------

def _gum(*args: str) -> str:
    """Run a gum subcommand, return stripped stdout. Esc/Ctrl-C -> exit."""
    try:
        out = subprocess.run(
            ["gum", *args],
            check=True, capture_output=True, text=True, stdin=sys.stdin,
        )
    except FileNotFoundError:
        sys.exit("gum is not installed (install.sh should have handled this).")
    except subprocess.CalledProcessError as e:
        if e.returncode in (1, 130):
            sys.exit("\nCancelled.")
        raise
    return out.stdout.rstrip("\n")


def gum_input(*, prompt: str, default: str = "", placeholder: str = "",
              header: str = "", password: bool = False) -> str:
    args = ["input", "--prompt", prompt, "--width", "70"]
    if header:
        args += ["--header", header]
    if placeholder:
        args += ["--placeholder", placeholder]
    if default:
        args += ["--value", default]
    if password:
        args += ["--password"]
    return _gum(*args)


def gum_choose(*, header: str, options: list[str]) -> str:
    args = ["choose", "--header", header,
            "--height", str(min(len(options) + 2, 12)),
            *options]
    return _gum(*args)


def gum_confirm(prompt: str, *, default_yes: bool = True) -> bool:
    args = ["confirm", prompt]
    if not default_yes:
        args += ["--default=false"]
    try:
        subprocess.run(["gum", *args], check=True, stdin=sys.stdin)
        return True
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return False
        if e.returncode == 130:
            sys.exit("\nCancelled.")
        raise


def section(title: str) -> None:
    """Bold colored divider above each major section."""
    subprocess.run(
        ["gum", "style",
         "--foreground", "212", "--bold",
         "--margin", "1 0 0 0",
         f"── {title} ──"],
        check=False,
    )


def styled_box(text: str) -> None:
    subprocess.run(
        ["gum", "style",
         "--border", "rounded",
         "--border-foreground", "212",
         "--margin", "1 0",
         "--padding", "1 2",
         text],
        check=False,
    )


# ---------- prompt helpers ----------

def ask_int(*, prompt: str, header: str, default: int, lo: int, hi: int) -> int:
    while True:
        raw = gum_input(prompt=prompt, default=str(default), header=header,
                        placeholder=str(default))
        try:
            n = int(raw)
        except ValueError:
            print(f"  Need an integer between {lo} and {hi}.")
            continue
        if not lo <= n <= hi:
            print(f"  Need a value between {lo} and {hi}.")
            continue
        return n


def ask_time_hhmm(*, prompt: str, header: str, default: str) -> str:
    pattern = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
    while True:
        raw = gum_input(prompt=prompt, default=default, header=header,
                        placeholder="HH:MM (24h)")
        if pattern.fullmatch(raw):
            return raw
        print("  Need HH:MM in 24-hour format, e.g. 05:30 or 18:00.")


# ---------- per-step wizard ----------

def step_episode() -> int:
    section("Episode")
    return ask_int(
        prompt="Length (min)> ",
        header="How long should each episode be? Range 5-15. "
               "Longer = more TTS credits, more Claude time.",
        default=10, lo=5, hi=15,
    )


def step_tts_backend() -> str:
    section("Text-to-speech")
    label = gum_choose(
        header="Which TTS engine? (Use ↑/↓ to move, Enter to pick.)",
        options=[
            "Edge TTS    — free, cloud, no API key, decent quality",
            "ElevenLabs  — paid (~$22/mo Creator), much better quality",
        ],
    )
    return "edge_tts" if label.startswith("Edge") else "elevenlabs"


def step_edge_voices() -> tuple[str, str]:
    labels = [label for (label, _) in EDGE_VOICES]
    a_label = gum_choose(
        header="Voice A — the curious co-host who drives the conversation:",
        options=labels,
    )
    b_label = gum_choose(
        header="Voice B — the expert co-host who explains the paper:",
        options=labels,
    )
    a = next(v for (l, v) in EDGE_VOICES if l == a_label)
    b = next(v for (l, v) in EDGE_VOICES if l == b_label)
    return a, b


def step_elevenlabs() -> tuple[str, str, str, str]:
    api_key = gum_input(
        prompt="API key> ",
        header="Paste your ElevenLabs API key. Create one at "
               "https://elevenlabs.io/app/settings/api-keys "
               "with text_to_speech + user_read scopes.",
        placeholder="sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        password=True,
    )
    if not api_key:
        sys.exit("ElevenLabs API key cannot be empty.")
    voice_a = gum_input(
        prompt="Voice A id> ",
        header="Browse https://elevenlabs.io/voice-library and copy a voice's "
               "ID (the curious co-host).",
        placeholder="20-character alphanumeric ID",
    )
    voice_b = gum_input(
        prompt="Voice B id> ",
        header="A second voice ID for the expert co-host.",
        placeholder="20-character alphanumeric ID",
    )
    label = gum_choose(
        header="Pick the synthesis model. Turbo is half-cost and very close in "
               "quality for technical English; Multilingual is the gold standard.",
        options=[m[0] for m in ELEVENLABS_MODELS],
    )
    model = next(m for (l, m) in ELEVENLABS_MODELS if l == label)
    return api_key, voice_a, voice_b, model


def step_paper_sourcing() -> str:
    section("Paper sourcing")
    return gum_input(
        prompt="arXiv categories> ",
        header="Comma-separated arXiv category codes to monitor. See the full "
               "taxonomy at https://arxiv.org/category_taxonomy.",
        placeholder="e.g. cs.RO, cs.LG, cs.AI, cs.CV",
        default="cs.RO, cs.LG, cs.AI, cs.CV",
    )


def step_interests(categories: str) -> None:
    template = (TEMPLATES / "interests.md.tmpl").read_text()
    placeholder = gum_input(
        prompt="One-line interests> ",
        header="What you research / care about. Used by the embedding model "
               "and Claude to pick papers. You'll get to flesh this out in an "
               "editor next.",
        placeholder="e.g. robot learning, sim-to-real, dexterous manipulation",
        default="robot learning",
    )
    body = template.format(categories=categories, placeholder_topic=placeholder)
    target = REPO_ROOT / "config" / "interests.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    editor = os.environ.get("EDITOR") or shutil.which("nano") or "vi"
    if gum_confirm(f"Open {target.name} in {editor} now to flesh it out?"):
        subprocess.run([editor, str(target)], check=False)


def step_schedule() -> str:
    section("Schedule")
    label = gum_choose(
        header="How often should PaperFetcher run? Weekdays-only is "
               "recommended since arXiv doesn't post on weekends.",
        options=["Weekdays only (Mon-Fri)", "Every day"],
    )
    daily = label.startswith("Every")
    hhmm = ask_time_hhmm(
        prompt="Time (HH:MM)> ",
        header="When should the cron fire each day? 24-hour format. "
               "Pick early-morning so the episode is ready for your commute.",
        default="05:30",
    )
    prefix = "*-*-*" if daily else "Mon..Fri *-*-*"
    return f"{prefix} {hhmm}:00"


def step_rclone() -> tuple[str, str]:
    section("Google Drive (rclone)")
    remote = gum_input(
        prompt="rclone remote name> ",
        header="The name you'll give your Google Drive remote in rclone. "
               "Used as 'remote:folder' in rclone copy commands.",
        placeholder="any short name, e.g. gdrive",
        default="gdrive",
    )
    have = subprocess.run(
        ["rclone", "listremotes"], capture_output=True, text=True,
    ).stdout.splitlines()
    have_clean = [r.rstrip(":") for r in have]
    if remote not in have_clean:
        print(f"  rclone remote '{remote}' is not configured yet.")
        print(f"  We'll launch `rclone config` next. In the wizard, pick:")
        print(f"     name = {remote}")
        print(f"     storage = drive (Google Drive)")
        print(f"     leave id / secret blank")
        print(f"     scope = drive")
        print(f"     auto-config = yes  (opens your browser)")
        if gum_confirm("Run rclone config now?"):
            subprocess.run(["rclone", "config"], check=False)
    folder = gum_input(
        prompt="Drive folder> ",
        header="Subfolder inside your Drive root where dated episode folders "
               "will be created (e.g. PaperFetcher/2026-05-12/).",
        placeholder="e.g. PaperFetcher",
        default="PaperFetcher",
    )
    return remote, folder


# ---------- file generation ----------

def write_settings_toml(*, target_minutes: int, audio_backend: str,
                        voice_a: str, voice_b: str, elevenlabs_model: str,
                        rclone_remote: str, rclone_folder: str) -> None:
    template = (TEMPLATES / "settings.toml.tmpl").read_text()
    body = template.format(
        target_minutes=target_minutes,
        audio_backend=audio_backend,
        voice_a=voice_a,
        voice_b=voice_b,
        elevenlabs_model=elevenlabs_model or "eleven_turbo_v2_5",
        rclone_remote=rclone_remote,
        rclone_folder=rclone_folder,
    )
    (REPO_ROOT / "config" / "settings.toml").write_text(body, encoding="utf-8")


def write_env_d_for_elevenlabs(api_key: str) -> None:
    env_d = Path.home() / ".config" / "environment.d"
    env_d.mkdir(parents=True, exist_ok=True)
    target = env_d / "paperfetcher.conf"
    target.write_text(f"ELEVENLABS_API_KEY={api_key}\n", encoding="utf-8")
    target.chmod(0o600)
    subprocess.run(
        ["systemctl", "--user", "import-environment", "ELEVENLABS_API_KEY"],
        env={**os.environ, "ELEVENLABS_API_KEY": api_key},
        check=False,
    )


def write_systemd_units(*, oncalendar: str) -> None:
    user_units = Path.home() / ".config" / "systemd" / "user"
    user_units.mkdir(parents=True, exist_ok=True)
    service = (TEMPLATES / "paperfetcher.service.tmpl").read_text().format(
        repo_path=str(REPO_ROOT),
    )
    timer = (TEMPLATES / "paperfetcher.timer.tmpl").read_text().format(
        oncalendar=oncalendar,
    )
    (user_units / "paperfetcher.service").write_text(service, encoding="utf-8")
    (user_units / "paperfetcher.timer").write_text(timer, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now",
                    "paperfetcher.timer"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def maybe_enable_linger() -> None:
    state = subprocess.run(
        ["loginctl", "show-user", os.environ["USER"]],
        capture_output=True, text=True,
    ).stdout
    if "Linger=yes" in state:
        return
    section("Linger")
    print("  Without `linger`, the systemd timer pauses when you log out.")
    print("  Enabling it requires sudo. Skip if your machine is always logged-in.")
    if gum_confirm("Run `sudo loginctl enable-linger`?"):
        subprocess.run(["sudo", "loginctl", "enable-linger",
                        os.environ["USER"]], check=False)


# ---------- main ----------

def main() -> int:
    print("Get ready to make a few choices...")

    target_minutes = step_episode()
    audio_backend = step_tts_backend()

    if audio_backend == "elevenlabs":
        api_key, voice_a, voice_b, elevenlabs_model = step_elevenlabs()
    else:
        voice_a, voice_b = step_edge_voices()
        api_key, elevenlabs_model = "", "eleven_turbo_v2_5"

    categories = step_paper_sourcing()
    step_interests(categories)
    oncalendar = step_schedule()
    rclone_remote, rclone_folder = step_rclone()

    section("Review")
    summary_lines = [
        f"Length:    {target_minutes} min",
        f"TTS:       {audio_backend}",
        f"Voice A:   {voice_a}",
        f"Voice B:   {voice_b}",
        f"Schedule:  {oncalendar}",
        f"Drive:     {rclone_remote}:{rclone_folder}",
        f"Repo:      {REPO_ROOT}",
    ]
    styled_box("\n".join(summary_lines))
    if not gum_confirm("Write configuration?"):
        sys.exit("Aborted before writing.")

    write_settings_toml(
        target_minutes=target_minutes, audio_backend=audio_backend,
        voice_a=voice_a, voice_b=voice_b,
        elevenlabs_model=elevenlabs_model,
        rclone_remote=rclone_remote, rclone_folder=rclone_folder,
    )
    if audio_backend == "elevenlabs":
        write_env_d_for_elevenlabs(api_key)
    write_systemd_units(oncalendar=oncalendar)
    maybe_enable_linger()

    section("Done")
    styled_box(
        "Smoke test:        bash run.sh --dry-run\n"
        "Trigger now:       systemctl --user start paperfetcher.service\n"
        "Watch live:        journalctl --user -u paperfetcher -f\n"
        "Next firing:       systemctl --user list-timers paperfetcher.timer\n"
        "Uninstall later:   bash uninstall.sh"
    )
    if gum_confirm("Run a dry-run now (fetch + rank only, no audio, no delivery)?"):
        subprocess.run(["bash", str(REPO_ROOT / "run.sh"), "--dry-run"], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
