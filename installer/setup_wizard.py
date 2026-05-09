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

# A small curated Edge TTS voice list (en-US/en-GB), so users don't have to
# browse all 400+ voices. Each entry: (display label, voice_id).
EDGE_VOICES = [
    ("Aria (US, female, warm newsreader)",   "en-US-AriaNeural"),
    ("Guy (US, male, clear)",                "en-US-GuyNeural"),
    ("Jenny (US, female, conversational)",   "en-US-JennyNeural"),
    ("Davis (US, male, friendly)",           "en-US-DavisNeural"),
    ("Sonia (UK, female, BBC tone)",         "en-GB-SoniaNeural"),
    ("Ryan (UK, male, BBC tone)",            "en-GB-RyanNeural"),
]

ELEVENLABS_MODELS = [
    ("eleven_turbo_v2_5 (recommended, half-cost)", "eleven_turbo_v2_5"),
    ("eleven_multilingual_v2 (highest quality, 2× cost)", "eleven_multilingual_v2"),
]


# ---------- gum wrappers ----------

def _gum(*args: str, **popen_kwargs) -> str:
    """Run a gum subcommand, return stripped stdout. Cancellation -> exit."""
    try:
        out = subprocess.run(
            ["gum", *args],
            check=True, capture_output=True, text=True, **popen_kwargs,
        )
    except FileNotFoundError:
        sys.exit("gum is not installed (install.sh should have handled this).")
    except subprocess.CalledProcessError as e:
        # gum exits 130 on Ctrl-C / Esc — treat as cancellation.
        if e.returncode in (130, 1):
            sys.exit("\nCancelled.")
        raise
    return out.stdout.rstrip("\n")


def gum_input(prompt: str, *, default: str = "", placeholder: str = "",
              password: bool = False) -> str:
    args = ["input", "--prompt", f"{prompt} ", "--width", "80"]
    if default:
        args += ["--value", default]
    if placeholder:
        args += ["--placeholder", placeholder]
    if password:
        args += ["--password"]
    return _gum(*args)


def gum_choose(prompt: str, options: list[str], *, header: str = "") -> str:
    print(f"\n{prompt}")
    args = ["choose", "--height", str(min(len(options) + 2, 12))]
    if header:
        args += ["--header", header]
    args += options
    return _gum(*args)


def gum_confirm(prompt: str, *, default_yes: bool = True) -> bool:
    args = ["confirm", prompt]
    if not default_yes:
        args += ["--default=false"]
    try:
        subprocess.run(["gum", *args], check=True, stdin=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return False
        if e.returncode == 130:
            sys.exit("\nCancelled.")
        raise


def gum_format(text: str) -> None:
    subprocess.run(["gum", "format"], input=text, text=True, check=False)


# ---------- prompt helpers ----------

def ask_int(prompt: str, *, default: int, lo: int, hi: int) -> int:
    while True:
        raw = gum_input(prompt, default=str(default))
        try:
            n = int(raw)
        except ValueError:
            print(f"  Need an integer between {lo} and {hi}, got {raw!r}.")
            continue
        if not lo <= n <= hi:
            print(f"  Need a value between {lo} and {hi}, got {n}.")
            continue
        return n


def ask_time_hhmm(prompt: str, *, default: str) -> str:
    pattern = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
    while True:
        raw = gum_input(prompt, default=default, placeholder="HH:MM (24h)")
        if pattern.fullmatch(raw):
            return raw
        print("  Need HH:MM in 24-hour format, e.g. 05:30 or 18:00.")


# ---------- per-step wizard ----------

def banner() -> None:
    gum_format(
        "# PaperFetcher setup wizard\n\n"
        "We'll configure your daily arXiv → podcast pipeline. "
        "Press **Esc** at any prompt to cancel.\n"
    )


def step_podcast_length() -> int:
    return ask_int(
        "Episode length in minutes (5-15):",
        default=10, lo=5, hi=15,
    )


def step_tts_backend() -> str:
    label = gum_choose(
        "Which TTS engine?",
        options=[
            "Edge TTS  —  free, cloud, no API key, decent quality",
            "ElevenLabs  —  paid (~$22/mo Creator), much better quality",
        ],
        header="Free now, or pay for higher fidelity?",
    )
    return "edge_tts" if label.startswith("Edge") else "elevenlabs"


def step_edge_voices() -> tuple[str, str]:
    labels = [label for (label, _) in EDGE_VOICES]
    a_label = gum_choose("Pick voice A (the curious co-host):", labels)
    b_label = gum_choose("Pick voice B (the expert co-host):", labels)
    a = next(v for (l, v) in EDGE_VOICES if l == a_label)
    b = next(v for (l, v) in EDGE_VOICES if l == b_label)
    return a, b


def step_elevenlabs() -> tuple[str, str, str, str]:
    gum_format(
        "## ElevenLabs setup\n\n"
        "1. Subscribe to **Creator** at https://elevenlabs.io/pricing\n"
        "2. Browse voices at https://elevenlabs.io/voice-library — copy two voice IDs\n"
        "3. Create an API key with **text_to_speech: convert** + **user: read** scopes\n"
    )
    api_key = gum_input(
        "Paste your ElevenLabs API key:",
        placeholder="sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        password=True,
    )
    if not api_key:
        sys.exit("ElevenLabs API key cannot be empty.")
    voice_a = gum_input("Voice ID A (curious co-host):",
                        placeholder="J2FGlQG8Gd7x8uEDt2H8")
    voice_b = gum_input("Voice ID B (expert co-host):",
                        placeholder="Fahco4VZzobUeiPqni1S")

    label = gum_choose("Model:", [m[0] for m in ELEVENLABS_MODELS])
    model = next(m for (l, m) in ELEVENLABS_MODELS if l == label)
    return api_key, voice_a, voice_b, model


def step_categories() -> str:
    return gum_input(
        "arXiv categories (comma-separated):",
        default="cs.RO, cs.LG, cs.AI, cs.CV",
        placeholder="cs.RO, cs.LG, …",
    )


def step_interests(categories: str) -> None:
    """Write template, open in $EDITOR, leave the file in place."""
    template = (TEMPLATES / "interests.md.tmpl").read_text()
    placeholder_topic = gum_input(
        "One-sentence summary of your research interests (you'll edit the full file in a moment):",
        placeholder="e.g. robot learning for dexterous manipulation",
    )
    body = template.format(
        categories=categories,
        placeholder_topic=placeholder_topic or "(fill in your interests)",
    )
    target = REPO_ROOT / "config" / "interests.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")

    editor = os.environ.get("EDITOR") or shutil.which("nano") or "vi"
    if gum_confirm(f"Open {target.name} in {editor} now to flesh out your interests?"):
        subprocess.run([editor, str(target)], check=False)


