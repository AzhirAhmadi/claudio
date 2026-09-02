"""Respelling: it must fix the words asked for and touch nothing else."""

from __future__ import annotations

import pytest

from claudio import config as configmod
from claudio import pronounce
from claudio import setup as setupmod
from claudio.cli import main

GERMAN = {
    "Bestellung": "Be-shtell-ung",
    "Rechnung": "Rekh-nung",
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDIO_SETTINGS", raising=False)
    monkeypatch.delenv("CLAUDIO_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(setupmod, "SETTINGS", tmp_path / "settings.json")
    yield


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #

def test_replaces_a_configured_word():
    assert pronounce.apply("edit Bestellung sync", GERMAN) == "edit Be-shtell-ung sync"


def test_is_case_insensitive():
    assert pronounce.apply("BESTELLUNG", GERMAN) == "Be-shtell-ung"
    assert pronounce.apply("bestellung", GERMAN) == "Be-shtell-ung"


def test_matches_whole_words_only():
    """A substring must not be rewritten mid-word."""
    assert pronounce.apply("Bestellungen", GERMAN) == "Bestellungen"
    assert pronounce.apply("preBestellung", GERMAN) == "preBestellung"


def test_longest_entry_wins():
    mapping = {"stell": "shtell", "Bestellung": "Be-shtell-ung"}
    assert pronounce.apply("the Bestellung", mapping) == "the Be-shtell-ung"


def test_handles_non_ascii_boundaries():
    """\\b misbehaves next to umlauts, so boundaries are explicit."""
    mapping = {"Prüfung": "Proo-fung"}
    assert pronounce.apply("the Prüfung today", mapping) == "the Proo-fung today"


def test_replacement_is_literal_not_a_regex_template():
    mapping = {"cost": r"\1 dollars"}
    assert pronounce.apply("the cost", mapping) == r"the \1 dollars"


def test_special_characters_in_the_key_are_escaped():
    mapping = {"a.b": "ay bee"}
    assert pronounce.apply("a.b", mapping) == "ay bee"
    assert pronounce.apply("axb", mapping) == "axb"


def test_multiple_occurrences_all_replaced():
    assert pronounce.apply("Bestellung and Bestellung", GERMAN) == \
        "Be-shtell-ung and Be-shtell-ung"


@pytest.mark.parametrize("mapping", [None, {}])
def test_no_table_is_a_no_op(mapping):
    assert pronounce.apply("anything at all", mapping) == "anything at all"


def test_empty_text_is_safe():
    assert pronounce.apply("", GERMAN) == ""


def test_blank_keys_are_ignored():
    assert pronounce.apply("hello", {"  ": "x"}) == "hello"


def test_preview_reports_what_fired():
    hits = pronounce.preview("edit Bestellung now", GERMAN)
    assert hits == [("Bestellung", "Be-shtell-ung")]


def test_preview_is_empty_when_nothing_matches():
    assert pronounce.preview("edit the order", GERMAN) == []


# --------------------------------------------------------------------------- #
# config plumbing
# --------------------------------------------------------------------------- #

def test_table_loads_from_config():
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text(
        '[pronounce]\nBestellung = "Be-shtell-ung"\n')
    assert configmod.load().pronounce == {"Bestellung": "Be-shtell-ung"}


def test_shipped_template_parses_with_an_empty_table():
    configmod.write_template()
    cfg = configmod.load()
    assert cfg.pronounce == {}
    # the [[rule]] array and the [pronounce] table must coexist
    assert len(cfg.rules) == 3


def test_table_survives_a_full_rewrite():
    cfg = configmod.load()
    cfg.pronounce = dict(GERMAN)
    configmod.save(cfg)
    assert configmod.load().pronounce == GERMAN


def test_speech_is_rewritten_but_the_banner_is_not(monkeypatch):
    """Only what is spoken changes; what you read stays accurate."""
    from claudio import engines

    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text(
        '[speech]\nengine = "say"\n\n[pronounce]\nBestellung = "Be-shtell-ung"\n')

    spoken = []
    monkeypatch.setattr(engines, "_speak_say", lambda cfg, text: spoken.append(text))
    monkeypatch.setattr(engines, "_speak_edge", lambda cfg, text: False)

    engines.speak(configmod.load(), "edit Bestellung")
    assert spoken == ["edit Be-shtell-ung"]


# --------------------------------------------------------------------------- #
# the CLI
# --------------------------------------------------------------------------- #

def test_pronounce_lists_the_table(capsys):
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text(
        '[pronounce]\nBestellung = "Be-shtell-ung"\n')
    assert main(["pronounce"]) == 0
    out = capsys.readouterr().out
    assert "Bestellung" in out and "Be-shtell-ung" in out


def test_pronounce_explains_an_empty_table(capsys):
    assert main(["pronounce"]) == 0
    assert "no [pronounce] entries yet" in capsys.readouterr().out


def test_pronounce_previews_text(capsys):
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text(
        '[pronounce]\nBestellung = "Be-shtell-ung"\n')
    assert main(["pronounce", "edit", "Bestellung", "now"]) == 0
    out = capsys.readouterr().out
    assert "written: edit Bestellung now" in out
    assert "spoken : edit Be-shtell-ung now" in out
    assert "Bestellung -> Be-shtell-ung" in out


def test_pronounce_says_when_nothing_matched(capsys):
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text('[pronounce]\nFoo = "bar"\n')
    main(["pronounce", "hello world"])
    assert "nothing matched" in capsys.readouterr().out
