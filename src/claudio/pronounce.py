"""Respelling words the voice gets wrong.

The neural `Multilingual` voices take no language parameter. They detect the
language of each span from the text alone, so a lone German noun inside an
English sentence - `Bestellung`, `Rechnung` - can be detected as French and
spoken with French phonology. Microsoft's SSML `<lang>` element would fix that
properly, but edge-tts XML-escapes the text and hardcodes `xml:lang='en-US'`, so
no markup can reach the endpoint.

What we do control is the text. Respelling a word phonetically before it is sent
means the detector never sees the foreign spelling, so it cannot guess wrong.
This works on every engine, including local say(1), and needs no network.

Only speech is rewritten; the notification banner keeps the real spelling, so
what you read stays accurate to what Claude is doing.
"""

from __future__ import annotations

import re

MAX_ENTRIES = 500


def compile_rules(mapping: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """Whole-word, case-insensitive patterns, longest key first.

    Longest-first matters: with both `Bestellung` and `stell` configured, the
    longer entry has to win or it would be rewritten piecemeal.
    """
    rules = []
    for key in sorted(mapping, key=len, reverse=True)[:MAX_ENTRIES]:
        word = str(key).strip()
        if not word:
            continue
        replacement = str(mapping[key])
        # \b fails next to non-ASCII letters (ü, ß), so use explicit boundaries.
        pattern = re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.IGNORECASE)
        rules.append((pattern, replacement))
    return rules


def apply(text: str, mapping: dict[str, str] | None) -> str:
    """Rewrite configured words. Returns `text` unchanged when nothing matches."""
    if not text or not mapping:
        return text
    out = text
    for pattern, replacement in compile_rules(mapping):
        out = pattern.sub(lambda _, r=replacement: r, out)
    return out


def preview(text: str, mapping: dict[str, str] | None) -> list[tuple[str, str]]:
    """Which entries would fire on this text - used by `claudio pronounce`."""
    if not text or not mapping:
        return []
    hits = []
    for pattern, replacement in compile_rules(mapping):
        found = pattern.search(text)
        if found:
            hits.append((found.group(0), replacement))
    return hits
