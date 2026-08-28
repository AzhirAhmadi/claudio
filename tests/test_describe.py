"""The headline behaviour: a tool call must describe itself, not just name itself."""

import pytest

from claudio.describe import describe, spoken_path


@pytest.mark.parametrize(("raw", "expected"), [
    ("/a/b/invoice_repository.rb", "invoice repository"),
    ("app/models/order_spec.rb", "order spec"),
    ("Gemfile", "Gemfile"),
    ("db/structure.sql", "structure"),
    ("some-kebab-name.ts", "some kebab name"),
    ("", ""),
    (None, ""),
])
def test_spoken_path(raw, expected):
    assert spoken_path(raw) == expected


def test_edit_names_the_file_and_the_change():
    result = describe("Edit", {
        "file_path": "/x/app/services/invoice_policy.rb",
        "old_string": "def call",
        "new_string": "  validates :starts_at, presence: true\n",
    })
    assert "invoice policy" in result.phrase
    assert "validates :starts_at" in result.phrase
    assert result.fields["file"] == "invoice policy"


def test_edit_flags_replace_all():
    result = describe("Edit", {"file_path": "a.rb", "new_string": "x = 1",
                               "replace_all": True})
    assert "everywhere" in result.phrase


def test_bash_prefers_claudes_own_description():
    result = describe("Bash", {"command": "bundle exec rspec spec/foo_spec.rb:12",
                               "description": "Run the checkout specs"})
    assert result.phrase == "Run the checkout specs"
    assert result.fields["program"] == "bundle"


def test_bash_falls_back_to_the_command():
    result = describe("Bash", {"command": "git push --force-with-lease origin main"})
    assert result.phrase.startswith("run git push")


def test_bash_mentions_background():
    result = describe("Bash", {"command": "sleep 100", "description": "Wait",
                               "run_in_background": True})
    assert "in the background" in result.phrase


def test_write_counts_lines():
    result = describe("Write", {"file_path": "notes.md", "content": "a\nb\nc"})
    assert "create notes" in result.phrase
    assert result.fields["lines"] == "3"


def test_webfetch_uses_the_domain():
    result = describe("WebFetch", {"url": "https://docs.example.com/a/b?c=1",
                                   "prompt": "find the schema"})
    assert result.phrase == "fetch docs.example.com"
    assert result.fields["domain"] == "docs.example.com"


def test_task_names_the_agent():
    result = describe("Task", {"subagent_type": "code-reviewer",
                               "description": "review the diff"})
    assert "code reviewer agent" in result.phrase
    assert "review the diff" in result.phrase


def test_mcp_tool_splits_server_and_tool():
    result = describe("mcp__analytics-db__execute_sql", {})
    assert result.fields["server"] == "analytics db"
    assert result.fields["mcp_tool"] == "execute sql"
    assert "analytics db" in result.phrase


def test_unknown_tool_still_says_something():
    result = describe("SomeFutureTool", {"whatever": 1})
    assert result.phrase == "use some future tool"


@pytest.mark.parametrize("payload", [None, {}, {"file_path": None}, "not a dict"])
def test_never_raises_on_junk(payload):
    assert describe("Edit", payload).phrase


def test_long_change_is_clipped():
    result = describe("Edit", {"file_path": "a.rb", "new_string": "x" * 500})
    assert len(result.phrase) <= 200
