# Contributing

Thanks for helping with Glowtrack! It's a small hobby project, so keep changes focused.

## Setup

```
git clone <this repo> ~/GoveeSpotifySync
cd ~/GoveeSpotifySync
/usr/bin/python3 -m pip install --user Pillow
/usr/bin/python3 server/app.py        # dashboard at http://127.0.0.1:8765
```

Edit anything in `server/`; the server reloads itself. Dashboard files in `server/web/`
are read fresh on each page load. The menu-bar app is in `mac/` (`mac/build.sh`).

## Before sending a change

- Run the tests: `/usr/bin/python3 -m unittest discover tests` (no lamps or Spotify needed).
- Added new Tailwind classes? Rebuild the styles: `/usr/bin/python3 tools/build_tailwind.py`.
- Keep the server dependency-free apart from Pillow.
- Anything that sends to the lamps goes through `engine.py` only.
- Changed one of the designs? Run `tools/layout-lint.js` in the page (see its header) and go through
  `docs/design-review-prompt.md` before sending it.
- Don't commit personal data (lamp IPs, tokens, config files).

## Reporting problems

Use **Report a problem** in Settings (or the menu bar icon): it opens the GitHub form with your version
and design already filled in. Please add your macOS version, the player you used (Spotify, Apple Music,
a browser...) and the last lines of `~/Library/Logs/GoveeSpotifySync.log`. Tried WiZ, LIFX or WLED? There is
a short test-report form for that too, and "it just worked" is a useful report.

Security issues (e.g. a way to control someone's lamps from another device): please report
privately to the maintainer rather than in a public issue.

## Editing the designs

`server/web/themes.js` and `themes.css` are the source of the four designs (they were first generated from
a mockup, but that pipeline is gone). Edit them directly, then follow the checks above: run
`tools/layout-lint.js` and look at every screen, including with a very long title.

## Releasing

`tools/release.sh <version> <notes.md>` does the whole release; see [docs/releasing.md](docs/releasing.md).
