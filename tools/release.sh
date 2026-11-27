#!/bin/bash
# Publishes a Glowtrack release: bumps the version, runs the tests, builds the five self-contained
# downloads, pushes the code to the public repository and creates the GitHub release.
#
#   tools/release.sh <version> <release-notes.md> [--dry-run] [--yes]
#
#   tools/release.sh 3.2.0 notes.md --dry-run    check everything, change nothing
#   tools/release.sh 3.2.0 notes.md              asks before it pushes and publishes
#
# Needs: the GitHub CLI (gh) signed in with push rights to the public repository, Xcode command-line tools,
# and a clean git working tree. The public copy is committed as one new commit with your GitHub
# no-reply address, the same way earlier releases were (see docs/releasing.md).
set -euo pipefail

REPO="omerham/glowtrack"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

die() { echo "Stopped: $*" >&2; exit 1; }
[[ $# -ge 2 ]] || die "usage: tools/release.sh <version> <notes.md> [--dry-run] [--yes]"
VERSION="$1"; NOTES="$2"; DRY=0; YES=0
shift 2
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --yes) YES=1 ;;
    *) echo "unknown option: $a"; exit 1 ;;
  esac
done

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "give a version like 3.2.0   (usage: tools/release.sh <version> <notes.md> [--dry-run] [--yes])"
[[ -f "$NOTES" ]] || die "release notes file not found: $NOTES"
command -v gh >/dev/null || die "the GitHub CLI (gh) is not installed"
gh auth status >/dev/null 2>&1 || die "gh is not signed in (run: gh auth login)"
[[ -z "$(git status --porcelain)" ]] || die "the working tree has uncommitted changes; commit or stash them first"

CURRENT="$(sed -n 's/^VERSION = "\(.*\)".*/\1/p' server/config.py)"
LATEST="$(gh release view --repo "$REPO" --json tagName -q .tagName 2>/dev/null | sed 's/^v//' || true)"
newer() { [[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" == "$1" && "$1" != "$2" ]]; }
newer "$VERSION" "${LATEST:-0.0.0}" || die "$VERSION is not newer than the latest release (${LATEST:-none})"

echo "Release $VERSION  (code says $CURRENT, latest published ${LATEST:-none})"
echo "Notes: $NOTES"

echo "-> tests"
/usr/bin/python3 -m unittest discover -s tests 2>&1 | tail -3 | grep -q "^OK" || die "the tests do not pass"

if [[ "$DRY" == "1" ]]; then
  echo "Dry run: checks passed. Nothing was changed, built or published."
  exit 0
fi

echo "-> bump the version"
sed -i '' "s/^VERSION = \"[^\"]*\"/VERSION = \"$VERSION\"/" server/config.py
sed -i '' "s|<key>CFBundleShortVersionString</key><string>[^<]*</string>|<key>CFBundleShortVersionString</key><string>$VERSION</string>|; s|<key>CFBundleVersion</key><string>[^<]*</string>|<key>CFBundleVersion</key><string>$VERSION</string>|" mac/Info.plist
/usr/bin/python3 -m unittest discover -s tests 2>&1 | tail -3 | grep -q "^OK" || die "the tests fail after the version bump"

echo "-> build the downloads (Apple silicon and Intel in one app)"
mac/build.sh --dist >/dev/null
ZIPS=(build/dist/Glowtrack-a.zip build/dist/Glowtrack-b.zip build/dist/Glowtrack-c.zip build/dist/Glowtrack-d.zip build/dist/Glowtrack-classic.zip)
for z in "${ZIPS[@]}"; do [[ -s "$z" ]] || die "missing $z"; done
CHECK="$(mktemp -d)"; unzip -q "${ZIPS[0]}" -d "$CHECK"
grep -q "VERSION = \"$VERSION\"" "$CHECK/Glowtrack.app/Contents/Resources/server/config.py" || die "the built app does not carry version $VERSION"
lipo -info "$CHECK/Glowtrack.app/Contents/MacOS/Glowtrack" | grep -q "x86_64" || die "the built app is not universal"
rm -rf "$CHECK"

git add -A
git commit -q -m "$VERSION: version bump"

if [[ "$YES" != "1" ]]; then
  echo
  echo "Ready to publish $VERSION to https://github.com/$REPO (push the code, then create the release with 5 zips)."
  read -r -p "Type the version number to confirm: " ANSWER
  [[ "$ANSWER" == "$VERSION" ]] || die "not confirmed; the version bump is committed locally, nothing was published"
fi

echo "-> push the code"
WORK="$(mktemp -d)"
gh repo clone "$REPO" "$WORK/public" -- -q
mkdir -p "$WORK/exp-src"
git archive HEAD | tar -x -C "$WORK/exp-src"
# GitHub refuses a push that adds workflow files unless gh has the "workflow" permission; leave them out then
if ! gh auth status 2>&1 | grep -q "workflow"; then
  if [[ -d "$WORK/exp-src/.github/workflows" ]]; then
    echo "   (gh lacks the 'workflow' permission: not pushing .github/workflows this time; see docs/releasing.md)"
    rm -rf "$WORK/exp-src/.github/workflows"
  fi
fi
rsync -a --delete --exclude .git "$WORK/exp-src/" "$WORK/public/"
cd "$WORK/public"
git add -A
UID_NUM="$(gh api user -q .id)"; LOGIN="$(gh api user -q .login)"
git -c user.name="$LOGIN" -c user.email="${UID_NUM}+${LOGIN}@users.noreply.github.com" commit -q -m "$VERSION" || echo "(no code changes to push)"
git -c credential.helper= -c credential.helper='!gh auth git-credential' push -q

echo "-> create the release"
cd "$ROOT"
gh release create "v$VERSION" --repo "$REPO" --title "Glowtrack $VERSION" --notes-file "$NOTES" --latest "${ZIPS[@]}"
rm -rf "$WORK"
echo "Done: https://github.com/$REPO/releases/tag/v$VERSION"
