#!/bin/sh
# Cut a release: tag it, then point the formula at the real tarball checksum.
#
#   scripts/release.sh 0.1.0
#
# The tarball sha256 cannot be known before the tag exists on GitHub, so the
# order matters: tag, push the tag, let GitHub generate the archive, then hash
# it. This script does all of that and leaves the formula change staged for you
# to review.

set -eu

cd "$(dirname "$0")/.."

VERSION="${1-}"
[ -n "$VERSION" ] || { echo "usage: $0 <version>   e.g. $0 0.1.0" >&2; exit 2; }
case "$VERSION" in
  v*) echo "error: give the version without a leading v (e.g. 0.1.0)" >&2; exit 1 ;;
esac

OWNER=$(sed -n 's|.*github\.com/\([^/]*\)/claudio.*|\1|p' Formula/claudio.rb | head -1)
[ -n "$OWNER" ] || { echo "error: cannot read the owner from Formula/claudio.rb" >&2; exit 1; }
TAG="v$VERSION"

command -v uv >/dev/null 2>&1 || { echo "error: uv is required" >&2; exit 1; }

echo "==> checks"
uv run --extra dev ruff check src tests
uv run --extra dev pytest -q
python3 scripts/update_formula_resources.py >/dev/null
echo "    formula resources refreshed"

if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree is dirty; commit or stash first" >&2
  git status --short >&2
  exit 1
fi

echo "==> version bump to $VERSION"
sed -i '' "s|^version = \".*\"|version = \"$VERSION\"|" pyproject.toml
sed -i '' "s|^VERSION = \".*\"|VERSION = \"$VERSION\"|" src/claudio/cli.py
grep -q "\"$VERSION\"" pyproject.toml || { echo "error: bump failed" >&2; exit 1; }

if [ -n "$(git status --porcelain)" ]; then
  git add pyproject.toml src/claudio/cli.py Formula/claudio.rb
  git commit -q -m "Release $VERSION"
  echo "    committed"
fi

echo "==> tag and push"
git tag -a "$TAG" -m "claudio $VERSION"
git push origin HEAD
git push origin "$TAG"

ARCHIVE="https://github.com/$OWNER/claudio/archive/refs/tags/$TAG.tar.gz"
echo "==> hashing $ARCHIVE"
# GitHub generates the archive on first request; give it a moment if it 404s.
SHA=""
for attempt in 1 2 3 4 5; do
  SHA=$(curl -fsSL "$ARCHIVE" 2>/dev/null | shasum -a 256 | awk '{print $1}') || SHA=""
  [ -n "$SHA" ] && [ "$SHA" != "$(printf '' | shasum -a 256 | awk '{print $1}')" ] && break
  echo "    not ready yet (attempt $attempt), waiting..."
  sleep 5
  SHA=""
done
[ -n "$SHA" ] || { echo "error: could not download the tag archive" >&2; exit 1; }
echo "    sha256 $SHA"

echo "==> updating the formula"
sed -i '' "s|^  url \".*\"|  url \"$ARCHIVE\"|" Formula/claudio.rb
sed -i '' "s|^  sha256 \".*\"$|  sha256 \"$SHA\"|" Formula/claudio.rb
grep -q "$SHA" Formula/claudio.rb || { echo "error: formula not updated" >&2; exit 1; }

git add Formula/claudio.rb
git commit -q -m "Formula: point at $TAG"
git push origin HEAD

cat <<EOS

Released $VERSION.

Install it:
  brew tap $OWNER/claudio https://github.com/$OWNER/claudio
  brew install claudio
  claudio setup

Already tapped? Then:
  brew update && brew upgrade claudio
EOS
