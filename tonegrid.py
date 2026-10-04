#!/usr/bin/env python3
"""tonegrid - a dependency-free Spotify terminal client with ASCII art.

    tonegrid login --client-id ID   authorize once (PKCE, no client secret)
    tonegrid                        full-screen player
    tonegrid now                    print the current track as ASCII art and exit
    tonegrid --demo                 offline mock library, no account needed

Playback control needs Spotify Premium and an active device (open any
Spotify app once). Album art uses Pillow if it is installed; otherwise the
art is generated from the track id.
"""
import argparse
import base64
import curses
import hashlib
import io
import json
import locale
import math
import os
import random
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    from PIL import Image  # optional
except ImportError:
    Image = None

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state "
          "user-read-currently-playing playlist-read-private")
CONF = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tonegrid" / "auth.json"

RAMP = " .,:;-=+*#%@"
BARS = " ▁▂▃▄▅▆▇█"


# --------------------------------------------------------------------------
# auth (Authorization Code + PKCE)
# --------------------------------------------------------------------------

def _post_form(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _save(tok):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    CONF.write_text(json.dumps(tok))
    CONF.chmod(0o600)


def login(client_id):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(8)
    url = ACCOUNTS + "/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "scope": SCOPES,
        "redirect_uri": REDIRECT, "state": state,
        "code_challenge_method": "S256", "code_challenge": challenge})
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            got.update({k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"tonegrid: authorized. You can close this tab.")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8888), H)
    print("Opening browser. If nothing happens, visit:\n" + url)
    webbrowser.open(url)
    srv.handle_request()
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        sys.exit("login failed: " + got.get("error", "state mismatch"))
    tok = _post_form(ACCOUNTS + "/api/token", {
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT,
        "client_id": client_id, "code_verifier": verifier})
    _save({"client_id": client_id, "access_token": tok["access_token"],
           "refresh_token": tok["refresh_token"], "expires_at": time.time() + tok["expires_in"]})
    print("Logged in. Run `tonegrid`.")


def access_token(force=False):
    if not CONF.exists():
        sys.exit("Not logged in. Run: tonegrid login --client-id <your Spotify app client id>\n"
                 "(or try `tonegrid --demo`)")
    tok = json.loads(CONF.read_text())
    if force or tok["expires_at"] - time.time() < 60:
        new = _post_form(ACCOUNTS + "/api/token", {
            "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
            "client_id": tok["client_id"]})
        tok["access_token"] = new["access_token"]
        tok["refresh_token"] = new.get("refresh_token", tok["refresh_token"])
        tok["expires_at"] = time.time() + new["expires_in"]
        _save(tok)
    return tok["access_token"]


# --------------------------------------------------------------------------
# backends: both expose the same small interface
#   state() -> dict | None      track, playing, progress_ms, volume, shuffle, repeat
#   toggle/next/prev/seek/volume/shuffle/repeat/play
#   playlists() / playlist_tracks(id) / search(q) / image(url)
# --------------------------------------------------------------------------

def norm_track(t):
    imgs = (t.get("album") or {}).get("images") or []
    return {"id": t.get("id") or t["uri"], "uri": t["uri"], "name": t["name"],
            "artists": ", ".join(a["name"] for a in t.get("artists", [])),
            "album": (t.get("album") or {}).get("name", ""),
            "duration_ms": t.get("duration_ms", 0),
            "art_url": imgs[-1]["url"] if imgs else None}  # smallest is plenty


