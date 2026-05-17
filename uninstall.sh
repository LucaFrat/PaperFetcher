#!/usr/bin/env bash
# PaperFetcher uninstaller. Removes everything the installer placed AND
# the systemd hooks the wizard created. Does NOT touch:
#   - apt packages (ffmpeg, rclone, jq, gum) — may be used by other things
#   - uv, Claude Code CLI, rclone config (general purpose)
#   - your Google Drive folder (your content, your call)
#
# Run via:
#   wget -qO- https://raw.githubusercontent.com/LucaFrat/PaperFetcher/main/uninstall.sh | bash
# or locally:
#   bash ~/.local/share/paperfetcher/uninstall.sh
set -euo pipefail

readonly INSTALL_DIR="${HOME}/.local/share/paperfetcher"
readonly UNIT_DIR="${HOME}/.config/systemd/user"
readonly ENV_FILE="${HOME}/.config/environment.d/paperfetcher.conf"

# ---------- pretty output ----------
c_red()    { printf '\033[31m%s\033[0m' "$*"; }
c_green()  { printf '\033[32m%s\033[0m' "$*"; }
c_yellow() { printf '\033[33m%s\033[0m' "$*"; }
c_bold()   { printf '\033[1m%s\033[0m' "$*"; }

step()    { printf '\n%s %s\n' "$(c_bold "==>")" "$(c_bold "$*")"; }
info()    { printf '    %s\n' "$*"; }
ok()      { printf '    %s %s\n' "$(c_green "✓")" "$*"; }
removed() { printf '    %s removed: %s\n' "$(c_green "✓")" "$*"; }
skipped() { printf '    %s skipped: %s\n' "$(c_yellow "·")" "$*"; }

# ---------- argument parsing ----------
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--yes]

  --yes, -y    Skip the confirmation prompt.
EOF
            exit 0
            ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# ---------- banner + confirm ----------
cat <<'BANNER'

  ╔═══════════════════════════════════════╗
  ║       PaperFetcher  uninstaller       ║
  ╚═══════════════════════════════════════╝

This will remove:
  - ~/.local/share/paperfetcher  (project files, .venv, output, logs)
  - ~/.config/systemd/user/paperfetcher.{service,timer}
  - ~/.config/environment.d/paperfetcher.conf  (your ElevenLabs key, if set)
  - the running systemd timer + service

This will NOT remove:
  - apt packages (ffmpeg, rclone, jq, gum, libnotify-bin)
  - uv, Claude Code CLI, rclone configuration
  - your Google Drive folder of past episodes
  - linger setting on your account

BANNER

if [[ "${ASSUME_YES}" -eq 0 ]]; then
    read -rp "Proceed with uninstall? [y/N] " reply
    if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        exit 0
    fi
fi

# ---------- 1. stop + disable systemd units ----------
step "Stopping and disabling systemd units"
if systemctl --user list-unit-files paperfetcher.timer >/dev/null 2>&1; then
    systemctl --user disable --now paperfetcher.timer 2>/dev/null || true
    ok "paperfetcher.timer disabled"
else
    skipped "paperfetcher.timer (not installed)"
fi
if systemctl --user list-unit-files paperfetcher.service >/dev/null 2>&1; then
    systemctl --user stop paperfetcher.service 2>/dev/null || true
    ok "paperfetcher.service stopped"
fi

# ---------- 2. unit files ----------
step "Removing unit files"
for f in "${UNIT_DIR}/paperfetcher.timer" "${UNIT_DIR}/paperfetcher.service"; do
    if [[ -f "$f" ]]; then
        rm -f "$f"
        removed "$f"
    else
        skipped "$f (does not exist)"
    fi
done
systemctl --user daemon-reload

# ---------- 3. environment.d file + runtime env ----------
step "Removing API key file"
if [[ -f "${ENV_FILE}" ]]; then
    rm -f "${ENV_FILE}"
    removed "${ENV_FILE}"
else
    skipped "${ENV_FILE} (does not exist)"
fi
# unset-environment can silently no-op for vars that came in via
# import-environment (observed on systemd 255). Blank the value first so
# even if unset is ineffective there's no key left behind.
systemctl --user set-environment ELEVENLABS_API_KEY= 2>/dev/null || true
systemctl --user unset-environment ELEVENLABS_API_KEY 2>/dev/null || true

# ---------- 4. install directory ----------
step "Removing install directory"
if [[ -d "${INSTALL_DIR}" ]]; then
    rm -rf "${INSTALL_DIR}"
    removed "${INSTALL_DIR}"
else
    skipped "${INSTALL_DIR} (does not exist)"
fi

# ---------- summary ----------
step "Done"
cat <<EOF

Things you may want to clean up manually:

  - Episode folder on Google Drive (rclone purge <remote>:<folder>)
  - apt packages, if you don't use them for anything else:
      sudo apt remove ffmpeg rclone jq gum libnotify-bin
  - rclone remote configuration:
      rclone config delete <remote-name>
  - Linger (if you enabled it just for PaperFetcher):
      sudo loginctl disable-linger \$USER

EOF
