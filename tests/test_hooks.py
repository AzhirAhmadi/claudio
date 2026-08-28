"""What gets said, for which event, and when nothing should be said at all."""

import json
import time

import pytest

from claudio import hooks
from claudio.config import Config, Rule


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDIO_SETTINGS", raising=False)
    monkeypatch.delenv("CLAUDIO_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield


def cfg(**overrides) -> Config:
    conf = Config()
    conf.notify.update(overrides.pop("notify", {}))
    conf.speech.update(overrides.pop("speech", {}))
    conf.session.update(overrides.pop("session", {}))
    conf.rules = overrides.pop("rules", [])
    return conf


def transcript_file(tmp_path, *, title=None, assistant=None, user_ago=None):
    path = tmp_path / "t.jsonl"
    lines = []
    if title:
        lines.append({"type": "ai-title", "aiTitle": title, "sessionId": "x"})
    if user_ago is not None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.gmtime(time.time() - user_ago)) + ".000Z"
        lines.append({"type": "user", "timestamp": stamp,
                      "message": {"role": "user", "content": "hi"}})
    if assistant:
        lines.append({"type": "assistant", "isSidechain": False,
                      "message": {"role": "assistant",
                                  "content": [{"type": "text", "text": assistant}]}})
    path.write_text("\n".join(json.dumps(item) for item in lines))
    return str(path)


# --------------------------------------------------------------------------- #
# permission requests - the whole point of the tool
# --------------------------------------------------------------------------- #

def test_permission_says_what_the_edit_is(tmp_path):
    payload = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Edit",
        "tool_input": {"file_path": "app/models/order.rb",
                       "new_string": "validates :name, presence: true"},
        "cwd": "/w/my-project-a1b2c3",
        "transcript_path": transcript_file(tmp_path, title="order validation"),
    }
    result = hooks.build(payload, cfg())
    assert result is not None
    assert "order" in result.text
    assert "validates :name" in result.text
    assert "Edit" not in result.text


def test_permission_respects_a_skip_rule(tmp_path):
    payload = {"hook_event_name": "PermissionRequest", "tool_name": "Read",
               "tool_input": {"file_path": "a.rb"}, "cwd": "/w/x"}
    assert hooks.build(payload, cfg(rules=[Rule(tool="Read", skip=True)])) is None


def test_permission_uses_a_custom_template(tmp_path):
    payload = {
        "hook_event_name": "PermissionRequest", "tool_name": "Bash",
        "tool_input": {"command": "rails db:migrate", "description": "Run migrations"},
        "cwd": "/w/shop-a1b2c3",
        "transcript_path": transcript_file(tmp_path, title="db work"),
    }
    rule = Rule(tool="Bash", say="{session} wants to run {description}")
    result = hooks.build(payload, cfg(rules=[rule]))
    assert result.text == "db work wants to run Run migrations"


def test_glob_rule_matches_mcp_tools():
    payload = {"hook_event_name": "PermissionRequest",
               "tool_name": "mcp__postgres__query", "tool_input": {}, "cwd": "/w/x"}
    rule = Rule(tool="mcp__*", say="database access on {server}")
    result = hooks.build(payload, cfg(rules=[rule]))
    assert result.text == "database access on postgres"


def test_permission_can_be_switched_off():
    payload = {"hook_event_name": "PermissionRequest", "tool_name": "Edit",
               "tool_input": {}, "cwd": "/w/x"}
    assert hooks.build(payload, cfg(notify={"permission": False})) is None


def test_generic_permission_notification_is_suppressed_after_a_rich_one():
    rich = {"hook_event_name": "PermissionRequest", "tool_name": "Edit",
            "tool_input": {"file_path": "a.rb"}, "cwd": "/w/x"}
    assert hooks.build(rich, cfg()) is not None
    generic = {"hook_event_name": "Notification",
               "notification_type": "permission_prompt",
               "message": "Claude needs your permission to use Edit", "cwd": "/w/x"}
    assert hooks.build(generic, cfg()) is None


