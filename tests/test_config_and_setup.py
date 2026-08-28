"""Config round-tripping, and hook wiring that must never damage settings.json."""

import json

import pytest

from claudio import config as configmod
from claudio import setup as setupmod
from claudio.cli import parse_duration


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDIO_SETTINGS", raising=False)
    monkeypatch.delenv("CLAUDIO_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(setupmod, "SETTINGS", tmp_path / "settings.json")
    yield


def test_defaults_apply_when_no_file():
    cfg = configmod.load()
    assert cfg.get("speech", "engine") == "edge"
    assert cfg.get("notify", "min_turn_seconds") == 45


def test_template_is_valid_toml_and_parses_into_rules():
    path, created = configmod.write_template()
    assert created
    cfg = configmod.load()
    assert cfg.get("speech", "voice").startswith("en-US-Ava")
    tools = [rule.tool for rule in cfg.rules]
    assert "Read" in tools and "Bash" in tools
    assert cfg.rule_for("Read").skip is True
    assert "{description}" in cfg.rule_for("Bash").say


def test_template_is_not_overwritten_without_force():
    configmod.write_template()
    configmod.config_path().write_text('[speech]\nvoice = "mine"\n')
    _, created = configmod.write_template()
    assert created is False
    assert configmod.load().get("speech", "voice") == "mine"


def test_save_round_trips():
    cfg = configmod.load()
    cfg.speech["voice"] = "en-GB-SoniaNeural"
    configmod.save(cfg)
    assert configmod.load().get("speech", "voice") == "en-GB-SoniaNeural"


def test_broken_config_falls_back_to_defaults():
    configmod.config_path().parent.mkdir(parents=True, exist_ok=True)
    configmod.config_path().write_text("this is not [valid toml")
    assert configmod.load().get("speech", "engine") == "edge"


def test_rule_glob_matching():
    rule = configmod.Rule(tool="mcp__*")
    assert rule.matches("mcp__postgres__query")
    assert not rule.matches("Edit")


# --------------------------------------------------------------------------- #
# settings.json
# --------------------------------------------------------------------------- #

def test_install_creates_hooks():
    added = setupmod.install_hooks()
    assert set(added) == set(setupmod.HOOK_EVENTS)
    assert all(setupmod.hooks_installed().values())


def test_install_is_idempotent():
    setupmod.install_hooks()
    assert setupmod.install_hooks() == []


def test_install_preserves_unrelated_settings_and_hooks():
    setupmod.SETTINGS.write_text(json.dumps({
        "model": "sonnet",
        "permissions": {"allow": ["Bash(gh:*)"]},
        "hooks": {"Notification": [
            {"hooks": [{"type": "command", "command": "/other/tool notify"}]}]},
    }))
    setupmod.install_hooks()
    data = json.loads(setupmod.SETTINGS.read_text())
    assert data["model"] == "sonnet"
    assert data["permissions"]["allow"] == ["Bash(gh:*)"]
    commands = [h["command"] for e in data["hooks"]["Notification"] for h in e["hooks"]]
    assert "/other/tool notify" in commands
    assert any("claudio" in c for c in commands)


def test_uninstall_removes_only_our_hooks():
    setupmod.SETTINGS.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "/other/tool x"}]}]}}))
    setupmod.install_hooks()
    setupmod.uninstall_hooks()
    data = json.loads(setupmod.SETTINGS.read_text())
    remaining = [h["command"] for e in data.get("hooks", {}).get("Stop", [])
                 for h in e["hooks"]]
    assert remaining == ["/other/tool x"]
    assert not any(setupmod.hooks_installed().values())


def test_install_backs_up_existing_settings():
    setupmod.SETTINGS.write_text('{"model": "sonnet"}')
    setupmod.install_hooks()
    backup = setupmod.SETTINGS.with_suffix(".json.claudio-backup")
    assert backup.exists()
    assert json.loads(backup.read_text()) == {"model": "sonnet"}


def test_corrupt_settings_does_not_crash_detection():
    setupmod.SETTINGS.write_text("{not json")
    assert setupmod.hooks_installed() == dict.fromkeys(setupmod.HOOK_EVENTS, False)


# --------------------------------------------------------------------------- #
# durations
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("text", "low", "high"), [
    ("30m", 1750, 1850),
    ("2h", 7150, 7250),
    ("90", 5350, 5450),
    ("45s", 40, 50),
])
def test_relative_durations(text, low, high):
    import time
    delta = parse_duration(text) - time.time()
    assert low < delta < high


def test_forever_is_far_future():
    import time
    assert parse_duration("forever") - time.time() > 86400 * 365


def test_bad_duration_is_rejected():
    with pytest.raises(SystemExit):
        parse_duration("banana")
