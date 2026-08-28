"""Consent must be informed, refusable, and never assumed."""

from __future__ import annotations

import pytest

from claudio import config as configmod
from claudio import consent
from claudio import setup as setupmod
from claudio.cli import main


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDIO_SETTINGS", raising=False)
    monkeypatch.delenv("CLAUDIO_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(setupmod, "SETTINGS", tmp_path / "settings.json")
    yield


def answer(monkeypatch, *replies):
    """Drive the prompt as if a person were typing, on a real terminal."""
    queue = list(replies)
    monkeypatch.setattr(consent, "interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _="": queue.pop(0))


# --------------------------------------------------------------------------- #
# the disclosure itself
# --------------------------------------------------------------------------- #

def test_disclaimer_lists_every_item_actually_sent():
    text = consent.disclaimer()
    for item in consent.SENT:
        assert item in text
    for item in consent.NOT_SENT:
        assert item in text


def test_disclaimer_names_microsoft_and_the_code_line():
    text = consent.disclaimer().lower()
    assert "microsoft" in text
    assert "one line of the code being changed" in text
    assert "ip address" in text


def test_disclaimer_says_the_useful_part_is_unaffected():
    """Declining must not read as choosing a crippled tool."""
    text = consent.disclaimer().lower()
    assert "identical" in text
    assert "either way" in text


def test_disclaimer_warns_about_employer_codebases():
    assert "employer-owned" in consent.disclaimer()


# --------------------------------------------------------------------------- #
# answering
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("reply", ["y", "Y", "yes", "1", "neural"])
def test_accepting_selects_neural(monkeypatch, reply):
    answer(monkeypatch, reply)
    assert consent.ask() == (consent.NEURAL, True)


@pytest.mark.parametrize("reply", ["n", "no", "N", "2", "local"])
def test_declining_selects_local(monkeypatch, reply):
    answer(monkeypatch, reply)
    assert consent.ask() == (consent.LOCAL, True)


def test_bare_enter_declines(monkeypatch):
    """The safe option must be the default, so a hurried Enter cannot opt in."""
    answer(monkeypatch, "")
    assert consent.ask() == (consent.LOCAL, True)


def test_nonsense_is_rejected_until_a_real_answer(monkeypatch):
    answer(monkeypatch, "maybe", "wat", "y")
    assert consent.ask() == (consent.NEURAL, True)


def test_ctrl_c_declines(monkeypatch):
    monkeypatch.setattr(consent, "interactive", lambda: True)

    def interrupt(_=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert consent.ask() == (consent.LOCAL, False)


def test_no_terminal_never_assumes_agreement(monkeypatch):
    """A piped `curl | sh` install must not silently opt in."""
    monkeypatch.setattr(consent, "interactive", lambda: False)
    assert consent.ask() == (consent.LOCAL, False)


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #

def test_acceptance_is_recorded_with_a_timestamp():
    from claudio import hooks

    cfg = consent.record(configmod.load(), consent.NEURAL, accepted=True)
    assert consent.consented(cfg)
    assert hooks.read_state()["neural_consent"].startswith("20")
    assert configmod.load().get("speech", "engine") == "edge"


def test_acceptance_is_not_stored_in_the_editable_config():
    """Consent must not be forgeable by hand-editing config.toml."""
    consent.record(configmod.load(), consent.NEURAL, accepted=True)
    assert "neural_consent" not in configmod.config_path().read_text()


def test_switching_to_local_clears_the_record():
    consent.record(configmod.load(), consent.NEURAL, accepted=True)
    cfg = consent.record(configmod.load(), consent.LOCAL, accepted=False)
    assert not consent.consented(cfg)
    assert configmod.load().get("speech", "engine") == "say"


def test_switching_engines_preserves_the_documented_config():
    """set_value edits in place; a full rewrite would strip every comment."""
    configmod.write_template()
    before = configmod.config_path().read_text()
    assert "# Rules: control what a permission request actually says." in before

    consent.record(configmod.load(), consent.LOCAL, accepted=False)
    after = configmod.config_path().read_text()

    assert "# Rules: control what a permission request actually says." in after
    assert "# claudio voices en-" in after
    assert after.count("[[rule]]") == before.count("[[rule]]")
    assert 'engine = "say"' in after
    assert 'engine = "edge"' not in after
    # the trailing comment on the edited line survives too
    assert "neural, needs network" in after


def test_neural_without_acceptance_is_flagged():
    """A hand-edited config must not quietly bypass the disclosure."""
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text('[speech]\nengine = "edge"\n')
    assert consent.needs_disclosure(configmod.load())


def test_local_never_needs_disclosure():
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text('[speech]\nengine = "say"\n')
    assert not consent.needs_disclosure(configmod.load())


@pytest.mark.parametrize(("given", "expected"), [
    ("neural", "edge"), ("edge", "edge"), ("microsoft", "edge"),
    ("local", "say"), ("say", "say"), ("offline", "say"),
    ("banana", None), ("", None), (None, None),
])
def test_engine_names(given, expected):
    assert consent.normalise(given) == expected


# --------------------------------------------------------------------------- #
# through the CLI
# --------------------------------------------------------------------------- #

def test_setup_asks_and_honours_a_refusal(monkeypatch, capsys):
    answer(monkeypatch, "n")
    assert main(["setup"]) == 0
    assert configmod.load().get("speech", "engine") == "say"
    assert "Microsoft" in capsys.readouterr().out


def test_setup_honours_acceptance(monkeypatch):
    answer(monkeypatch, "y")
    main(["setup"])
    cfg = configmod.load()
    assert cfg.get("speech", "engine") == "edge"
    assert consent.consented(cfg)


def test_setup_engine_flag_skips_the_prompt_but_still_prints_disclosure(capsys):
    assert main(["setup", "--engine", "neural"]) == 0
    assert configmod.load().get("speech", "engine") == "edge"
    assert "Microsoft" in capsys.readouterr().out


def test_setup_rejects_an_unknown_engine():
    with pytest.raises(SystemExit):
        main(["setup", "--engine", "banana"])


def test_engine_command_shows_disclosure_every_time(monkeypatch, capsys):
    consent.record(configmod.load(), consent.NEURAL, accepted=True)
    answer(monkeypatch, "y")
    main(["engine", "neural"])
    assert "sent to Microsoft" in capsys.readouterr().out


def test_engine_switch_can_be_declined_mid_flight(monkeypatch):
    consent.record(configmod.load(), consent.LOCAL, accepted=False)
    answer(monkeypatch, "n")
    main(["engine", "neural"])
    assert configmod.load().get("speech", "engine") == "say"


def test_engine_to_local_needs_no_prompt(capsys):
    consent.record(configmod.load(), consent.NEURAL, accepted=True)
    assert main(["engine", "local"]) == 0
    assert configmod.load().get("speech", "engine") == "say"
    assert "Nothing leaves your Mac" in capsys.readouterr().out


def test_engine_yes_flag_still_prints_the_disclosure(capsys):
    assert main(["engine", "neural", "--yes"]) == 0
    assert consent.consented(configmod.load())
    out = capsys.readouterr().out
    assert "Microsoft" in out and "Not sent" in out


def test_engine_with_no_argument_reports_state(capsys):
    consent.record(configmod.load(), consent.LOCAL, accepted=False)
    assert main(["engine"]) == 0
    assert "local" in capsys.readouterr().out


def test_doctor_flags_undisclosed_neural(capsys):
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text('[speech]\nengine = "edge"\n')
    main(["doctor"])
    out = capsys.readouterr().out
    assert "NOT yet disclosed" in out