class Spotify:
    def __init__(self):
        access_token()
        self.repeat_modes = ["off", "context", "track"]

    def req(self, method, path, params=None, retry=True):
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        r = urllib.request.Request(url, method=method, data=b"" if method in ("PUT", "POST") else None,
                                   headers={"Authorization": "Bearer " + access_token()})
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                body = resp.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:
                access_token(force=True)
                return self.req(method, path, params, retry=False)
            detail = ""
            try:
                detail = json.load(e).get("error", {}).get("message", "")
            except Exception:
                pass
            raise RuntimeError(f"{e.code} {detail or e.reason}")

    def put_json(self, path, params, body):
        r = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(params), method="PUT",
                                   data=json.dumps(body).encode(),
                                   headers={"Authorization": "Bearer " + access_token(),
                                            "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(r, timeout=15).read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{e.code} {e.reason} (Premium + an active device required)")

    def state(self):
        s = self.req("GET", "/me/player")
        if not s or not s.get("item"):
            return None
        return {"track": norm_track(s["item"]), "playing": s["is_playing"],
                "progress_ms": s.get("progress_ms") or 0,
                "volume": (s.get("device") or {}).get("volume_percent") or 0,
                "shuffle": s.get("shuffle_state", False), "repeat": s.get("repeat_state", "off")}

    def toggle(self, playing):
        self.req("PUT", "/me/player/pause" if playing else "/me/player/play")

    def next(self):
        self.req("POST", "/me/player/next")

    def prev(self):
        self.req("POST", "/me/player/previous")

    def seek(self, ms):
        self.req("PUT", "/me/player/seek", {"position_ms": int(ms)})

    def volume(self, v):
        self.req("PUT", "/me/player/volume", {"volume_percent": int(v)})

    def shuffle(self, on):
        self.req("PUT", "/me/player/shuffle", {"state": str(on).lower()})

    def repeat(self, cur):
        nxt = self.repeat_modes[(self.repeat_modes.index(cur) + 1) % 3]
        self.req("PUT", "/me/player/repeat", {"state": nxt})

    def play(self, track, context=None):
        if context:
            self.put_json("/me/player/play", {}, {"context_uri": context, "offset": {"uri": track["uri"]}})
        else:
            self.put_json("/me/player/play", {}, {"uris": [track["uri"]]})

    def playlists(self):
        out = self.req("GET", "/me/playlists", {"limit": 50})
        return [{"id": p["id"], "uri": p["uri"], "name": p["name"]} for p in out["items"] if p]

    def playlist_tracks(self, pid):
        try:  # endpoint was renamed; try the new name first
            out = self.req("GET", f"/playlists/{pid}/items", {"limit": 100})
        except RuntimeError:
            out = self.req("GET", f"/playlists/{pid}/tracks", {"limit": 100})
        rows = []
        for it in out["items"]:
            t = it.get("track") or it.get("item")
            if t and t.get("uri", "").startswith("spotify:track"):
                rows.append(norm_track(t))
        return rows

    def search(self, q):
        out = self.req("GET", "/search", {"q": q, "type": "track", "limit": 30})
        return [norm_track(t) for t in out["tracks"]["items"]]

    def image(self, url):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return r.read()
        except Exception:
            return None


