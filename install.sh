#!/usr/bin/env bash
# PaperFetcher one-command installer for Ubuntu / Debian.
# Run via:
#   wget -qO- https://raw.githubusercontent.com/LucaFrat/PaperFetcher/main/install.sh | bash
set -euo pipefail

readonly REPO_URL="https://github.com/LucaFrat/PaperFetcher.git"
readonly INSTALL_DIR="${HOME}/.local/share/paperfetcher"
readonly CLAUDE_DOCS="https://code.claude.com/docs"

# ---------- pretty output ----------
c_red()    { printf '\033[31m%s\033[0m' "$*"; }
c_green()  { printf '\033[32m%s\033[0m' "$*"; }
c_yellow() { printf '\033[33m%s\033[0m' "$*"; }
c_bold()   { printf '\033[1m%s\033[0m' "$*"; }

step()  { printf '\n%s %s\n' "$(c_bold "==>")" "$(c_bold "$*")"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '    %s %s\n' "$(c_green "✓")" "$*"; }
warn()  { printf '    %s %s\n' "$(c_yellow "!")" "$*"; }
fail()  { printf '\n%s %s\n\n' "$(c_red "✗")" "$*" >&2; exit 1; }

# ---------- banner ----------
cat <<'BANNER'

  ╔═══════════════════════════════════════╗
  ║         PaperFetcher  installer       ║
  ║  arXiv → Claude → ElevenLabs/Edge TTS ║
  ║          → your phone, daily          ║
  ╚═══════════════════════════════════════╝

BANNER

# ---------- preflight ----------
step "Preflight checks"

if [[ "$(uname -s)" != "Linux" ]]; then
    fail "PaperFetcher installs on Linux only. See the Manual install in README.md."
fi

if ! command -v apt-get >/dev/null 2>&1; then
    fail "This installer needs apt (Ubuntu/Debian). For other distros, follow the Manual install in README.md."
fi

if [[ "$(id -u)" -eq 0 ]]; then
    fail "Run as your normal user, not root. The installer will sudo only when needed."
fi

if [[ -d "${INSTALL_DIR}" ]]; then
    fail "Install dir already exists at ${INSTALL_DIR}. Remove it (or 'cd ${INSTALL_DIR} && git pull') and re-run."
fi

ok "Linux + apt detected, running as ${USER}"

# ---------- system packages ----------
step "Installing system packages (sudo apt)"
# `apt-get update` is non-fatal here: a broken third-party PPA (Docker,
# lazygit, Spotify, ...) on the user's machine is a pre-existing problem,
# not a PaperFetcher problem. We only need our packages to install cleanly,
# which `apt-get install` will report on if anything's actually broken.
if ! sudo apt-get update -qq; then
    warn "apt-get update reported issues with some of your apt sources."
    warn "These are usually unrelated repos (Docker, expired PPAs, missing GPG keys)."
    warn "Continuing — if our packages won't install, the next step will say so."
fi
sudo apt-get install -y -qq \
    ffmpeg rclone jq libnotify-bin git curl ca-certificates
ok "ffmpeg, rclone, jq, libnotify-bin, git, curl"

# gum is in Charm's apt repo, not Debian's. Add the repo if needed.
if ! command -v gum >/dev/null 2>&1; then
    info "Installing gum from charm.sh apt repo..."
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://repo.charm.sh/apt/gpg.key \
        | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg
    echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" \
        | sudo tee /etc/apt/sources.list.d/charm.list >/dev/null
    sudo apt-get update -qq || warn "apt-get update reported issues — continuing"
    sudo apt-get install -y -qq gum
fi
ok "gum $(gum --version 2>/dev/null | head -1 || echo 'installed')"

# ---------- uv ----------
step "Installing uv (Python package manager)"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv installer puts it in ~/.local/bin
    export PATH="${HOME}/.local/bin:${PATH}"
fi
ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"

# ---------- claude code CLI check ----------
step "Verifying Claude Code CLI"
if ! command -v claude >/dev/null 2>&1; then
    cat <<EOF >&2

$(c_red "✗") Claude Code CLI is not installed.

  PaperFetcher needs the 'claude' CLI on a Claude Max subscription.

  1. Install it:    ${CLAUDE_DOCS}
  2. Authenticate:  claude login   (pick your Max-plan account)
  3. Re-run this installer.

EOF
    exit 1
fi
ok "claude $(claude --version 2>/dev/null | head -1)"

# ---------- clone ----------
step "Cloning PaperFetcher to ${INSTALL_DIR}"
mkdir -p "$(dirname "${INSTALL_DIR}")"
git clone --quiet "${REPO_URL}" "${INSTALL_DIR}"
cd "${INSTALL_DIR}"
ok "cloned at $(git -C "${INSTALL_DIR}" rev-parse --short HEAD)"

# ---------- python deps ----------
step "Installing Python dependencies (uv sync)"
uv sync --quiet
ok "Python env ready at .venv"

# ---------- hand off to wizard ----------
step "Launching configuration wizard"
echo
exec uv run python -m installer.setup_wizard
