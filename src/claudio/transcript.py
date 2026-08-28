"""Reading the bits of a Claude Code transcript we need.

Transcripts are JSON Lines. They can reach tens of megabytes, so every reader
here streams and keeps only the last match rather than parsing the whole file
into memory.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import time
from pathlib import Path

_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS = re.compile(r"[*_#>]+")
_BULLET = re.compile(r"^\s*[-*+]\s+|^\s*\d+\.\s+", re.M)
_URL = re.compile(r"https?://\S+")


def plain(text: str | None) -> str:
    """Markdown prose reduced to something a voice can read."""
    out = _FENCE.sub(" ", text or "")
    out = _LINK.sub(r"\1", out)
    out = _INLINE_CODE.sub(r"\1", out)
    out = _BULLET.sub("", out)
    out = _EMPHASIS.sub("", out)
    out = _URL.sub("a link", out)
    return re.sub(r"\s+", " ", out).strip()


def headline(text: str | None, limit: int = 220) -> str:
    """The one sentence worth interrupting somebody for."""
    body = plain(text)
    if not body:
        return ""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    for sentence in reversed(sentences[-4:]):
        if sentence.endswith("?"):
            return sentence[:limit]
    return (sentences[0] if sentences else body)[:limit]


def _iter_records(path: str | os.PathLike, needle: str):
    """Yield parsed records whose raw line contains `needle` (a cheap prefilter)."""
    try:
        with open(path, errors="replace") as handle:
            for line in handle:
                if needle not in line:
                    continue
                try:
                    yield json.loads(line)
                except (ValueError, TypeError):
                    continue
    except OSError:
        return


def last_assistant_text(path: str | os.PathLike | None) -> str:
    """Final assistant prose in the main thread; subagent output is ignored."""
    if not path or not Path(path).exists():
        return ""
    found = ""
    for record in _iter_records(path, '"assistant"'):
        if record.get("type") != "assistant" or record.get("isSidechain"):
            continue
        for block in (record.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = (block.get("text") or "").strip()
                if text:
                    found = text
    return found


def session_title(path: str | os.PathLike | None) -> str | None:
    """The title the session set for itself, else the auto-generated one.

    A manual title never reaches ~/.claude/sessions/<pid>.json - that keeps
    reporting `nameSource: "derived"` - so the transcript is the only record of
    what the user actually sees in the sidebar.
    """
    if not path or not Path(path).exists():
        return None
    ai_title = None
    explicit = None
    for record in _iter_records(path, '"title"'):
        if record.get("type") == "ai-title" and record.get("aiTitle"):
            ai_title = record["aiTitle"]
            continue
        for block in (record.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if not str(block.get("name", "")).endswith("set_session_title"):
                continue
            title = (block.get("input") or {}).get("title")
            if title:
                explicit = title
    if explicit or ai_title:
        return explicit or ai_title
    for record in _iter_records(path, '"aiTitle"'):
        if record.get("aiTitle"):
            ai_title = record["aiTitle"]
    return ai_title


def seconds_since_last_user_message(path: str | os.PathLike | None) -> float | None:
    """How long the current turn has been running, or None if unknowable."""
    if not path or not Path(path).exists():
        return None
    latest = None
    for record in _iter_records(path, '"user"'):
        if (record.get("type") == "user" and not record.get("isSidechain")
                and record.get("timestamp")):
            latest = record["timestamp"]
    if not latest:
        return None
    try:
        started = calendar.timegm(time.strptime(str(latest)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None
    return max(0.0, time.time() - started)
