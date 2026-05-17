#!/usr/bin/env bash
# Launch a Claude Code chat to interactively define the user's research
# interests, saving the result to config/interests.md. Invoked at the end of
# install.sh, and re-runnable any time:
#     bash ~/.local/share/paperfetcher/installer/onboard_interests.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INTERESTS_FILE="${REPO_ROOT}/config/interests.md"
SYS_PROMPT_FILE="${SCRIPT_DIR}/interests_system_prompt.md"

if ! command -v claude >/dev/null 2>&1; then
    echo "✗ claude CLI not found on PATH. Install Claude Code first:" >&2
    echo "    https://code.claude.com/docs" >&2
    exit 1
fi

if [[ ! -f "${SYS_PROMPT_FILE}" ]]; then
    echo "✗ system prompt missing: ${SYS_PROMPT_FILE}" >&2
    exit 1
fi

cat <<'BANNER'

  ╔════════════════════════════════════════════════════════════════╗
  ║  Final step — define your research interests with Claude       ║
  ╚════════════════════════════════════════════════════════════════╝

A Claude Code chat will open. Tell it what you work on, what methods you
care about, and what to filter out. It'll draft your interests in markdown
as you go.

When you're happy, ask Claude to save — it'll write to config/interests.md
(asking your permission once). Then type /exit to return here.

BANNER

read -rp "Press Enter to launch Claude... " _ || true

cd "${REPO_ROOT}"
# `|| true` so that a Ctrl+C or non-zero exit inside the chat doesn't abort
# the installer — we surface the real outcome by inspecting the file below.
claude \
    --append-system-prompt "$(cat "${SYS_PROMPT_FILE}")" \
    --add-dir "${REPO_ROOT}" \
    --name "PaperFetcher onboarding" \
    </dev/tty || true

# Treat as "saved" if the file has at least one alphabetic character beyond
# whitespace/comments — catches both empty files and stub-only files.
if [[ ! -s "${INTERESTS_FILE}" ]] || ! grep -q '[A-Za-z]' "${INTERESTS_FILE}"; then
    cat <<EOF >&2

⚠  config/interests.md is empty or missing.
   PaperFetcher's daily run will fail with "interests.md is empty" until
   you finish this step. To re-run the chat anytime:

       bash ${SCRIPT_DIR}/onboard_interests.sh

EOF
    exit 0
fi

echo
echo "✓ Saved your interests to ${INTERESTS_FILE}"
echo "  Re-run anytime to refine:  bash ${SCRIPT_DIR}/onboard_interests.sh"
echo
