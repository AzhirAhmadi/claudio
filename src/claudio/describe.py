"""Turn a Claude Code tool call into something worth hearing.

The generic permission notification says "Claude needs your permission to use
Edit" every single time, which carries no information. The PermissionRequest
hook, though, hands over `tool_name` and the full `tool_input`, so we can say
*which* file and *what* change instead.

`describe()` returns a Description: a set of named fields a user's template can
interpolate, plus a ready-made default phrase for when they have not written one.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

MAX_PHRASE = 180

# Filenames read far better without the extension, and with the word separators
# spoken as spaces: "invoice_repository_spec.rb" -> "invoice repository spec".
_KNOWN_EXTS = {
    ".rb", ".py", ".js", ".ts", ".tsx", ".jsx", ".haml", ".erb", ".yml", ".yaml",
    ".json", ".md", ".sql", ".sh", ".css", ".scss", ".html", ".toml", ".rs", ".go",
}


@dataclass
class Description:
    """Everything a template may reference, plus a sensible default sentence."""

    tool: str
    phrase: str
    fields: dict[str, str] = field(default_factory=dict)

    def as_template_vars(self) -> dict[str, str]:
        return {"tool": self.tool, "phrase": self.phrase, **self.fields}


def spoken_path(raw: str | None) -> str:
    """A file path as a human would say it out loud."""
    if not raw:
        return ""
    base = os.path.basename(str(raw).rstrip("/"))
    stem, ext = os.path.splitext(base)
    if ext.lower() in _KNOWN_EXTS:
        base = stem
    return re.sub(r"[_\-.]+", " ", base).strip() or str(raw)


def _clip(text: str, limit: int = MAX_PHRASE) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _first_code_line(blob: str | None) -> str:
    """The first line of a diff body that actually says something."""
    for line in str(blob or "").splitlines():
        stripped = line.strip()
        if len(stripped) > 3 and not stripped.startswith(("#", "//", "/*", "*")):
            return _clip(stripped, 70)
    return ""


def _shell_summary(command: str) -> tuple[str, str]:
    """(program, short spoken form) for a shell command."""
    command = re.sub(r"\s+", " ", str(command or "")).strip()
    if not command:
        return "", ""
    program = command.split()[0]
    if program in {"cd", "env", "sudo", "time"} and len(command.split()) > 1:
        program = command.split()[1]
    program = os.path.basename(program)
    head = " ".join(command.split()[:8])
    return program, _clip(head, 90)


def _mcp_parts(tool: str) -> tuple[str, str]:
    """mcp__analytics-db__run_query -> ('analytics db', 'run query')"""
    parts = tool.split("__")
    if len(parts) >= 3:
        server = re.sub(r"[_\-]+", " ", parts[1]).strip()
        name = re.sub(r"[_\-]+", " ", "__".join(parts[2:])).strip()
        return server, name
    return "", re.sub(r"[_\-]+", " ", tool)


def describe(tool: str, tool_input: dict | None) -> Description:
    """Build a Description for one tool call. Never raises on odd input."""
    data = tool_input if isinstance(tool_input, dict) else {}
    tool = str(tool or "tool")

    if tool.startswith("mcp__"):
        server, name = _mcp_parts(tool)
        where = f" on {server}" if server else ""
        return Description(tool, _clip(f"{name}{where}"),
                           {"server": server, "mcp_tool": name})

    handler = _HANDLERS.get(tool)
    if handler:
        return handler(tool, data)

    pretty = re.sub(r"(?<!^)(?=[A-Z])", " ", tool).lower()
    return Description(tool, _clip(f"use {pretty}"), {})


# --------------------------------------------------------------------------- #
# per-tool handlers
# --------------------------------------------------------------------------- #

def _edit(tool: str, data: dict) -> Description:
    name = spoken_path(data.get("file_path"))
    change = _first_code_line(data.get("new_string"))
    every = " everywhere" if data.get("replace_all") else ""
    phrase = f"edit {name}{every}"
    if change:
        phrase += f", changing {change}"
    return Description(tool, _clip(phrase),
                       {"file": name, "change": change,
                        "path": str(data.get("file_path") or "")})


def _write(tool: str, data: dict) -> Description:
    name = spoken_path(data.get("file_path"))
    lines = len(str(data.get("content") or "").splitlines())
    size = f", {lines} lines" if lines > 1 else ""
    return Description(tool, _clip(f"create {name}{size}"),
                       {"file": name, "lines": str(lines),
                        "path": str(data.get("file_path") or "")})


def _read(tool: str, data: dict) -> Description:
    name = spoken_path(data.get("file_path"))
    return Description(tool, _clip(f"read {name}"),
                       {"file": name, "path": str(data.get("file_path") or "")})


def _bash(tool: str, data: dict) -> Description:
    # Claude writes a human-readable `description` for every Bash call. It is
    # almost always the best thing to speak, so prefer it over the raw command.
    described = _clip(str(data.get("description") or ""), 120)
    program, head = _shell_summary(data.get("command"))
    background = " in the background" if data.get("run_in_background") else ""
    phrase = described or (f"run {head}" if head else "run a shell command")
    return Description(tool, _clip(phrase + background),
                       {"command": head, "program": program,
                        "description": described})


def _glob_grep(tool: str, data: dict) -> Description:
    pattern = _clip(str(data.get("pattern") or ""), 60)
    where = spoken_path(data.get("path"))
    scope = f" in {where}" if where else ""
    return Description(tool, _clip(f"search for {pattern}{scope}"),
                       {"pattern": pattern, "path": where})


def _web(tool: str, data: dict) -> Description:
    url = str(data.get("url") or "")
    domain = urlparse(url).netloc or url
    query = _clip(str(data.get("query") or data.get("prompt") or ""), 80)
    if domain:
        return Description(tool, _clip(f"fetch {domain}"),
                           {"domain": domain, "query": query, "url": url})
    return Description(tool, _clip(f"search the web for {query}"),
                       {"domain": "", "query": query, "url": ""})


def _task(tool: str, data: dict) -> Description:
    kind = re.sub(r"[_\-]+", " ", str(data.get("subagent_type") or "")).strip()
    what = _clip(str(data.get("description") or ""), 90)
    label = f"{kind} agent" if kind else "an agent"
    phrase = f"start {label}" + (f" to {what}" if what else "")
    return Description(tool, _clip(phrase),
                       {"agent_type": kind, "description": what})


def _notebook(tool: str, data: dict) -> Description:
    name = spoken_path(data.get("notebook_path"))
    return Description(tool, _clip(f"edit notebook {name}"), {"file": name})


_HANDLERS = {
    "Edit": _edit,
    "MultiEdit": _edit,
    "Write": _write,
    "Read": _read,
    "Bash": _bash,
    "BashOutput": _bash,
    "Glob": _glob_grep,
    "Grep": _glob_grep,
    "WebFetch": _web,
    "WebSearch": _web,
    "Task": _task,
    "Agent": _task,
    "NotebookEdit": _notebook,
}