class Mock:
    """Offline library; playback is simulated against the wall clock."""
    A = "Neon Static Glass Velvet Orbit Halogen Marrow Tidal Cinder Lumen Sable Quartz".split()
    B = "Garden Engine Drift Signal Harbor Meridian Parade Circuit Lantern Atlas Fever Echo".split()
    ARTISTS = ["The Parallax", "Lucid Cartographers", "Mono Tide", "Vera Halloran", "Static Orchard"]

    def __init__(self):
        rng = random.Random(7)
        self.lib = {}
        self.pls = []
        for i, pname in enumerate(["Late Night Compile", "Deep Focus", "Road Trip 2026", "Sunday Slow"]):
            tracks = []
            for j in range(12):
                name = f"{rng.choice(self.A)} {rng.choice(self.B)}"
                tid = f"mock{i}{j:02d}{abs(hash(name)) % 9999}"
                t = {"id": tid, "uri": "mock:" + tid, "name": name,
                     "artists": rng.choice(self.ARTISTS), "album": f"{rng.choice(self.A)} {rng.choice(self.B)}",
                     "duration_ms": rng.randint(150, 330) * 1000, "art_url": None}
                tracks.append(t)
                self.lib[tid] = t
            self.pls.append({"id": f"pl{i}", "uri": f"mock:pl{i}", "name": pname, "tracks": tracks})
        self.queue = list(self.pls[0]["tracks"])
        self.cur = 0
        self.playing = False
        self.pos = 0.0
        self.stamp = time.time()
        self.vol = 70
        self.shuf = False
        self.rep = "off"

    def _tick(self):
        now = time.time()
        if self.playing:
            self.pos += (now - self.stamp) * 1000
            while self.pos >= self.queue[self.cur]["duration_ms"]:
                self.pos -= self.queue[self.cur]["duration_ms"]
                self._advance(1, auto=True)
        self.stamp = now

    def _advance(self, d, auto=False):
        if auto and self.rep == "track":
            return
        if self.shuf:
            self.cur = random.randrange(len(self.queue))
        else:
            self.cur = (self.cur + d) % len(self.queue)

    def state(self):
        self._tick()
        return {"track": self.queue[self.cur], "playing": self.playing, "progress_ms": int(self.pos),
                "volume": self.vol, "shuffle": self.shuf, "repeat": self.rep}

    def toggle(self, playing):
        self._tick()
        self.playing = not self.playing

    def next(self):
        self._tick()
        self._advance(1)
        self.pos = 0

    def prev(self):
        self._tick()
        if self.pos > 3000:
            self.pos = 0
        else:
            self._advance(-1)
            self.pos = 0

    def seek(self, ms):
        self._tick()
        self.pos = max(0, min(ms, self.queue[self.cur]["duration_ms"] - 1))

    def volume(self, v):
        self.vol = max(0, min(100, v))

    def shuffle(self, on):
        self.shuf = on

    def repeat(self, cur):
        m = ["off", "context", "track"]
        self.rep = m[(m.index(cur) + 1) % 3]

    def play(self, track, context=None):
        self._tick()
        if context:
            pl = next(p for p in self.pls if p["uri"] == context)
            self.queue = list(pl["tracks"])
        else:
            self.queue = [track]
        self.cur = next(i for i, t in enumerate(self.queue) if t["id"] == track["id"])
        self.pos = 0
        self.playing = True

    def playlists(self):
        return [{k: p[k] for k in ("id", "uri", "name")} for p in self.pls]

    def playlist_tracks(self, pid):
        return next(p for p in self.pls if p["id"] == pid)["tracks"]

    def search(self, q):
        q = q.lower()
        return [t for t in self.lib.values() if q in (t["name"] + " " + t["artists"] + " " + t["album"]).lower()][:30]

    def image(self, url):
        return None


# --------------------------------------------------------------------------
# ASCII art
# --------------------------------------------------------------------------

def seed_of(s):
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big")


def xterm_from_rgb(r, g, b):
    q = lambda v: min(5, round(v / 255 * 5))
    return 16 + 36 * q(r) + 6 * q(g) + q(b)


class GenArt:
    """Animated plasma derived from the track id - deterministic per track."""

    def __init__(self, track_id):
        rng = random.Random(seed_of(track_id))
        self.k = [(rng.uniform(0.15, 0.6), rng.uniform(0.15, 0.6), rng.uniform(0, 6.28),
                   rng.uniform(-0.4, 0.4)) for _ in range(4)]
        h = rng.random()
        r, g, b = [int(255 * (0.5 + 0.5 * math.sin(6.28 * (h + o)))) for o in (0, 0.33, 0.66)]
        self.color = xterm_from_rgb(r, g, b)

    def render(self, w, h, t):
        rows = []
        for y in range(h):
            line = []
            for x in range(w):
                xx, yy = x / 2.0, y  # chars are ~2x taller than wide
                v = 0.0
                for fx, fy, ph, sp in self.k:
                    v += math.sin(xx * fx + yy * fy * 1.3 + ph + t * sp)
                v += math.sin(math.hypot(xx - w / 4, yy - h / 2) * 0.5 - t * 0.3)
                v = (v / 5 + 1) / 2
                line.append(RAMP[min(len(RAMP) - 1, int(v * len(RAMP)))])
            rows.append("".join(line))
        return rows


