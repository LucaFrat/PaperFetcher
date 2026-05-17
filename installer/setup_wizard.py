"""Interactive PaperFetcher setup wizard. Runs after install.sh's bash bootstrap."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).resolve().parent / "templates"

# Brighten gum's default header / placeholder text. gum ships with foreground
# 240 (dark grey) which is unreadable on most dark terminal themes. 252 is a
# near-white grey for headers, 245 keeps placeholders distinguishable from
# real input while still being visible. setdefault so users can override.
_HEADER_FG = "252"
_PLACEHOLDER_FG = "245"
for _var, _val in {
    "GUM_INPUT_HEADER_FOREGROUND":      _HEADER_FG,
    "GUM_INPUT_PLACEHOLDER_FOREGROUND": _PLACEHOLDER_FG,
    "GUM_CHOOSE_HEADER_FOREGROUND":     _HEADER_FG,
    "GUM_WRITE_HEADER_FOREGROUND":      _HEADER_FG,
    "GUM_WRITE_PLACEHOLDER_FOREGROUND": _PLACEHOLDER_FG,
    "GUM_CONFIRM_PROMPT_FOREGROUND":    _HEADER_FG,
}.items():
    os.environ.setdefault(_var, _val)

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
    """Run a gum subcommand, return stripped stdout. Esc/Ctrl-C -> exit.

    Capture stdout (= the user's selection / typed value) but leave stderr
    inherited. gum draws its interactive TUI on stderr; if we capture it,
    gum sees a non-TTY and falls back to non-interactive mode (returns
    empty instantly) — i.e. the prompt never visibly appears.
    """
    try:
        out = subprocess.run(
            ["gum", *args],
            check=True, text=True,
            stdin=sys.stdin, stdout=subprocess.PIPE, stderr=None,
        )
    except FileNotFoundError:
        sys.exit("gum is not installed (install.sh should have handled this).")
    except subprocess.CalledProcessError as e:
        if e.returncode in (1, 130):
            sys.exit("\nCancelled.")
        raise
    return out.stdout.rstrip("\n")


def gum_input(*, prompt: str, default: str = "", placeholder: str = "",
              header: str = "", password: bool = False,
              required: bool = False) -> str:
    args = ["input", "--prompt", prompt, "--width", "70"]
    if header:
        args += ["--header", header]
    if placeholder:
        args += ["--placeholder", placeholder]
    if default:
        args += ["--value", default]
    if password:
        args += ["--password"]
    while True:
        value = _gum(*args)
        if not required or value.strip():
            return value
        print("  This field can't be empty — please enter a value.")


def gum_choose(*, header: str, options: list[str]) -> str:
    args = ["choose", "--header", header,
            "--height", str(min(len(options) + 2, 12)),
            *options]
    return _gum(*args)


def gum_write(*, header: str, placeholder: str = "",
              width: int = 80, height: int = 14) -> str:
    """Multi-line text editor. Submit with Ctrl+D, cancel with Esc."""
    args = ["write",
            "--header", header,
            "--width", str(width),
            "--height", str(height),
            "--show-cursor-line",
            "--char-limit", "4000"]
    if placeholder:
        args += ["--placeholder", placeholder]
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


def _rclone_remote_works(remote: str) -> tuple[bool, str]:
    """Lightweight auth probe — `rclone lsd remote:` lists root folders.

    Cheap and catches the common failure modes (no token, expired token,
    orphan custom client_id like the one Google rejects with invalid_client).
    Returns (ok, last_error_line).
    """
    try:
        r = subprocess.run(
            ["rclone", "lsd", f"{remote}:"],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return False, "rclone lsd timed out after 30s"
    if r.returncode == 0:
        return True, ""
    err_lines = (r.stderr or r.stdout).strip().splitlines()
    return False, err_lines[-1] if err_lines else f"exit {r.returncode}"


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
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        styled_box(
            "ElevenLabs needs an API key, but ELEVENLABS_API_KEY isn't set\n"
            "in your shell. Pasting secrets into prompts feels gross — let's\n"
            "do it through your shell instead.\n\n"
            "1. Get a key at https://elevenlabs.io/app/settings/api-keys\n"
            "   (scopes: text_to_speech + user_read)\n\n"
            "2. In the SAME terminal you're running this installer in, run:\n"
            "       export ELEVENLABS_API_KEY=sk_xxxxxxxxxxxxxxxxxxxxxxxx\n\n"
            "3. Re-run the installer from that same terminal.\n\n"
            "Tip: add the export line to ~/.bashrc or ~/.zshrc to make it\n"
            "stick across shell sessions."
        )
        sys.exit(1)
    voice_a = gum_input(
        prompt="Voice A id> ",
        header="Browse https://elevenlabs.io/voice-library and copy a voice's "
               "ID (the curious co-host).",
        placeholder="20-character alphanumeric ID",
        required=True,
    )
    voice_b = gum_input(
        prompt="Voice B id> ",
        header="A second voice ID for the expert co-host.",
        placeholder="20-character alphanumeric ID",
        required=True,
    )
    label = gum_choose(
        header="Pick the synthesis model. Turbo is half-cost and very close in "
               "quality for technical English; Multilingual is the gold standard.",
        options=[m[0] for m in ELEVENLABS_MODELS],
    )
    model = next(m for (l, m) in ELEVENLABS_MODELS if l == label)
    return api_key, voice_a, voice_b, model


def step_schedule() -> str:
    section("Schedule")
    print("  arXiv mostly publishes Mon-Fri, but the 72-hour fetch window")
    print("  means weekend runs can still find recent papers to digest.")
    days_label = gum_choose(
        header="Which days should PaperFetcher run?",
        options=[
            "Weekdays only — Mon..Fri (matches arXiv's announce schedule)",
            "Every day     — Mon..Sun (also produces weekend digests)",
        ],
    )
    weekday_prefix = "Mon..Fri " if days_label.startswith("Weekdays") else ""
    hhmm = ask_time_hhmm(
        prompt="Time (HH:MM)> ",
        header="When should the cron fire? 24-hour format. "
               "Pick early-morning so the episode is ready for your commute.",
        default="05:30",
    )
    return f"{weekday_prefix}*-*-* {hhmm}:00"


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
    # Auth probe loop. Catches the gotcha that bit you (broken/orphan client_id,
    # expired token) before it costs you 5 min of Claude + ElevenLabs work on
    # tomorrow's run. User can still skip if they're fine with local fallback.
    while True:
        ok, err = _rclone_remote_works(remote)
        if ok:
            print(f"  ✓ rclone '{remote}:' authenticates")
            break
        print(f"  ✗ rclone can't list '{remote}:' — {err}")
        if not gum_confirm(f"Re-run rclone config to fix '{remote}'?"):
            print(f"  (continuing — daily runs will fall back to local delivery "
                  f"at ~/PaperFetcher-output/ until '{remote}:' is fixed)")
            break
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
    # The unit redirects stdout/stderr into logs/ via append:; systemd does
    # not auto-create the parent dir, so first run fails with 209/STDOUT
    # without this. (The unit also has ExecStartPre=mkdir -p as a safety net.)
    (REPO_ROOT / "logs").mkdir(exist_ok=True)
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


def step_verify(*, audio_backend: str, rclone_remote: str) -> int:
    """End-of-wizard sanity check.

    Reads the actual state the wizard just produced (files on disk + systemd
    user manager state) and reports per-check pass/fail. Critical failures
    return non-zero so install.sh aborts and the user investigates instead
    of waiting for tomorrow's silent breakage.
    """
    section("Final verification")
    failures: list[str] = []
    warnings: list[str] = []

    def check(label: str, ok: bool, detail: str = "", *, critical: bool = True) -> None:
        if ok:
            print(f"  ✓ {label}")
            return
        mark = "✗" if critical else "·"
        suffix = f" — {detail}" if detail else ""
        print(f"  {mark} {label}{suffix}")
        (failures if critical else warnings).append(label)

    # settings.toml exists and is valid TOML
    settings_path = REPO_ROOT / "config" / "settings.toml"
    try:
        with settings_path.open("rb") as f:
            tomllib.load(f)
        check("settings.toml exists and is valid TOML", True)
    except FileNotFoundError:
        check("settings.toml exists and is valid TOML", False, f"missing {settings_path}")
    except tomllib.TOMLDecodeError as e:
        check("settings.toml exists and is valid TOML", False, f"parse error: {e}")

    # ElevenLabs key plumbing (only if that backend was chosen)
    if audio_backend == "elevenlabs":
        env_file = Path.home() / ".config" / "environment.d" / "paperfetcher.conf"
        if env_file.exists():
            mode = env_file.stat().st_mode & 0o777
            check(f"ElevenLabs key file present, mode {oct(mode)[2:]}",
                  mode == 0o600,
                  f"expected 600, got {oct(mode)[2:]}")
        else:
            check("ElevenLabs key file present", False, f"missing {env_file}")
        envout = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True, text=True,
        ).stdout
        loaded = any(
            line.startswith("ELEVENLABS_API_KEY=") and len(line) > len("ELEVENLABS_API_KEY=")
            for line in envout.splitlines()
        )
        check("ELEVENLABS_API_KEY loaded into systemd user env", loaded,
              "import-environment may have failed; re-run installer")

    # systemd unit files exist on disk
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    for fname in ("paperfetcher.service", "paperfetcher.timer"):
        check(f"unit file {fname} present", (unit_dir / fname).exists())

    # timer enabled + active
    def systemctl_value(*args: str) -> str:
        return subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True, text=True,
        ).stdout.strip()

    enabled = systemctl_value("is-enabled", "paperfetcher.timer")
    check(f"timer enabled (is-enabled={enabled})", enabled == "enabled")
    active = systemctl_value("is-active", "paperfetcher.timer")
    check(f"timer active (is-active={active})", active == "active")

    # timer has a real scheduled next-fire (OnCalendar populated)
    next_us = systemctl_value("show", "paperfetcher.timer",
                              "-p", "NextElapseUSecRealtime", "--value")
    check("timer has a scheduled next-fire", next_us not in ("", "0"))

    # rclone target still works (warn-only — local fallback exists)
    ok, err = _rclone_remote_works(rclone_remote)
    check(f"rclone '{rclone_remote}:' authenticates", ok, err, critical=False)

    # linger (warn-only — user can skip)
    linger = subprocess.run(
        ["loginctl", "show-user", os.environ["USER"]],
        capture_output=True, text=True,
    ).stdout
    check("linger enabled (timer fires when logged out)",
          "Linger=yes" in linger,
          "without linger, timer pauses between logout and next login",
          critical=False)

    print()
    if failures:
        styled_box(
            f"⚠ {len(failures)} critical check(s) failed — see above.\n"
            "Tomorrow's scheduled run won't work. Fix and re-run installer."
        )
        return 1
    if warnings:
        styled_box(
            f"Wizard checks green, with {len(warnings)} non-critical warning(s).\n"
            "Daily run will work; warnings affect convenience or delivery only."
        )
    else:
        styled_box("All wizard checks passed ✓")
    return 0


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

    verify_rc = step_verify(
        audio_backend=audio_backend,
        rclone_remote=rclone_remote,
    )
    if verify_rc != 0:
        return verify_rc

    section("Wizard done")
    styled_box(
        "Config + systemd are set up. The next step is the interests chat\n"
        "with Claude — your installer will launch it in a moment.\n\n"
        "After that, useful commands:\n"
        "  Smoke test:       bash run.sh --dry-run\n"
        "  Trigger now:      systemctl --user start paperfetcher.service\n"
        "  Watch live:       journalctl --user -u paperfetcher -f\n"
        "  Next firing:      systemctl --user list-timers paperfetcher.timer\n"
        "  Redefine interests: bash installer/onboard_interests.sh\n"
        "  Uninstall later:  bash uninstall.sh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
