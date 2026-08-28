"""Voice discovery and auditioning."""

from __future__ import annotations

import shutil
import subprocess

from . import engines
from .config import Config, cache_dir

# Microsoft tags each neural voice with a content category. The "Conversation,
# Copilot" ones are tuned for short assistant utterances and land far better on
# a one-line notification than the "News, Novel" voices, which read
# declamatory. The Multilingual variants pronounce foreign words inside an
# English sentence properly - worth a lot if your branch names are German.
SHORTLIST: list[tuple[str, str]] = [
    ("en-US-AvaMultilingualNeural", "US female, assistant-tuned, handles non-English words"),
    ("en-US-AvaNeural", "US female, assistant-tuned"),
    ("en-US-EmmaMultilingualNeural", "US female, warmer"),
    ("en-US-AndrewMultilingualNeural", "US male, assistant-tuned"),
    ("en-US-BrianNeural", "US male, assistant-tuned"),
    ("en-US-AriaNeural", "US female, crisper news read"),
    ("en-GB-SoniaNeural", "British female"),
    ("en-GB-RyanNeural", "British male"),
    ("en-AU-NatashaNeural", "Australian female"),
    ("de-DE-SeraphinaMultilingualNeural", "German female, handles English"),
    ("de-DE-ConradNeural", "German male"),
]

DEMO_TEXT = (
    "Here is a sentence so you can judge the voice. Notice the pause before a "
    "comma, and whether the pitch rises at the end of a question. Does this "
    "sound like someone you want interrupting you?"
)


def neural_voices() -> list[str]:
    """Every edge-tts voice name, or [] when edge-tts is unreachable."""
    cli = engines._edge_cli()
    if not cli:
        return []
    try:
        out = subprocess.run([*cli, "--list-voices"], capture_output=True,
                             text=True, timeout=90, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    names = []
    for line in out.splitlines():
        token = line.split()[0] if line.split() else ""
        if token.endswith("Neural") and "-" in token:
            names.append(token)
    return names


def list_neural(prefix: str, current: str | None = None) -> tuple[list[str], int]:
    everything = neural_voices()
    hits = [v for v in everything if v.lower().startswith(prefix.lower())]
    return hits, len(everything)


def audition_neural(cfg: Config, text: str,
                    names: list[str] | None = None) -> list[tuple[str, bool]]:
    """Speak `text` in each voice, in turn. Returns (name, played) per voice."""
    dest = cache_dir() / "demo.mp3"
    volume = float(cfg.get("speech", "volume"))
    results = []
    entries = [(n, "") for n in names] if names else SHORTLIST
    for name, blurb in entries:
        print(f"-> {name:36s} {blurb}".rstrip(), flush=True)
        ok = engines.synthesise_to_file(cfg, text, name, dest)
        if ok:
            engines.play(dest, volume)
        else:
            print(f"   (could not synthesise {name}, skipping)", flush=True)
        results.append((name, ok))
    return results


def audition_local(cfg: Config, text: str,
                   names: list[str] | None = None) -> list[str]:
    """Speak `text` in each installed local voice worth hearing."""
    chosen = names or engines.premium_local_voices() or _decent_compact()
    for name in chosen:
        print(f"-> {name}", flush=True)
        if shutil.which("say"):
            subprocess.run(engines.say_argv(cfg, text, name), check=False)
    return chosen


def _decent_compact() -> list[str]:
    wanted = {"Samantha", "Daniel", "Karen", "Moira", "Tessa", "Anna"}
    return [name for name, _ in engines.local_voices() if name in wanted]
