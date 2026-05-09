#!/usr/bin/env bash
# PaperFetcher one-command installer for Ubuntu / Debian.
# Run via:
#   wget -qO- https://raw.githubusercontent.com/LucaFrat/PaperFetcher/main/install.sh | bash
set -e

# ---------- constants ----------
readonly REPO_URL="https://github.com/LucaFrat/PaperFetcher.git"
# Branch to clone. Override with PAPERFETCHER_BRANCH=<branch> for testing.
# Will switch to "main" once feat/easy-install is merged.
readonly BRANCH="${PAPERFETCHER_BRANCH:-feat/easy-install}"
readonly INSTALL_DIR="${HOME}/.local/share/paperfetcher"
readonly CLAUDE_DOCS="https://code.claude.com/docs"
readonly GUM_VERSION="0.14.3"

# ---------- banner ----------
cat <<'BANNER'

  ╔═══════════════════════════════════════╗
  ║         PaperFetcher  installer       ║
  ║  arXiv → Claude → ElevenLabs/Edge TTS ║
  ║          → your phone, daily          ║
  ╚═══════════════════════════════════════╝

BANNER

# ---------- friendly retry on failure ----------
trap '
  echo
  echo "✗ Installation failed. After fixing, re-run:"
  echo "    wget -qO- https://raw.githubusercontent.com/LucaFrat/PaperFetcher/${BRANCH}/install.sh | bash"
  echo
' ERR

# ---------- preflight ----------
if [[ "$(uname -s)" != "Linux" ]] || ! command -v apt-get >/dev/null 2>&1; then
    echo "✗ PaperFetcher installs on Ubuntu / Debian (apt). See README for manual install."
    exit 1
fi
if [[ "$(id -u)" -eq 0 ]]; then
    echo "✗ Run as your normal user, not root."
    exit 1
fi

echo "=> Begin installation (or abort with ctrl+c)..."

# Cache sudo credentials upfront so spinners aren't blocked by password prompts.
sudo -v

# Keep sudo timestamp warm in the background while we run.
( while true; do sudo -n true; sleep 60; kill -0 "$$" 2>/dev/null || exit; done ) &
readonly SUDO_KEEPALIVE_PID=$!
trap 'kill "${SUDO_KEEPALIVE_PID}" 2>/dev/null || true' EXIT

# ---------- system packages ----------
echo "Installing system packages..."
# All apt output suppressed. Pre-existing repo issues (broken PPAs, expired
# GPG keys, double-configured sources) are common and unrelated to us.
sudo apt-get update -y >/dev/null 2>&1 || true
sudo apt-get install -y \
    ffmpeg rclone jq libnotify-bin git curl ca-certificates \
    >/dev/null 2>&1

# ---------- gum (via .deb, faster than apt repo) ----------
if ! command -v gum >/dev/null 2>&1; then
    echo "Installing gum..."
    tmp_deb="$(mktemp --suffix=.deb)"
    wget -qO "${tmp_deb}" \
        "https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/gum_${GUM_VERSION}_amd64.deb"
    sudo apt-get install -y --allow-downgrades "${tmp_deb}" >/dev/null 2>&1
    rm -f "${tmp_deb}"
fi

# Helper for spinners (only available after gum installed).
spin() {
    local title="$1"
    shift
    gum spin --spinner dot --title "${title}" -- "$@"
}

# ---------- uv ----------
if ! command -v uv >/dev/null 2>&1; then
    spin "Installing uv..." bash -c \
        'curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1'
    export PATH="${HOME}/.local/bin:${PATH}"
fi

# ---------- Claude Code CLI check ----------
if ! command -v claude >/dev/null 2>&1; then
    cat <<EOF >&2

✗ Claude Code CLI is not installed.
  1. Install:       ${CLAUDE_DOCS}
  2. Authenticate:  claude login   (pick your Max-plan account)
  3. Re-run this installer.

EOF
    exit 1
fi

# ---------- clone (idempotent: rm -rf any prior install) ----------
mkdir -p "$(dirname "${INSTALL_DIR}")"
rm -rf "${INSTALL_DIR}"
spin "Cloning PaperFetcher (${BRANCH})..." \
    git clone --quiet --branch "${BRANCH}" "${REPO_URL}" "${INSTALL_DIR}"

# ---------- python env ----------
cd "${INSTALL_DIR}"
spin "Installing Python dependencies..." uv sync --quiet

# ---------- hand off to wizard ----------
echo
exec uv run python -m installer.setup_wizard
