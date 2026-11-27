# Releasing Glowtrack

One command does a release:

```
tools/release.sh 3.2.0 notes.md --dry-run     # checks only, changes nothing
tools/release.sh 3.2.0 notes.md               # bumps, tests, builds, then asks before publishing
```

`notes.md` is the release description shown on GitHub (what changed, how to install, what is needed;
copy the previous release's notes as a starting point).

What the script does, in order:

1. Checks `gh` is signed in, the working tree is clean, and the version is newer than the latest release.
2. Runs the tests.
3. Sets the version in `server/config.py` and `mac/Info.plist` (they must agree; a test checks it) and runs the tests again.
4. Builds the five downloads with `mac/build.sh --dist` (Classic and designs A to D). Each app runs on Apple
   silicon and on Intel Macs, and the script checks the build carries the new version and both chips.
5. Commits the bump locally, then **stops and asks you to type the version** before anything is public.
6. Pushes the code to the public repository as one new commit with your GitHub no-reply address, and
   creates the release with the five zips.

It never pushes or publishes without the confirmation (unless you pass `--yes`).

## Things to know

- Pushing the automatic-checks file `.github/workflows/tests.yml` needs the GitHub CLI's `workflow` permission.
  Grant it once with `gh auth refresh -h github.com -s workflow` (it opens a browser page for you to approve).

- The public repository and this local repository have different histories on purpose (the local history
  contains personal addresses); the script publishes a copy of the current files, not your local commits.
- The first `--dist` build downloads the two Pillow wheels (Apple silicon and Intel) from PyPI, checks their
  published checksums and joins them (`mac/universal_pillow.py`). They are cached in `build/cache`.
- The apps are not notarised, so the release notes should keep the "right-click, Open the first time" line.
- A release should also be tried on a Mac that has never run Glowtrack before publishing, when you can.
