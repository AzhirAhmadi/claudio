"""Turning a Claude Code hook payload into one spoken sentence."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import transcript
from .config import Config, state_path
from .describe import describe

# A manual title like "3-1042 login timeout" sorts nicely in the sidebar but
# reads terribly out loud, so the leading key is dropped before speaking.
KEY_PREFIX = re.compile(r"^\d-(\d{4}|\?{4})\s+")
WORKTREE_HASH = re.compile(r"-[0-9a-f]{6}$")

# PermissionRequest carries tool_name/tool_input and fires first; the generic
# Notification for the same prompt arrives right behind it with nothing useful.
PERMISSION_SUPPRESS_SECONDS = 20


@dataclass
class Announcement:
    text: str
    label: str
    kind: str

    def __bool__(self) -> bool:
        return bool(self.text)


def read_state() -> dict:
    try:
        return json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {}


def write_state(data: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def label_from_cwd(cwd: str | None) -> str:
    base = os.path.basename(str(cwd or "").rstrip("/")) or "claude"
    return re.sub(r"[_\-]+", " ", WORKTREE_HASH.sub("", base)).strip()


def session_label(payload: dict) -> str:
    title = transcript.session_title(payload.get("transcript_path"))
    return (title or label_from_cwd(payload.get("cwd")) or "claude")[:80]


def speakable_label(label: str, strip_key: bool = True) -> str:
    if strip_key:
        return (KEY_PREFIX.sub("", label).strip() or label)
    return label


def render(template: str, variables: dict[str, str]) -> str:
    """Interpolate {name} placeholders, leaving unknown ones as literal text."""
    def swap(match: re.Match) -> str:
        return variables.get(match.group(1), match.group(0))

    return re.sub(r"\{(\w+)\}", swap, template)


def _join(label: str, phrase: str, speak_name: bool) -> str:
    phrase = phrase.strip()
    if not speak_name or not label:
        return phrase
    return f"{label}: {phrase}" if phrase else label


def build(payload: dict, cfg: Config) -> Announcement | None:
    """The whole decision: what, if anything, should be said for this event."""
    if not isinstance(payload, dict) or payload.get("agent_id"):
        return None

    event = payload.get("hook_event_name")
    label = session_label(payload)
    spoken = speakable_label(label, bool(cfg.get("session", "strip_key_prefix")))
    speak_name = bool(cfg.get("session", "speak_name"))
    limit = int(cfg.get("notify", "max_chars"))

    if event == "PermissionRequest":
        if not cfg.get("notify", "permission"):
            return None
        return _permission(payload, cfg, label, spoken, speak_name, limit)

    if event == "Notification":
        kind = str(payload.get("notification_type") or "")
        if kind == "permission_prompt":
            # PermissionRequest already said something richer.
            since = time.time() - float(read_state().get("last_permission_at", 0))
            if since < PERMISSION_SUPPRESS_SECONDS:
                return None
            if not cfg.get("notify", "permission"):
                return None
            body = transcript.plain(payload.get("message") or "needs your permission")
            return Announcement(_join(spoken, body[:limit], speak_name), label, "permission")
        if not cfg.get("notify", "idle"):
            return None
        question = transcript.headline(
            transcript.last_assistant_text(payload.get("transcript_path")), limit)
        body = question or transcript.plain(payload.get("message") or "")
        text = _join(spoken, f"is waiting. {body}".strip(), speak_name)
        return Announcement(text[:limit + 120], label, "idle")

    if event == "Stop":
        if not cfg.get("notify", "turn_end") or payload.get("stop_hook_active"):
            return None
        threshold = float(cfg.get("notify", "min_turn_seconds"))
        elapsed = transcript.seconds_since_last_user_message(payload.get("transcript_path"))
        if threshold > 0 and elapsed is not None and elapsed < threshold:
            return None
        question = transcript.headline(
            payload.get("last_assistant_message")
            or transcript.last_assistant_text(payload.get("transcript_path")), limit)
        if not question:
            return None
        return Announcement(_join(spoken, question, speak_name), label, "turn_end")

    return None


def _permission(payload: dict, cfg: Config, label: str, spoken: str,
                speak_name: bool, limit: int) -> Announcement | None:
    tool = str(payload.get("tool_name") or "")
    description = describe(tool, payload.get("tool_input"))

    rule = cfg.rule_for(tool)
    if rule and rule.skip:
        return None

    variables = {"session": spoken, **description.as_template_vars()}
    if rule and rule.say:
        body = render(rule.say, variables).strip()
        text = body  # an explicit template owns the whole sentence
    else:
        text = _join(spoken, f"wants to {description.phrase}", speak_name)

    state = read_state()
    state["last_permission_at"] = time.time()
    write_state(state)
    return Announcement(re.sub(r"\s+", " ", text).strip()[:limit + 120], label, "permission")


def muted(cfg: Config) -> str | None:
    """Reason speech is suppressed right now, or None."""
    state = read_state()
    if state.get("disabled"):
        return "off"
    until = float(state.get("muted_until") or 0)
    if time.time() < until:
        left = int(until - time.time())
        if left > 86400 * 365:
            return "muted indefinitely"
        if left < 3600:
            return f"muted {max(1, left // 60)}m"
        return f"muted {left // 3600}h{(left % 3600) // 60:02d}m"
    return None


def set_mute(until: float | None = None, disabled: bool | None = None) -> None:
    state = read_state()
    if until is not None:
        state["muted_until"] = until
    if disabled is not None:
        state["disabled"] = disabled
    write_state(state)


def already_said(text: str, window: float) -> bool:
    state = read_state()
    now = time.time()
    if state.get("last_text") == text and now - float(state.get("last_at", 0)) < window:
        return True
    state["last_text"] = text
    state["last_at"] = now
    write_state(state)
    return False


def transcript_for_cwd(cwd: str) -> Path | None:
    """Newest transcript for a directory - used by `claudio replay`."""
    slug = str(cwd).replace("/", "-")
    folder = Path.home() / ".claude" / "projects" / slug
    if not folder.is_dir():
        return None
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None