class ImgArt:
    """Still ASCII rendering of real cover art (needs Pillow)."""

    def __init__(self, data):
        im = Image.open(io.BytesIO(data)).convert("RGB").resize((64, 32))
        self.px = list(im.convert("L").getdata())
        r, g, b = Image.open(io.BytesIO(data)).convert("RGB").resize((1, 1)).getpixel((0, 0))
        m = max(r, g, b, 1)
        self.color = xterm_from_rgb(r * 255 // m, g * 255 // m, b * 255 // m)
        lo, hi = min(self.px), max(self.px)
        self.lo, self.span = lo, max(1, hi - lo)

    def render(self, w, h, t):
        rows = []
        for y in range(h):
            line = []
            for x in range(w):
                v = (self.px[(y * 32 // h) * 64 + x * 64 // w] - self.lo) / self.span
                line.append(RAMP[min(len(RAMP) - 1, int(v * len(RAMP)))])
            rows.append("".join(line))
        return rows


def spectrum(track_id, n, t, playing):
    rng = random.Random(seed_of(track_id))
    ph = [(rng.uniform(0.8, 3.0), rng.uniform(0, 6.28), rng.uniform(0.3, 1)) for _ in range(n)]
    amp = 1.0 if playing else 0.08
    out = []
    for i, (f, p, a) in enumerate(ph):
        env = 0.35 + 0.65 * math.exp(-i / (n * 0.7))  # bass-heavy tilt
        v = (math.sin(t * f + p) * 0.5 + 0.5) * (math.sin(t * 5.3 + i) * 0.25 + 0.75)
        out.append(max(0.0, min(1.0, v * env * a * amp)))
    return out


def fmt_ms(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


# --------------------------------------------------------------------------
# TUI
# --------------------------------------------------------------------------

class App:
    def __init__(self, backend):
        self.b = backend
        self.st = None
        self.st_at = time.time()
        self.msg = ""
        self.art = {}
        self.items = []          # list pane rows
        self.list_title = "Press l for playlists, / to search"
        self.list_kind = None    # "playlists" | "tracks"
        self.list_ctx = None
        self.back = None
        self.sel = 0
        self.prompt = None
        self.alive = True

    def bg(self, fn, *a, done=None):
        def run():
            try:
                r = fn(*a)
                if done:
                    done(r)
            except Exception as e:
                self.msg = str(e)[:120]
        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        while self.alive:
            try:
                s = self.b.state()
                self.st, self.st_at = s, time.time()
                if s and s["track"]["id"] not in self.art:
                    self.load_art(s["track"])
                if not s and not self.msg:
                    self.msg = "No active device - open Spotify somewhere and press play"
            except Exception as e:
                self.msg = str(e)[:120]
            time.sleep(1.0)

    def load_art(self, tr):
        self.art[tr["id"]] = GenArt(tr["id"])
        if Image and tr.get("art_url"):
            def done(data):
                if data:
                    self.art[tr["id"]] = ImgArt(data)
            self.bg(self.b.image, tr["art_url"], done=done)

    def progress(self):
        s = self.st
        if not s:
            return 0
        p = s["progress_ms"] + ((time.time() - self.st_at) * 1000 if s["playing"] else 0)
        return min(p, s["track"]["duration_ms"])

    # ---- actions
    def act(self, fn, *a, optimistic=None):
        if optimistic and self.st:
            self.st.update(optimistic)
            self.st_at = time.time()
        self.bg(fn, *a)

    def open_playlists(self):
        def done(pl):
            self.items, self.sel = pl, 0
            self.list_kind, self.list_title, self.back = "playlists", "Playlists", None
        self.bg(self.b.playlists, done=done)

    def open_tracks(self, pl):
        def done(tr):
            self.items, self.sel = tr, 0
            self.list_kind, self.list_title, self.list_ctx = "tracks", pl["name"], pl["uri"]
            self.back = self.open_playlists
        self.bg(self.b.playlist_tracks, pl["id"], done=done)

    def search(self, q):
        def done(tr):
            self.items, self.sel = tr, 0
            self.list_kind, self.list_title, self.list_ctx, self.back = "tracks", f'Search: "{q}"', None, None
        self.bg(self.b.search, q, done=done)

    def key(self, k):
        s = self.st
        if self.prompt is not None:
            if k in (10, 13, curses.KEY_ENTER):
                q, self.prompt = self.prompt.strip(), None
                if q:
                    self.search(q)
            elif k == 27:
                self.prompt = None
            elif k in (127, 8, curses.KEY_BACKSPACE):
                self.prompt = self.prompt[:-1]
            elif 32 <= k < 0x110000:
                self.prompt += chr(k)
            return
        self.msg = ""
        if k in (ord("q"), 3):
            self.alive = False
        elif k == ord(" ") and s:
            self.act(self.b.toggle, s["playing"], optimistic={"playing": not s["playing"],
                                                              "progress_ms": int(self.progress())})
        elif k == ord("n"):
            self.act(self.b.next)
        elif k == ord("p"):
            self.act(self.b.prev)
        elif k == curses.KEY_RIGHT and s:
            self.act(self.b.seek, self.progress() + 5000, optimistic={"progress_ms": int(self.progress() + 5000)})
        elif k == curses.KEY_LEFT and s:
            self.act(self.b.seek, max(0, self.progress() - 5000), optimistic={"progress_ms": int(max(0, self.progress() - 5000))})
        elif k in (ord("+"), ord("=")) and s:
            v = min(100, s["volume"] + 5)
            self.act(self.b.volume, v, optimistic={"volume": v})
        elif k in (ord("-"), ord("_")) and s:
            v = max(0, s["volume"] - 5)
            self.act(self.b.volume, v, optimistic={"volume": v})
        elif k == ord("s") and s:
            self.act(self.b.shuffle, not s["shuffle"], optimistic={"shuffle": not s["shuffle"]})
        elif k == ord("r") and s:
            self.act(self.b.repeat, s["repeat"])
        elif k == ord("l"):
            self.open_playlists()
        elif k == ord("/"):
            self.prompt = ""
        elif k in (curses.KEY_DOWN, ord("j")) and self.items:
            self.sel = min(len(self.items) - 1, self.sel + 1)
        elif k in (curses.KEY_UP, ord("k")) and self.items:
            self.sel = max(0, self.sel - 1)
        elif k in (curses.KEY_BACKSPACE, 127, 8) and self.back:
            self.back()
        elif k in (10, 13, curses.KEY_ENTER) and self.items:
            it = self.items[self.sel]
            if self.list_kind == "playlists":
                self.open_tracks(it)
            else:
                self.act(self.b.play, it, self.list_ctx)

    # ---- drawing
    def put(self, scr, y, x, text, attr=0):
        h, w = scr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                scr.addstr(y, x, text[:w - x - (1 if y == h - 1 else 0)], attr)
            except curses.error:
                pass

    def draw(self, scr):
        scr.erase()
        H, W = scr.getmaxyx()
        t = time.time()
        s = self.st
        top = min(16, max(8, H // 2))
        art_h = top - 2
        art_w = art_h * 2
        show_art = W >= art_w + 34
        x0 = art_w + 3 if show_art else 1
        accent = curses.color_pair(1)
        bold = curses.A_BOLD
        if s:
            tr = s["track"]
            art = self.art.get(tr["id"]) or GenArt(tr["id"])
            if curses.COLORS >= 256:
                curses.init_pair(1, art.color, -1)
            if show_art:
                for i, row in enumerate(art.render(art_w, art_h, t if s["playing"] else 0)):
                    self.put(scr, 1 + i, 1, row, accent)
            self.put(scr, 1, x0, tr["name"], bold)
            self.put(scr, 2, x0, tr["artists"])
            self.put(scr, 3, x0, tr["album"], curses.A_DIM)
            bw = max(10, min(W - x0 - 2, 60))
            frac = self.progress() / max(1, tr["duration_ms"])
            fill = int(frac * bw)
            self.put(scr, 5, x0, "█" * fill + "░" * (bw - fill), accent)
            self.put(scr, 6, x0, f"{fmt_ms(self.progress())} / {fmt_ms(tr['duration_ms'])}")
            icon = "▶ playing" if s["playing"] else "❚❚ paused"
            self.put(scr, 7, x0, f"{icon}   vol {s['volume']:>3}%   shuffle {'on' if s['shuffle'] else 'off'}   repeat {s['repeat']}")
            nb = max(8, min(W - x0 - 2, 48))
            sp = spectrum(tr["id"], nb, t, s["playing"])
            vh = max(1, art_h - 9)
            for row in range(vh):
                line = ""
                for v in sp:
                    lvl = v * vh * 8 - (vh - 1 - row) * 8
                    line += BARS[max(0, min(8, int(lvl)))]
                self.put(scr, 9 + row, x0, line, accent)
        else:
            self.put(scr, 2, x0, "tonegrid", bold)
            self.put(scr, 4, x0, "nothing playing")
        self.put(scr, top, 0, "─" * W, curses.A_DIM)
        self.put(scr, top + 1, 1, self.list_title, bold)
        rows = H - top - 4
        if rows > 0 and self.items:
            start = max(0, min(self.sel - rows // 2, len(self.items) - rows))
            for i, it in enumerate(self.items[start:start + rows]):
                idx = start + i
                if self.list_kind == "playlists":
                    label = it["name"]
                else:
                    label = f"{it['name']}  -  {it['artists']}  [{fmt_ms(it['duration_ms'])}]"
                self.put(scr, top + 2 + i, 1, ("> " if idx == self.sel else "  ") + label,
                         curses.A_REVERSE if idx == self.sel else 0)
        if self.prompt is not None:
            self.put(scr, H - 2, 1, "search: " + self.prompt + "_", bold)
        elif self.msg:
            self.put(scr, H - 2, 1, self.msg, curses.A_BOLD)
        self.put(scr, H - 1, 0, " space play/pause  n/p track  ←/→ seek  +/- vol  s shuffle  r repeat  l lists  / search  q quit",
                 curses.A_DIM)
        scr.refresh()


def tui(scr, backend):
    locale.setlocale(locale.LC_ALL, "")
    curses.curs_set(0)
    curses.use_default_colors()
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
    scr.timeout(80)
    scr.keypad(True)
    app = App(backend)
    threading.Thread(target=app.poll, daemon=True).start()
    app.open_playlists()
    while app.alive:
        app.draw(scr)
        k = scr.getch()
        if k != -1 and k != curses.KEY_RESIZE:
            app.key(k)


def cmd_now(backend):
    s = backend.state()
    if not s:
        sys.exit("nothing playing")
    tr = s["track"]
    art = GenArt(tr["id"])
    if Image and tr.get("art_url"):
        data = backend.image(tr["art_url"])
        if data:
            art = ImgArt(data)
    print("\n".join(art.render(48, 24, 0)))
    print(f"\n{tr['name']} - {tr['artists']}\n{tr['album']}")
    print(f"{fmt_ms(s['progress_ms'])} / {fmt_ms(tr['duration_ms'])}  {'playing' if s['playing'] else 'paused'}")


def main():
    ap = argparse.ArgumentParser(prog="tonegrid", description="Spotify in your terminal, in ASCII.")
    ap.add_argument("cmd", nargs="?", default="play", choices=["play", "now", "login", "logout"])
    ap.add_argument("--client-id", help="Spotify app client id (for `login`)")
    ap.add_argument("--demo", action="store_true", help="offline mock library")
    a = ap.parse_args()
    if a.cmd == "login":
        cid = a.client_id or os.environ.get("SPOTIFY_CLIENT_ID")
        if not cid:
            sys.exit("Pass --client-id (create a free app at developer.spotify.com/dashboard "
                     f"with redirect URI {REDIRECT})")
        return login(cid)
    if a.cmd == "logout":
        CONF.unlink(missing_ok=True)
        return print("Logged out.")
    backend = Mock() if a.demo else Spotify()
    if a.demo and a.cmd == "now":
        backend.toggle(False)
    if a.cmd == "now":
        return cmd_now(backend)
    try:
        curses.wrapper(tui, backend)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
