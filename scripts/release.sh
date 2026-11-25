#!/bin/sh
# Publish a release of postloom:
#
#   sh scripts/release.sh 0.1.0
#
# Run it on an up-to-date main, in a clean clone. It checks everything, dates the
# version's changelog section, commits, tags vX.Y.Z and pushes. The tag starts
# .github/workflows/release.yml, which builds, tests the package, publishes it to PyPI
# and creates the GitHub release with the changelog's notes.
set -eu

fail() { echo "release: $*" >&2; exit 1; }

version="${1:-}"
[ -n "$version" ] || fail "say which version, e.g. sh scripts/release.sh 0.1.0"
cd "$(dirname "$0")/.."

current=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n 1)
[ "$version" = "$current" ] || fail "pyproject.toml says $current, not $version; change it first"
grep -q "^## \[$version\] - unreleased" CHANGELOG.md \
    || fail "CHANGELOG.md has no '## [$version] - unreleased' section"
[ "$(git branch --show-current)" = main ] || fail "switch to main first"
[ -z "$(git status --porcelain)" ] || fail "commit or stash your changes first"
git fetch --quiet origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main isn't the same as origin/main; pull or push first"
! git rev-parse --quiet --verify "refs/tags/v$version" >/dev/null || fail "v$version is already tagged"

sh scripts/check.sh

today=$(date +%Y-%m-%d)
sed "s/^## \[$version\] - unreleased/## [$version] - $today/" CHANGELOG.md > CHANGELOG.md.new
mv CHANGELOG.md.new CHANGELOG.md
git commit --quiet -m "Release $version" CHANGELOG.md
git tag -a "v$version" -m "postloom $version"
git push --quiet origin main "v$version"
echo "Tagged and pushed v$version. Follow the release under Actions -> Release."
