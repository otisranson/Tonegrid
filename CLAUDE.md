# Tonegrid: future ideas

Deferred work, in rough priority order. Constraints below come from Spotify's development-mode
API limits (see README "Notes"), which shape what is possible.

## Real spectrum bars

The bars are decorative (seeded from the track id) because Spotify gives apps no audio analysis.
When playback is on the built-in spotifyd device, the audio is local and can be analysed:

1. Start spotifyd with `--backend pipe --audio-format s16` so it writes raw PCM to a FIFO.
2. Read the FIFO in a thread, play the audio through libpulse-simple via `ctypes`
   (no external tools or numpy needed), and keep the FFT off the audio thread.
3. Pure-Python FFT over the latest samples at about 20 fps; delay the bars slightly to match the
   audio buffer.
4. Keep the current fake bars as the fallback (other devices, or no audio flowing) and add a flag
   to turn real bars off.

Open questions: CPU cost of a pure-Python FFT, whether the volume keys still work on the pipe
backend, and audio latency under WSLg. Only works for the terminal device, since audio from other
devices never passes through this machine.

## Better artist radio (Last.fm)

Radio is currently "play and shuffle the artist, then rely on spotifyd's `--autoplay`". Spotify has
no radio, recommendations or related-artists endpoint for new apps. If autoplay stays on one
artist or repeats:

1. Read a free Last.fm API key from an environment variable; without it, keep the current behaviour.
2. `artist.getSimilar` for the chosen artist (about 10 similar artists).
3. Search each on Spotify (search is capped at 10 results), collect a few tracks each, and play
   the shuffled list as a URI queue.

ListenBrainz/MusicBrainz are a keyless alternative if the data quality is good enough.

## Smaller items

- **Narrow terminals:** the key-hint footer is about 117 characters and is cut off below that
  width. Wrap it or shorten it.
- **Liked Songs:** list and play the user's saved tracks (their own data, so the dev-mode playlist
  restriction should not apply).
- **Queue view:** show what plays next via the player queue endpoint. Untested whether it works for
  playlists the user does not own.
- **Disambiguate artists:** search can list two artists with the same name (for example two
  "Dawncall"); show genres or another detail on each row.
- **Consistent list format:** History shows `artist - track`, playlist track lists still show
  `track - artist`; decide on one.
- **macOS:** spotifyd builds exist but the player path is untested there.
