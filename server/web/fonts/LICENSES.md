# Fonts

The dashboard's fonts are stored here so the app never needs to contact Google's font servers
(`tools/bundle_fonts.py` fetched them from Google Fonts). Each family is licensed under the
**SIL Open Font License 1.1**; the full licence and copyright notice of each is in `licenses/`.

| Family | Used by | Licence file |
|---|---|---|
| Plus Jakarta Sans | Classic dashboard | `licenses/plus-jakarta-sans-OFL.txt` |
| JetBrains Mono | Classic dashboard | `licenses/jetbrains-mono-OFL.txt` |
| Archivo | Poster design | `licenses/archivo-OFL.txt` |
| Big Shoulders Display | Poster design | `licenses/big-shoulders-display-OFL.txt` |
| DM Mono | Poster and Stage designs | `licenses/dm-mono-OFL.txt` |
| Doto | Dot design | `licenses/doto-OFL.txt` |
| Geist Mono | Instrument design | `licenses/geist-mono-OFL.txt` |
| Instrument Sans | Instrument and Stage designs | `licenses/instrument-sans-OFL.txt` |
| Syne | Stage design | `licenses/syne-OFL.txt` |

Only the Latin character set is included (English and Western European text, numbers, punctuation).
Other scripts are drawn with the system font.
