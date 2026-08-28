"""Guard: nothing employer-specific or secret may reach this public repo.

This project is published openly, but it was written while working on a private
codebase. It is very easy for a domain term, an internal hostname, a ticket ID
or a real name to drift into an example or a docstring. This test fails loudly
if that happens, so the mistake is caught before a commit rather than after a
push.

Add to DENY when you notice a new term worth banning. Keep entries lowercase.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SCANNED_SUFFIXES = {".py", ".md", ".toml", ".rb", ".sh", ".yml", ".yaml", ".cfg", ".txt"}
SKIPPED_DIRS = {".git", ".venv", "venv", "dist", "build", "__pycache__",
                ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"}

# Terms that must never appear: employer, product and domain vocabulary from the
# private codebase this was extracted from, plus the author's WORK identity.
#
# The owner's own handle is deliberately absent - this is published under
# github.com/AzhirAhmadi, so that name belongs in the URLs. What must never
# appear is the work account, the employer, or anything from their codebase.
DENY = [
    "studitemps", "jobvalley", "azhirjobvalley", "shinobi",
    "disposition", "schichtplan", "planung", "garantielohn", "auftragsnummer",
    "zendesk", "appsignal", "prod-readonly", "maf-",
]

# The owner's public handle, allowed only in their own repository URLs. Any
# other appearance of a personal identifier still trips the email pattern below.
OWNER = "azhirahmadi"

# Anything that looks like a credential, however it got there.
SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "OpenAI-style API key"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "GitHub personal access token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "GitHub fine-grained token"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."), "JWT"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"\bpostgres(?:ql)?://[^\s\"']*:[^\s\"'@]+@"), "database URL with password"),
    (re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org)\b)"
                r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email address"),
]


def scanned_files() -> list[Path]:
    found = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        if SKIPPED_DIRS & set(path.relative_to(ROOT).parts):
            continue
        found.append(path)
    return sorted(found)


def test_there_is_something_to_scan():
    files = scanned_files()
    assert len(files) > 8, f"expected to scan the project, only found {files}"


@pytest.mark.parametrize("path", scanned_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_employer_or_domain_terms(path: Path):
    if path.name == Path(__file__).name:
        pytest.skip("this file necessarily contains the denylist")
    lowered = path.read_text(errors="replace").lower()
    hits = sorted({term for term in DENY if term in lowered})
    assert not hits, (
        f"{path.relative_to(ROOT)} contains private/domain terms {hits}. "
        "Replace them with a neutral example before committing."
    )


@pytest.mark.parametrize("path", scanned_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_owner_handle_appears_only_in_repository_urls(path: Path):
    """The owner's name is fine in their own URLs, nowhere else."""
    if path.name == Path(__file__).name:
        pytest.skip("this file necessarily contains the handle")
    # The handle is legitimate only as part of an `owner/claudio` identifier: a
    # git URL, a Homebrew tap (owner/claudio) or formula (owner/claudio/claudio).
    # Strip every such reference; anything left is the handle loose in prose.
    identifier = re.compile(rf"(?:(?:github\.com|githubusercontent\.com)[:/])?"
                            rf"{OWNER}/claudio(?:/claudio)?(?:\.git)?", re.I)
    stray = []
    for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if OWNER not in line.lower():
            continue
        if OWNER in identifier.sub("", line).lower():
            stray.append(number)
    assert not stray, (
        f"{path.relative_to(ROOT)} mentions the owner handle outside an "
        f"owner/claudio identifier at line(s) {stray}. Keep identity out of prose."
    )


@pytest.mark.parametrize("path", scanned_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_credentials_or_real_addresses(path: Path):
    if path.name == Path(__file__).name:
        pytest.skip("this file necessarily contains the patterns")
    body = path.read_text(errors="replace")
    found = [label for pattern, label in SECRET_PATTERNS if pattern.search(body)]
    assert not found, (
        f"{path.relative_to(ROOT)} looks like it contains {found}. "
        "Secrets belong in the Keychain and are asked for at setup, never in the repo."
    )


def test_the_tool_never_reads_a_credential_from_config():
    """claudio needs no credential; nothing should be quietly harvesting one.

    A bare "token" is excluded on purpose - it legitimately means a lexical
    token when parsing `say -v ?` output. Only auth-shaped names are banned.
    """
    suspicious = re.compile(
        r"(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token"
        r"|bearer|client[_-]?secret|\bsecret\b|\bpasswords?\b|\bcredentials?\b)",
        re.I,
    )
    offenders = {}
    for path in (ROOT / "src").rglob("*.py"):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if suspicious.search(line) and "Keychain" not in line:
                offenders.setdefault(str(path.relative_to(ROOT)), []).append(number)
    assert not offenders, (
        f"credential handling appeared in {offenders}. If an engine ever needs a "
        "key, prompt for it in `claudio setup` and store it in the macOS Keychain "
        "- never in config.toml, and never committed."
    )
