#!/bin/sh
# claudio installer - spoken notifications for Claude Code on macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/AzhirAhmadi/claudio/main/install.sh | sh
#
# Installs whatever is missing (Homebrew tap, or uv), then runs `claudio setup`.
# Safe to re-run: every step is idempotent.

set -eu

REPO="AzhirAhmadi/claudio"
TAP="AzhirAhmadi/claudio"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
fail() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "claudio is macOS only (it speaks through say and afplay)."

for tool in say afplay osascript; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is missing; this does not look like a working macOS."
done

say "Installing claudio"

if command -v brew >/dev/null 2>&1; then
  info "using Homebrew"
  brew tap "$TAP" "https://github.com/$REPO" 2>/dev/null || true
  brew install claudio || brew upgrade claudio
else
  info "Homebrew not found; using uv"
  if ! command -v uv >/dev/null 2>&1; then
    info "installing uv"
    curl -fsSL https://astral.sh/uv/install.sh | sh
    for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
      [ -d "$candidate" ] && PATH="$candidate:$PATH"
    done
    export PATH
  fi
  command -v uv >/dev/null 2>&1 || fail "uv install failed; see https://docs.astral.sh/uv/"
  uv tool install --force "git+https://github.com/$REPO"
fi

if ! command -v claudio >/dev/null 2>&1; then
  for candidate in "$HOME/.local/bin" /opt/homebrew/bin /usr/local/bin; do
    if [ -x "$candidate/claudio" ]; then
      PATH="$candidate:$PATH"
      export PATH
      break
    fi
  done
fi
command -v claudio >/dev/null 2>&1 || fail "claudio installed but is not on PATH; add ~/.local/bin to PATH and re-run."

say "Setting up"
# Piped through `curl | sh`, stdin is the script itself, so setup could not ask
# which voice engine to use and would silently take the private default.
# Reattach the real terminal when there is one.
if [ -r /dev/tty ]; then
  claudio setup < /dev/tty || fail "setup failed; run 'claudio doctor' for detail."
else
  info "no terminal available; defaulting to the local voice engine"
  info "to review the neural option later, run: claudio engine neural"
  claudio setup --engine local || fail "setup failed; run 'claudio doctor' for detail."
fi

say "Done"
info "Restart Claude Code so it loads the hooks."
info "Then try:  claudio demo"
