# Tonegrid

A Spotify terminal client with ASCII art. One Python file, standard library only.

![Tonegrid playing in a terminal](docs/screenshot.png)

*Demo mode (`--demo`): mock library, same interface as the real thing.*

**Live demo (mock library, runs in your browser):** https://otisranson.github.io/Tonegrid/

- Full-screen curses player: animated ASCII art, progress bar, spectrum bars, playlists, history, artist radio
- Plays audio in the terminal through [spotifyd](https://docs.spotifyd.rs), which Tonegrid starts and stops for you
- Album art rendered as ASCII when [Pillow](https://pypi.org/project/Pillow/) is installed; otherwise a plasma generated from the track id
- OAuth with PKCE, so there is no client secret to store

## Quick start

Try it first, no account needed:

```
git clone https://github.com/otisranson/Tonegrid.git
cd Tonegrid
python3 tonegrid.py --demo
```

### What you need

- Linux, macOS or WSL2 (it uses `curses`), Python 3 (developed on 3.14) and a terminal with Unicode and 256 colors, at least about 120 columns wide
- A **Spotify Premium** account. Spotify requires it both for playback control and for owning a developer app
- For terminal audio: spotifyd (step 3)

### 1. Create a Spotify app (once, free)

1. Go to <https://developer.spotify.com/dashboard> and log in.
2. **Create app**. Any name works. Don't put "Spotify" in the name.
3. Set the **Redirect URI** to exactly `http://127.0.0.1:8888/callback` and click Add. It must be `127.0.0.1`, not `localhost`.
4. Tick **Web API**, save, then open **Settings** and copy the **Client ID**. You don't need the secret.

A new app is in "development mode": it works for your own account, and you can add up to 5 other
users under **User Management**.

### 2. Log in

```
python3 tonegrid.py login --client-id YOUR_CLIENT_ID
```

Your browser opens Spotify's consent page. On WSL, or any machine where it doesn't open, paste the
printed URL into a browser. The token is stored in `~/.config/tonegrid/auth.json` (mode 600);
`python3 tonegrid.py logout` deletes it.

### 3. Set up terminal audio (optional)

Spotify's Web API is only a remote control, so something has to play the sound. Without this step
Tonegrid controls another device (open Spotify on your phone or desktop and start a track once).

1. Install [spotifyd](https://github.com/Spotifyd/spotifyd/releases) (the `default` build for your
   platform) and put it on your `PATH` or in `~/.local/bin`:
   ```
   tar xzf spotifyd-linux-x86_64-default.tar.gz
   install -m755 spotifyd ~/.local/bin/
   ```
2. On Linux it needs the PulseAudio client library: `sudo apt install libpulse0`. WSL2 plays audio
   through WSLg, which works out of the box on current Windows 11.
3. Log spotifyd in, once. This is its own browser login and doesn't need your Client ID:
   ```
   python3 tonegrid.py setup
   ```

### 4. Run it

```
python3 tonegrid.py
```

Tonegrid starts spotifyd, which appears in Spotify as a device called "tonegrid", and stops it when
you quit. If nothing else is playing it claims playback for the terminal. Press `d` to move
playback to the terminal at any time.

If spotifyd is missing, not set up or crashes, Tonegrid keeps running as a remote control and
shows the reason on the bottom line (`d` restarts it). Use `--no-player` to skip the daemon.

Other commands:

```
python3 tonegrid.py now      # print the current track as ASCII art and exit
python3 tonegrid.py --demo   # offline mock library
```

## Keys

| key | action | key | action |
|---|---|---|---|
| space | play / pause | `l` | playlists |
| `n` / `p` | next / previous | `h` | history (recently played) |
| `←` / `→` | seek 5s | `/` | artist radio (see below) |
| `+` / `-` | volume | `↑↓` `j k` | move in list |
| `s` / `r` | shuffle / repeat | enter | open / play |
| `d` | play in this terminal | backspace | back |
| `q` | quit | | |

**Artist radio:** press `/`, type an artist name, pick a result and press enter. Recent artists are
listed, and `↑`/`↓` fills the box from them.

## Troubleshooting

| you see | what it means |
|---|---|
| `403 Forbidden` opening a playlist, then it plays instead | Spotify only lets development-mode apps read the tracks of playlists you own or collaborate on. Tonegrid plays the whole playlist instead. Copy a playlist into your own library to browse its tracks. |
| `nothing playing` / `No active device` | Nothing is active. Press `d`, or open Spotify on any device and start a track once. |
| `terminal player not set up - run: tonegrid.py setup` | Do step 3. |
| `spotifyd not installed` | Do step 3, or use another device. |
| `terminal player stopped (exit N)` | spotifyd crashed. Read `~/.config/tonegrid/spotifyd.log`, then press `d` to restart. |
| `History needs a new permission` | You logged in before history existed. Run the `login` command again. |
| `INVALID_CLIENT: Invalid redirect URI` at login | The redirect URI in the dashboard must be exactly `http://127.0.0.1:8888/callback`. |
| A 403 on playback commands | Playback control needs Premium and an active device. |

## Notes

- **Artist radio** is a best effort. Spotify's Web API has no radio endpoint, so Tonegrid plays and shuffles the artist and, with the built-in player, spotifyd's autoplay carries on with similar music after it runs out. On other devices Spotify's own autoplay setting decides what follows.
- Search is capped at 10 results by Spotify for development-mode apps.
- The spectrum bars are decorative, seeded from the track id. Spotify does not expose live audio or audio analysis to third-party apps.
- Spotify's rules for new apps keep changing; errors shown on the bottom line are Spotify's own messages.

MIT licensed.
