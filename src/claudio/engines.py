"""Speaking, and the banner that accompanies it.

Two engines. `say` is macOS's built-in synthesiser: instant, offline, robotic.
`edge` uses Microsoft's neural voices through the bundled edge-tts, which sounds
far better but needs the network - so it always degrades to `say` rather than
falling silent.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, cache_dir

BANNER_TIMEOUT = 5


def _clamp_volume(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.6


def banner(title: str, message: str) -> None:
    """A macOS notification, so a muted announcement still leaves a trace."""
    def esc(text: str) -> str:
        return json.dumps(text)[1:-1].replace("\\", "\\\\")

    script = f'display notification "{esc(message)}" with title "{esc(title)}"'
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=BANNER_TIMEOUT, check=False)


def say_argv(cfg: Config, text: str, voice: str | None = None) -> list[str]:
    volume = _clamp_volume(cfg.get("speech", "volume"))
    chosen = voice or str(cfg.get("speech", "fallback_voice"))
    return ["say", "-v", chosen, "-r", str(int(cfg.get("speech", "rate"))),
            f"[[volm {volume:.2f}]] {text}"]


def edge_rate_percent(rate: int, baseline: int = 175) -> str:
    """edge-tts wants a relative rate like '+9%'."""
    delta = round((int(rate) - baseline) / baseline * 100)
    return f"{'+' if delta >= 0 else '-'}{abs(delta)}%"


def _edge_cli() -> list[str] | None:
    """How to invoke edge-tts: bundled console script, our own interpreter, or uvx."""
    script = shutil.which("edge-tts")
    if script:
        return [script]
    try:
        import edge_tts  # noqa: F401
        return [sys.executable, "-m", "edge_tts"]
    except ImportError:
        pass
    uvx = shutil.which("uvx")
    return [uvx, "--quiet", "edge-tts"] if uvx else None


def speak(cfg: Config, text: str) -> str:
    """Start speaking and return the engine actually used. Never blocks on audio."""
    engine = str(cfg.get("speech", "engine")).lower()
    if engine == "edge" and _speak_edge(cfg, text):
        return "edge"
    _speak_say(cfg, text)
    return "say"


def _speak_say(cfg: Config, text: str) -> None:
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.Popen(say_argv(cfg, text),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _speak_edge(cfg: Config, text: str) -> bool:
    cli = _edge_cli()
    if not cli:
        return False
    out = str(cache_dir() / "last.mp3")
    volume = _clamp_volume(cfg.get("speech", "volume"))
    rate = edge_rate_percent(int(cfg.get("speech", "rate")))

    # `exec afplay` replaces the shell on success, so the say(1) line below is
    # reached only when synthesis failed - offline, DNS down, bad voice name.
    quoted = " ".join(f"'{part}'" for part in cli)
    fallback = " ".join(f"'{part}'" for part in
                        say_argv(cfg, "$3", str(cfg.get("speech", "fallback_voice"))))
    script = (
        f'{quoted} --voice "$1" --rate "$2" --text "$3" --write-media "$4" '
        f'>/dev/null 2>&1 && [ -s "$4" ] && exec afplay -v "$5" "$4"\n'
        f'exec {fallback}'
    )
    try:
        subprocess.Popen(
            ["/bin/sh", "-c", script, "sh",
             str(cfg.get("speech", "voice")), rate, text, out, f"{volume:.2f}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def synthesise_to_file(cfg: Config, text: str, voice: str, dest: Path,
                       timeout: int = 60) -> bool:
    """Blocking synthesis, used by `claudio demo`."""
    cli = _edge_cli()
    if not cli:
        return False
    rate = edge_rate_percent(int(cfg.get("speech", "rate")))
    try:
        subprocess.run([*cli, "--voice", voice, "--rate", rate,
                        "--text", text, "--write-media", str(dest)],
                       capture_output=True, timeout=timeout, check=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return dest.exists() and dest.stat().st_size > 0


def play(path: Path, volume: float = 0.6) -> None:
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["afplay", "-v", f"{_clamp_volume(volume):.2f}", str(path)],
                       capture_output=True, check=False)


def frontmost_app() -> str:
    script = ('tell application "System Events" to get name of first process '
              'whose frontmost is true')
    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def claude_is_focused() -> bool:
    return "claude" in frontmost_app().lower()


def local_voices() -> list[tuple[str, str]]:
    """(name, locale) for every installed say(1) voice."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                             timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():
        parts = line.split("#", 1)[0].rstrip()
        if not parts:
            continue
        tokens = parts.split()
        if len(tokens) < 2:
            continue
        locale = tokens[-1]
        name = " ".join(tokens[:-1]).strip()
        if "_" in locale and name:
            found.append((name, locale))
    return found


def premium_local_voices(languages: tuple[str, ...] = ("en", "de")) -> list[str]:
    """Installed Premium/Enhanced voices, best tier first.

    macOS does not expose Siri voices to say(1), so they never appear here even
    though the assets are on disk.
    """
    ranked = {"premium": 0, "enhanced": 1}
    hits = []
    for name, locale in local_voices():
        if not locale.startswith(languages):
            continue
        lowered = name.lower()
        for keyword, rank in ranked.items():
            if keyword in lowered:
                hits.append((rank, name))
                break
    return [name for _, name in sorted(set(hits))]


def homebrew_prefix() -> str:
    return os.environ.get("HOMEBREW_PREFIX", "/opt/homebrew")
