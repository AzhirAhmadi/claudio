"""Everything `claudio setup` and `claudio doctor` need.

Setup is idempotent: run it as often as you like. It only ever adds claudio's
own hook entries and never rewrites anyone else's.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import engines
from .config import config_path, write_template

HOOK_EVENTS = ("PermissionRequest", "Notification", "Stop")
COMMAND_SUFFIX = "hook"


SETTINGS = Path.home() / ".claude" / "settings.json"


def settings_file() -> Path:
    """Claude Code's user settings. CLAUDIO_SETTINGS overrides it for testing."""
    override = os.environ.get("CLAUDIO_SETTINGS")
    return Path(override) if override else SETTINGS


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str | None = None
    optional: bool = False

    def render(self) -> str:
        mark = "ok  " if self.ok else ("note" if self.optional else "FAIL")
        line = f"[{mark}] {self.name}: {self.detail}"
        if not self.ok and self.fix:
            label = "optional" if self.optional else "fix"
            line += f"\n         {label}: {self.fix}"
        return line


def claudio_command() -> str:
    binary = shutil.which("claudio") or str(Path.home() / ".local" / "bin" / "claudio")
    return f"{binary} {COMMAND_SUFFIX}"


def _load_settings() -> dict:
    if not settings_file().exists():
        return {}
    try:
        return json.loads(settings_file().read_text())
    except (OSError, ValueError):
        return {}


def _entry_commands(entries: list) -> list[str]:
    found = []
    for entry in entries or []:
        for hook in (entry or {}).get("hooks", []) or []:
            if isinstance(hook, dict) and hook.get("command"):
                found.append(str(hook["command"]))
    return found


def hooks_installed() -> dict[str, bool]:
    settings = _load_settings()
    hooks = settings.get("hooks") or {}
    state = {}
    for event in HOOK_EVENTS:
        commands = _entry_commands(hooks.get(event, []))
        state[event] = any(COMMAND_SUFFIX in cmd and "claudio" in cmd for cmd in commands)
    return state


def install_hooks() -> list[str]:
    """Add claudio to settings.json. Returns the events newly wired."""
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    command = claudio_command()
    added = []
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        existing = _entry_commands(entries)
        if any(COMMAND_SUFFIX in cmd and "claudio" in cmd for cmd in existing):
            continue
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
        added.append(event)
    if added:
        settings_file().parent.mkdir(parents=True, exist_ok=True)
        if settings_file().exists():
            shutil.copy2(settings_file(), settings_file().with_suffix(".json.claudio-backup"))
        tmp = settings_file().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n")
        tmp.replace(settings_file())
    return added


def uninstall_hooks() -> list[str]:
    settings = _load_settings()
    hooks = settings.get("hooks") or {}
    removed = []
    for event in HOOK_EVENTS:
        entries = hooks.get(event)
        if not entries:
            continue
        kept = []
        for entry in entries:
            inner = [h for h in (entry or {}).get("hooks", []) or []
                     if not (COMMAND_SUFFIX in str(h.get("command", ""))
                             and "claudio" in str(h.get("command", "")))]
            if inner:
                kept.append({**entry, "hooks": inner})
            elif (entry or {}).get("hooks"):
                removed.append(event)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if removed:
        tmp = settings_file().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings, indent=2) + "\n")
        tmp.replace(settings_file())
    return removed


def run_checks() -> list[Check]:
    checks: list[Check] = []

    is_mac = platform.system() == "Darwin"
    checks.append(Check("platform", is_mac, platform.platform(),
                        "claudio speaks through macOS say(1) and afplay; it is macOS only"))

    for binary in ("say", "afplay", "osascript"):
        found = shutil.which(binary)
        checks.append(Check(binary, bool(found), found or "not found",
                            "part of macOS; a missing one means a broken install"))

    cli = engines._edge_cli()
    checks.append(Check("edge-tts", bool(cli),
                        " ".join(cli) if cli else "not available",
                        "brew reinstall claudio, or: uv tool install edge-tts"))

    path = config_path()
    checks.append(Check("config", path.exists(), str(path),
                        "claudio setup"))

    installed = hooks_installed()
    for event, ok in installed.items():
        checks.append(Check(f"hook {event}", ok,
                            "wired" if ok else "not wired",
                            "claudio setup"))

    from . import config as configmod
    from . import consent

    cfg = configmod.load()
    engine = str(cfg.get("speech", "engine")).lower()
    if engine == consent.NEURAL:
        checks.append(Check("engine", consent.consented(cfg),
                            "neural - spoken text is sent to Microsoft"
                            + ("" if consent.consented(cfg) else ", NOT yet disclosed"),
                            "config says neural but no acceptance is recorded (hand-edited?). "
                            "Run `claudio engine neural` to see what is sent and confirm, "
                            "or `claudio engine local` to keep everything on this Mac."))
    else:
        checks.append(Check("engine", True, "local - nothing leaves this Mac"))

    premium = engines.premium_local_voices()
    checks.append(Check("local premium voices", bool(premium),
                        ", ".join(premium) if premium else
                        "none installed (only the robotic compact voices)",
                        "System Settings > Accessibility > Read & Speak > System voice "
                        "> Manage Voices > download a (Premium) voice. Only matters if "
                        'you set engine = "say".',
                        optional=True))

    return checks


def doctor() -> tuple[list[Check], bool]:
    """All checks, plus whether every *required* one passed."""
    checks = run_checks()
    return checks, all(c.ok for c in checks if not c.optional)


def setup(force_config: bool = False, engine: str | None = None) -> list[str]:
    """Write the config, choose an engine with consent, and wire the hooks.

    `engine` skips the interactive question - used by --engine for unattended
    installs. Anything else asks, and declining always yields the local engine.
    """
    from . import config as configmod
    from . import consent

    notes = []
    path, created = write_template(force=force_config)
    notes.append(f"{'wrote' if created else 'kept existing'} config at {path}")

    cfg = configmod.load()
    if engine:
        chosen, accepted = engine, True
        print(consent.disclaimer())
        print(f"\n  --engine {engine} given on the command line; not asking.\n")
    elif created or consent.needs_disclosure(cfg):
        chosen, accepted = consent.ask()
    else:
        chosen, accepted = str(cfg.get("speech", "engine")), consent.consented(cfg)
        notes.append(f"kept engine = {chosen}")

    consent.record(configmod.load(), chosen, accepted)
    if chosen != cfg.speech.get("engine") or created or engine:
        notes.append(consent.switch_summary(chosen))

    added = install_hooks()
    notes.append(f"wired hooks: {', '.join(added)}" if added else "hooks already wired")
    return notes
