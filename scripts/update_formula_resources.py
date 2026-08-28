#!/usr/bin/env python3
"""Regenerate the Homebrew formula's `resource` blocks from the real dependency tree.

`virtualenv_install_with_resources` vendors every dependency, so the formula needs
the full transitive closure with a sha256 for each sdist - not just the direct
dependencies. Getting that by hand is error-prone and goes stale on every bump.

Usage:
    python3 scripts/update_formula_resources.py            # rewrite the formula
    python3 scripts/update_formula_resources.py --check    # fail if out of date

Needs `uv` on PATH and network access to PyPI.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMULA = ROOT / "Formula" / "claudio.rb"
BEGIN = "  # BEGIN generated resources - scripts/update_formula_resources.py"
END = "  # END generated resources"


def project_dependencies() -> list[str]:
    """Read the runtime dependencies straight out of pyproject.toml."""
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return list(data["project"]["dependencies"])


def resolve(requirements: list[str]) -> list[tuple[str, str]]:
    """Pin the full closure with uv, returning [(name, version), ...]."""
    result = subprocess.run(
        ["uv", "pip", "compile", "--quiet", "--no-header", "-"],
        input="\n".join(requirements) + "\n",
        capture_output=True, text=True, check=True,
    )
    pinned = []
    for line in result.stdout.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pinned.append((name.strip(), version.strip()))
    return sorted(pinned)


def sdist(name: str, version: str) -> tuple[str, str]:
    """(url, sha256) of the source distribution on PyPI."""
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        payload = json.load(response)
    for entry in payload["urls"]:
        if entry["packagetype"] == "sdist":
            return entry["url"], entry["digests"]["sha256"]
    raise SystemExit(f"{name} {version} publishes no sdist; "
                     "Homebrew needs one to build from source")


def render(pinned: list[tuple[str, str]]) -> str:
    lines = [BEGIN]
    for name, version in pinned:
        url, digest = sdist(name, version)
        lines += [
            f'  resource "{name}" do',
            f'    url "{url}"',
            f'    sha256 "{digest}"',
            "  end",
            "",
        ]
    lines[-1] = END
    return "\n".join(lines)


def splice(body: str, block: str) -> str:
    pattern = re.compile(rf"{re.escape(BEGIN)}.*?{re.escape(END)}", re.S)
    if pattern.search(body):
        return pattern.sub(block, body)
    # First run: replace whatever hand-written resources are there.
    existing = re.compile(r"(  # Regenerate with:.*?\n)?(  resource \".*?\n  end\n\n?)+", re.S)
    if existing.search(body):
        return existing.sub(block + "\n\n", body, count=1)
    return body.replace("  def install", block + "\n\n  def install")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the formula is out of date")
    args = parser.parse_args(argv)

    pinned = resolve(project_dependencies())
    block = render(pinned)
    body = FORMULA.read_text()
    updated = splice(body, block)

    if args.check:
        if updated != body:
            print("Formula/claudio.rb resources are out of date; run "
                  "scripts/update_formula_resources.py", file=sys.stderr)
            return 1
        print(f"formula resources up to date ({len(pinned)} packages)")
        return 0

    FORMULA.write_text(updated)
    print(f"wrote {len(pinned)} resources to {FORMULA.relative_to(ROOT)}")
    for name, version in pinned:
        print(f"  {name} {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
