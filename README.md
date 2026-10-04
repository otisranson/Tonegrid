# Sonar

A Spotify terminal client with ASCII art. One Python file, standard library only.

**Live demo (mock library, runs in your browser):** https://otisranson.github.io/Sonar/

- Full-screen curses player: animated ASCII art, progress bar, spectrum bars, playlists, search
- Album art rendered as ASCII when [Pillow](https://pypi.org/project/Pillow/) is installed; otherwise a plasma generated from the track id
- OAuth with PKCE, so there is no client secret to store
- `sonar --demo` runs against an offline mock library, so you can try it without an account

## Use

```
python3 sonar.py --demo                  # try it, no account
python3 sonar.py login --client-id ID    # once
python3 sonar.py                         # player
python3 sonar.py now                     # print current track as ASCII art
```

Create a free app at <https://developer.spotify.com/dashboard> with redirect URI
`http://127.0.0.1:8888/callback`, and use its client id. Playback control needs
**Spotify Premium** and an active device (open any Spotify app once). Tokens are stored in
`~/.config/sonar/auth.json` (mode 600); `sonar logout` deletes them.

## Keys

| key | action | key | action |
|---|---|---|---|
| space | play / pause | `l` | playlists |
| `n` / `p` | next / previous | `/` | search |
| `←` / `→` | seek 5s | `↑↓` `j k` | move in list |
| `+` / `-` | volume | enter | open / play |
| `s` / `r` | shuffle / repeat | backspace | back |

## Notes

- The spectrum bars are decorative, seeded from the track id. Spotify does not expose live audio to third-party apps.
- Tested against the mock backend only; the live Spotify calls follow the public Web API but have not been exercised against a real account.

MIT licensed.