def step_schedule() -> str:
    """Returns an OnCalendar string like 'Mon..Fri *-*-* 05:30:00'."""
    label = gum_choose(
        "How often should PaperFetcher run?",
        options=["Weekdays only (Mon-Fri)", "Every day"],
    )
    daily = label.startswith("Every")
    hhmm = ask_time_hhmm("Time of day to fire:", default="05:30")
    prefix = "*-*-*" if daily else "Mon..Fri *-*-*"
    return f"{prefix} {hhmm}:00"


def step_rclone() -> tuple[str, str]:
    """Returns (remote_name, folder_name)."""
    remote = gum_input("rclone remote name:", default="gdrive",
                       placeholder="name you give it during 'rclone config'")

    have = subprocess.run(
        ["rclone", "listremotes"], capture_output=True, text=True,
    ).stdout.splitlines()
    have_clean = [r.rstrip(":") for r in have]
    if remote not in have_clean:
        gum_format(
            f"## rclone remote `{remote}` not configured yet\n\n"
            "rclone needs a one-time browser auth to access your Google Drive. "
            "We'll launch `rclone config` now — pick:\n"
            f"- name: **{remote}**\n"
            "- storage: **drive** (Google Drive)\n"
            "- leave client_id / client_secret blank\n"
            "- scope: **drive**\n"
            "- auto-config: **yes**\n"
        )
        if gum_confirm("Run rclone config interactively?"):
            subprocess.run(["rclone", "config"], check=False)

    folder = gum_input("Drive folder for episodes:", default="PaperFetcher")
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
    # Make it visible to the running user-systemd manager too.
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
                    "paperfetcher.timer"], check=False)


def maybe_enable_linger() -> None:
    state = subprocess.run(
        ["loginctl", "show-user", os.environ["USER"]],
        capture_output=True, text=True,
    ).stdout
    if "Linger=yes" in state:
        return
    gum_format(
        "## One last thing: enable linger\n\n"
        "Without `linger`, the systemd timer pauses when you log out. Enabling "
        "it requires sudo. Skip if your machine is always logged-in.\n"
    )
    if gum_confirm("Run `sudo loginctl enable-linger`?"):
        subprocess.run(["sudo", "loginctl", "enable-linger",
                        os.environ["USER"]], check=False)


# ---------- main ----------

def main() -> int:
    banner()

    target_minutes = step_podcast_length()
    audio_backend = step_tts_backend()

    api_key = ""
    if audio_backend == "elevenlabs":
        api_key, voice_a, voice_b, elevenlabs_model = step_elevenlabs()
    else:
        voice_a, voice_b = step_edge_voices()
        elevenlabs_model = "eleven_turbo_v2_5"

    categories = step_categories()
    step_interests(categories)
    oncalendar = step_schedule()
    rclone_remote, rclone_folder = step_rclone()

    gum_format(
        "## Summary\n\n"
        f"- Episode length: **{target_minutes} min**\n"
        f"- TTS: **{audio_backend}**\n"
        f"- Voices: A=`{voice_a}`, B=`{voice_b}`\n"
        f"- Schedule: `{oncalendar}`\n"
        f"- Drive target: `{rclone_remote}:{rclone_folder}`\n"
        f"- Repo path: `{REPO_ROOT}`\n"
    )
    if not gum_confirm("Write configuration and enable the timer?"):
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

    gum_format(
        "## ✓ Setup complete\n\n"
        f"- Repo:    `{REPO_ROOT}`\n"
        f"- Logs:    `{REPO_ROOT}/logs/`\n"
        f"- Output:  `{REPO_ROOT}/output/<date>/`\n"
        f"- Drive:   `{rclone_remote}:{rclone_folder}/<date>/`\n\n"
        "**Run a smoke test now:**  `bash run.sh --dry-run`\n"
        "**Trigger immediately:**   `systemctl --user start paperfetcher.service`\n"
        "**See next firing:**       `systemctl --user list-timers paperfetcher.timer`\n"
    )
    if gum_confirm("Run a dry-run now (fetch + rank only, no audio, no delivery)?"):
        subprocess.run(["bash", str(REPO_ROOT / "run.sh"), "--dry-run"], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
