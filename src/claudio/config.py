"""Configuration: a documented TOML file with working defaults."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

APP = "claudio"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP


def config_path() -> Path:
    return Path(os.environ.get("CLAUDIO_CONFIG") or config_dir() / "config.toml")


def state_path() -> Path:
    """Runtime state. Overridable so a test can never touch the real record."""
    override = os.environ.get("CLAUDIO_STATE")
    return Path(override) if override else config_dir() / "state.json"


def cache_dir() -> Path:
    path = config_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


DEFAULTS: dict[str, Any] = {
    "speech": {
        "engine": "edge",
        "voice": "en-US-AvaMultilingualNeural",
        "fallback_voice": "Samantha",
        "rate": 190,
        "volume": 0.6,
    },
    "notify": {
        "banner": True,
        "permission": True,
        "idle": True,
        "turn_end": True,
        "min_turn_seconds": 45,
        "skip_turn_end_when_focused": True,
        "max_chars": 220,
        "dedupe_seconds": 8,
    },
    "session": {
        "speak_name": True,
        "strip_key_prefix": True,
    },
}

TEMPLATE = """# claudio - spoken notifications for Claude Code
# Every value here is optional; delete a line to fall back to the default.
# Docs: https://github.com/AzhirAhmadi/claudio

[speech]
engine = "edge"                            # neural, needs network; see `claudio engine`
                                           # "say" = local only, nothing leaves this Mac
voice = "en-US-AvaMultilingualNeural"      # claudio voices en-
fallback_voice = "Samantha"                # local voice used when edge is unreachable
rate = 190                                 # words per minute
volume = 0.6

[notify]
banner = true                              # also post a macOS notification banner
permission = true                          # speak permission requests
idle = true                                # speak when a session sits waiting for you
turn_end = true                            # speak when a long turn finishes
min_turn_seconds = 45                      # below this, assume you were watching
skip_turn_end_when_focused = true          # stay quiet if Claude is the front app

[session]
speak_name = true                          # lead with the session name
strip_key_prefix = true                    # drop a "2-1994 " sorting key before speaking

# ---------------------------------------------------------------------------
# Rules: control what a permission request actually says.
#
# Without a rule, claudio already says what the tool is doing - "edit
# invoice policy, changing validates :amount" instead of the
# useless "needs your permission to use Edit".
#
# Add a rule to reword it, or to stay silent for noisy tools.
#   tool  - exact tool name, or a glob: "mcp__*", "Web*"
#   say   - template; {session} {tool} {phrase} plus the tool's own fields
#   skip  - true to never speak this tool
#
# Fields per tool:
#   Edit/Write/Read  {file} {path} {change} {lines}
#   Bash             {description} {command} {program}
#   Grep/Glob        {pattern} {path}
#   WebFetch/Search  {domain} {query} {url}
#   Task             {agent_type} {description}
#   mcp__*           {server} {mcp_tool}
# ---------------------------------------------------------------------------

[[rule]]
tool = "Read"
skip = true                                # reading files is rarely worth interrupting you

# Claude's own {description} is already an imperative phrase ("Run the pending
# migrations"), so do not prefix it with another verb or it stutters.
[[rule]]
tool = "Bash"
say = "{session}: {description}"

[[rule]]
tool = "Edit"
say = "{session}: {phrase}"

# ---------------------------------------------------------------------------
# Pronunciation: respell words the voice mangles.
#
# The neural "Multilingual" voices take no language parameter - they guess the
# language of each word from its spelling, so an isolated German noun in an
# English sentence can be detected as French and spoken that way. There is no
# way to tell the endpoint otherwise (edge-tts escapes the text and fixes
# xml:lang to en-US), but we can change the spelling before sending it.
#
# Left side: the word as it appears. Right side: how to say it.
# Matching is whole-word and case-insensitive. Only speech is affected - the
# notification banner still shows the real word.
#
# Check what fires:  claudio pronounce "your text here"
# ---------------------------------------------------------------------------