# --------------------------------------------------------------------------- #
# other events
# --------------------------------------------------------------------------- #

def test_idle_reads_the_last_question(tmp_path):
    payload = {"hook_event_name": "Notification", "notification_type": "idle_prompt",
               "message": "Claude is waiting for your input", "cwd": "/w/x",
               "transcript_path": transcript_file(
                   tmp_path, title="my work",
                   assistant="I did the thing. Should I open the PR as a draft?")}
    result = hooks.build(payload, cfg())
    assert "Should I open the PR as a draft?" in result.text
    assert "is waiting" in result.text


def test_turn_end_is_silent_for_a_quick_turn(tmp_path):
    payload = {"hook_event_name": "Stop", "stop_hook_active": False,
               "last_assistant_message": "Done.", "cwd": "/w/x",
               "transcript_path": transcript_file(tmp_path, user_ago=5)}
    assert hooks.build(payload, cfg(notify={"min_turn_seconds": 45})) is None


def test_turn_end_speaks_for_a_long_turn(tmp_path):
    payload = {"hook_event_name": "Stop", "stop_hook_active": False,
               "last_assistant_message": "All 14 specs pass. Shall I merge?",
               "cwd": "/w/x",
               "transcript_path": transcript_file(tmp_path, title="specs", user_ago=600)}
    result = hooks.build(payload, cfg(notify={"min_turn_seconds": 45}))
    assert "Shall I merge?" in result.text


def test_stop_hook_active_is_ignored():
    payload = {"hook_event_name": "Stop", "stop_hook_active": True,
               "last_assistant_message": "x", "cwd": "/w/x"}
    assert hooks.build(payload, cfg()) is None


def test_subagent_events_are_ignored():
    payload = {"hook_event_name": "PermissionRequest", "agent_id": "abc",
               "tool_name": "Edit", "tool_input": {}, "cwd": "/w/x"}
    assert hooks.build(payload, cfg()) is None


def test_unknown_event_is_ignored():
    assert hooks.build({"hook_event_name": "PostToolUse", "cwd": "/w/x"}, cfg()) is None


# --------------------------------------------------------------------------- #
# naming
# --------------------------------------------------------------------------- #

def test_worktree_hash_is_stripped():
    assert hooks.label_from_cwd("/a/b/sick-leave-fix-9185ce") == "sick leave fix"


def test_sorting_key_is_not_spoken():
    assert hooks.speakable_label("3-1042 login timeout") == "login timeout"
    assert hooks.speakable_label("4-???? open question") == "open question"


def test_sorting_key_can_be_kept():
    assert hooks.speakable_label("2-1994 x", strip_key=False) == "2-1994 x"


def test_title_beats_cwd(tmp_path):
    payload = {"cwd": "/a/b/ugly-dir-a1b2c3",
               "transcript_path": transcript_file(tmp_path, title="Nice Title")}
    assert hooks.session_label(payload) == "Nice Title"


def test_cwd_is_the_fallback():
    assert hooks.session_label({"cwd": "/a/b/my-thing-a1b2c3"}) == "my thing"


# --------------------------------------------------------------------------- #
# templating
# --------------------------------------------------------------------------- #

def test_render_leaves_unknown_placeholders_alone():
    assert hooks.render("{a} and {b}", {"a": "x"}) == "x and {b}"


def test_dedupe_window():
    assert hooks.already_said("same", 10) is False
    assert hooks.already_said("same", 10) is True
    assert hooks.already_said("different", 10) is False


def test_mute_and_unmute():
    conf = cfg()
    assert hooks.muted(conf) is None
    hooks.set_mute(until=time.time() + 600)
    assert "muted" in hooks.muted(conf)
    hooks.set_mute(until=0)
    assert hooks.muted(conf) is None
    hooks.set_mute(disabled=True)
    assert hooks.muted(conf) == "off"
