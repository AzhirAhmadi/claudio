"""Informed consent for the neural engine.

The neural voices are free and unauthenticated, which makes it tempting to just
switch them on. But they work by sending the text to be spoken to Microsoft, and
that text is drawn from the user's sessions. Nobody should discover that after
the fact.

So: `claudio setup` states exactly what would be sent, and asks. Accepting picks
the neural engine; declining picks the local one. Switching to the neural engine
later shows the same disclosure again. When there is no terminal to ask on, the
local engine wins by default - silence is never taken as agreement.
"""

from __future__ import annotations

import sys
import time

from .config import Config, set_value
from .hooks import read_state, write_state

LOCAL = "say"
NEURAL = "edge"

# Everything below is derived from what engines._speak_edge actually transmits:
# the composed announcement sentence, nothing else.
SENT = [
    "The session name - your Claude Code session title, or the folder name.",
    "File names from tool calls, e.g. \"invoice policy\" for invoice_policy.rb.",
    "One line of the code being changed, taken from the edit itself.",
    "The description Claude writes for a shell command, or its first few words.",
    "Domains from web fetches, and the names of MCP servers and their tools.",
    "One sentence of Claude's last message - usually the question it is asking.",
    "The voice name and speaking rate, plus your IP address, as with any request.",
]

NOT_SENT = [
    "File contents, beyond the single changed line described above.",
    "Whole conversations, whole commands, or anything you type.",
    "Any account, licence key or identifier - the endpoint is unauthenticated.",
]

DISCLAIMER = """\
────────────────────────────────────────────────────────────────────────────
  Choose a voice engine
────────────────────────────────────────────────────────────────────────────

  claudio can speak with either engine. What it TELLS you is identical:
  which session needs you, and what it actually wants - the file being
  edited, the command being run, the question being asked. That is the
  point of the tool and you get it either way.

  The only difference is how natural the voice sounds.

  1) neural  - Microsoft Edge TTS. Clearly better voices. Free, no account.
               Needs the network, and SENDS TEXT TO MICROSOFT (see below).
  2) local   - macOS say(1). Nothing leaves your Mac, works offline.
               Stock voices are robotic; a free Premium voice fixes that
               (claudio will tell you how).

  Choosing "neural" means this is sent to Microsoft's Edge TTS endpoint
  every time claudio speaks:

{sent}

  Not sent:

{not_sent}

  Microsoft's handling of it is governed by their terms, not by claudio.
  claudio itself stores nothing and transmits nothing else.

  If you use Claude Code on a private, employer-owned or client codebase,
  note that a session title plus a file name can be enough to disclose
  something you are not permitted to disclose. When in doubt, choose local.

  You can change this at any time:  claudio engine neural | local
────────────────────────────────────────────────────────────────────────────"""


def disclaimer() -> str:
    sent = "\n".join(f"    - {line}" for line in SENT)
    not_sent = "\n".join(f"    - {line}" for line in NOT_SENT)
    return DISCLAIMER.format(sent=sent, not_sent=not_sent)


def normalise(name: str | None) -> str | None:
    """Accept the friendly names as well as the config values."""
    value = str(name or "").strip().lower()
    if value in {"neural", "edge", "edge-tts", "microsoft", "1"}:
        return NEURAL
    if value in {"local", "say", "macos", "offline", "2"}:
        return LOCAL
    return None


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def ask(default_local: bool = True) -> tuple[str, bool]:
    """Show the disclaimer and ask. Returns (engine, asked_interactively)."""
    print(disclaimer())
    if not interactive():
        print("\n  No terminal to ask on, so choosing the private option: local.")
        print("  To use the neural voices instead, run:  claudio engine neural\n")
        return LOCAL, False

    while True:
        try:
            reply = input("\n  Send text to Microsoft for better voices? [y/N] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled - choosing local.\n")
            return LOCAL, False
        if reply == "" or reply.lower() in {"n", "no", "2", "local"}:
            print("\n  Local engine selected. Nothing will leave your Mac.\n")
            return LOCAL, True
        if reply.lower() in {"y", "yes", "1", "neural"}:
            print("\n  Neural engine selected. You accepted the disclosure above.\n")
            return NEURAL, True
        print("  Please answer y or n.")

    # unreachable
    return LOCAL, False


def record(cfg: Config, engine: str, accepted: bool) -> Config:
    """Persist the choice, and when it was made.

    The engine is a setting, so it goes in config.toml - edited in place so the
    template's documentation survives. The acceptance itself is not a setting,
    so it goes in state.json where hand-editing config cannot forge it.
    """
    set_value("speech", "engine", engine)
    state = read_state()
    if engine == NEURAL and accepted:
        state["neural_consent"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        state.pop("neural_consent", None)
    write_state(state)
    cfg.speech["engine"] = engine
    return cfg


def consented(cfg: Config | None = None) -> bool:
    return bool(read_state().get("neural_consent"))


def needs_disclosure(cfg: Config) -> bool:
    """Neural engine in use with no recorded acceptance - e.g. hand-edited config."""
    return str(cfg.get("speech", "engine")).lower() == NEURAL and not consented(cfg)


def switch_summary(engine: str) -> str:
    if engine == NEURAL:
        return ("engine = neural (Microsoft Edge TTS)\n"
                "  Spoken text now leaves your Mac. Revert with: claudio engine local")
    return ("engine = local (macOS say)\n"
            "  Nothing leaves your Mac. Stock voices are robotic - see "
            "`claudio demo --local`\n  for how to install a free Premium voice.")