[pronounce]
# Bestellung = "Be-shtell-ung"
# Rechnung = "Rekh-nung"
"""


@dataclass
class Rule:
    tool: str = "*"
    say: str | None = None
    skip: bool = False

    def matches(self, tool: str) -> bool:
        from fnmatch import fnmatch

        return fnmatch(tool, self.tool)


@dataclass
class Config:
    speech: dict[str, Any] = field(default_factory=dict)
    notify: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    rules: list[Rule] = field(default_factory=list)
    pronounce: dict[str, str] = field(default_factory=dict)
    path: Path | None = None

    def get(self, section: str, key: str) -> Any:
        table = getattr(self, section, {})
        if key in table:
            return table[key]
        return DEFAULTS[section][key]

    def rule_for(self, tool: str) -> Rule | None:
        for rule in self.rules:
            if rule.matches(tool):
                return rule
        return None

    def to_toml(self) -> str:
        payload = {
            "speech": {**DEFAULTS["speech"], **self.speech},
            "notify": {**DEFAULTS["notify"], **self.notify},
            "session": {**DEFAULTS["session"], **self.session},
        }
        if self.pronounce:
            payload["pronounce"] = dict(self.pronounce)
        if self.rules:
            payload["rule"] = [
                {k: v for k, v in
                 {"tool": r.tool, "say": r.say, "skip": r.skip}.items()
                 if v not in (None, False)}
                for r in self.rules
            ]
        return tomli_w.dumps(payload)


def load(path: Path | None = None) -> Config:
    target = path or config_path()
    raw: dict[str, Any] = {}
    if target.exists():
        try:
            raw = tomllib.loads(target.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            raw = {}
    rules = [
        Rule(tool=str(entry.get("tool", "*")),
             say=entry.get("say"),
             skip=bool(entry.get("skip", False)))
        for entry in raw.get("rule", []) or []
        if isinstance(entry, dict)
    ]
    pronounce = {
        str(word): str(spoken)
        for word, spoken in (raw.get("pronounce", {}) or {}).items()
        if str(word).strip()
    }
    return Config(
        speech=raw.get("speech", {}) or {},
        notify=raw.get("notify", {}) or {},
        session=raw.get("session", {}) or {},
        rules=rules,
        pronounce=pronounce,
        path=target,
    )


def save(cfg: Config) -> Path:
    target = cfg.path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(cfg.to_toml())
    tmp.replace(target)
    return target


def set_value(section: str, key: str, value: object,
              path: Path | None = None) -> Path:
    """Change one key in place, preserving comments and layout.

    `save()` regenerates the whole file from data and would strip the
    documentation out of the template, so every targeted edit goes through here
    instead.
    """
    target = path or config_path()
    if not target.exists():
        write_template()
    lines = target.read_text().splitlines()

    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, (int, float)):
        rendered = str(value)
    else:
        rendered = tomli_w.dumps({key: str(value)}).split("=", 1)[1].strip()

    header = re.compile(rf"^\s*\[{re.escape(section)}\]\s*$")
    assignment = re.compile(rf"^(\s*){re.escape(key)}(\s*)=\s*[^#]*(#.*)?$")

    inside = False
    section_end = None
    for index, line in enumerate(lines):
        if header.match(line):
            inside = True
            section_end = index + 1
            continue
        if inside:
            if re.match(r"^\s*\[", line):
                inside = False
                continue
            match = assignment.match(line)
            if match:
                comment = f"  {match.group(3)}" if match.group(3) else ""
                lines[index] = f"{match.group(1)}{key} = {rendered}{comment}"
                target.write_text("\n".join(lines) + "\n")
                return target
            if line.strip():
                section_end = index + 1

    if section_end is None:
        lines += ["", f"[{section}]", f"{key} = {rendered}"]
    else:
        lines.insert(section_end, f"{key} = {rendered}")
    target.write_text("\n".join(lines) + "\n")
    return target


def write_template(force: bool = False) -> tuple[Path, bool]:
    """Drop the documented starter config in place. Returns (path, created)."""
    target = config_path()
    if target.exists() and not force:
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(TEMPLATE)
    return target, True
