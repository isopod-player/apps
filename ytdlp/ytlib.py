# SPDX-License-Identifier: GPL-2.0-or-later
"""What isoPod's list apps that play from YouTube share: yt-dlp, loaded once and in the
background, the questions-and-answers loop isoPod talks with, the app's kept state, and
fetching a newer yt-dlp.

An app (youtube.py) lies beside this, with yt-dlp's zipimport release in
share/yt-dlp and QuickJS-NG's qjs in bin/, as ytdlp/build.sh leaves them. It answers isoPod
on stdout, one JSON line each, and ends when stdin closes; anything else it would print
goes to stderr, which is isopodd's log.
"""

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
import zipfile

APP = os.path.dirname(os.path.abspath(sys.argv[0]))
DATA = os.environ.get("ISOPOD_APP_DATA") or os.path.expanduser("~")
BUNDLED = os.path.join(APP, "share", "yt-dlp")
UPDATED = os.path.join(DATA, "yt-dlp")
QJS = os.path.join(APP, "bin", "qjs")
RELEASES = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
# A 640x480 screen: up to 480p, H.264 where there is a choice (the CPU decodes it), and
# AAC beside it. A live stream comes whole, as HLS.
FORMAT = ("bv*[height<=480][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<=480][vcodec^=avc1]/"
          "bv*[height<=480]+ba/b[height<=480]/b")

TEXT = {
    "ko": {"update": "yt-dlp 새로 받기", "latest": "yt-dlp {v}, 가장 새것입니다.",
           "updated": "yt-dlp를 {v}(으)로 바꿨습니다. 다음에 열 때부터 씁니다.",
           "update_failed": "yt-dlp를 받지 못했습니다: {e}", "loading": "yt-dlp를 불러오지 못했습니다: {e}",
           "age": "연령 인증이 필요한 영상입니다.", "private": "비공개 영상입니다.",
           "upcoming": "아직 시작하지 않은 방송입니다.", "unavailable": "볼 수 없는 영상입니다.",
           "member": "채널 회원만 볼 수 있는 영상입니다.", "region": "이 나라에서는 볼 수 없는 영상입니다.",
           "network": "연결하지 못했습니다.", "live": "실시간", "views": "조회수 {n}"},
    "en": {"update": "Update yt-dlp", "latest": "yt-dlp {v} is the latest.",
           "updated": "yt-dlp is now {v}, from the next start.",
           "update_failed": "Could not update yt-dlp: {e}", "loading": "Could not load yt-dlp: {e}",
           "age": "This video needs age verification.", "private": "This video is private.",
           "upcoming": "This live stream has not begun.", "unavailable": "This video is unavailable.",
           "member": "This video is for channel members.", "region": "This video is not available here.",
           "network": "Could not connect.", "live": "Live", "views": "{n} views"},
}
TROUBLE = (("Sign in to confirm your age", "age"), ("age-restricted", "age"), ("Private video", "private"),
           ("will begin", "upcoming"), ("Premieres in", "upcoming"), ("members-only", "member"),
           ("Join this channel", "member"), ("not made this video available in your country", "region"),
           ("geo restrict", "region"), ("Unable to download", "network"), ("timed out", "network"),
           ("Video unavailable", "unavailable"), ("not available", "unavailable"))


class Trouble(Exception):
    """Something to tell the person, by its key in TEXT."""

    def __init__(self, key, **args):
        super().__init__(key)
        self.key = key
        self.args_ = args


# --- What is kept ----------------------------------------------------------------------

class State:
    """A JSON object of lists, kept in the app's data folder."""

    def __init__(self, name, keys, limits=None):
        self.path = os.path.join(DATA, name)
        self.limits = limits or {}
        try:
            with open(self.path, encoding="utf-8") as f:
                found = json.load(f)
        except (OSError, ValueError):
            found = {}
        self.data = {k: found.get(k) if isinstance(found.get(k), type(v)) else v for k, v in keys.items()}

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self):
        os.makedirs(DATA, exist_ok=True)
        with open(self.path + ".part", "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(self.path + ".part", self.path)

    def remember(self, key, value, same):
        """Put a value first in a kept list, taking out what it replaces."""
        rest = [v for v in self.data[key] if not same(v)]
        self.data[key] = [value] + rest[:self.limits.get(key, 1000) - 1]
        self.save()


# --- yt-dlp -----------------------------------------------------------------------------

def zip_version(path):
    try:
        with zipfile.ZipFile(path) as z:
            m = re.search(r"__version__\s*=\s*'([^']+)'", z.read("yt_dlp/version.py").decode())
            return m.group(1) if m else ""
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""


def newest_yt_dlp():
    """The yt-dlp this app came with, or a newer one fetched since."""
    found = [(zip_version(p), p) for p in (BUNDLED, UPDATED) if os.path.exists(p)]
    return max(found) if found else ("", BUNDLED)


class Log:
    """yt-dlp's words go to the log, never to stdout."""

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        if "Preferring" not in msg:  # the language asked for, every time
            print("yt-dlp:", msg, file=sys.stderr)

    def error(self, msg):
        print("yt-dlp:", msg, file=sys.stderr)


class Library:
    """yt-dlp, imported once in the background: it takes seconds on the device, which a
    first search would otherwise wait for."""

    def __init__(self):
        self.version, self.path = newest_yt_dlp()
        self.module = None
        self.error = None
        self.ready = threading.Event()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            sys.path.insert(0, self.path)
            import yt_dlp
            self.module = yt_dlp
        except Exception as e:  # a broken download should not end the app
            self.error = e
        self.ready.set()

    def ydl(self, lang, **options):
        self.ready.wait()
        if self.module is None:
            raise Trouble("loading", e=self.error)
        return self.module.YoutubeDL({
            "quiet": True, "no_warnings": True, "logger": Log(), "noplaylist": True,
            "socket_timeout": 20, "js_runtimes": {"quickjs": {"path": QJS}},
            "extractor_args": {"youtube": {"lang": [lang]}}, **options})

    def flat(self, url, lang, first=1, last=50):
        """A list (search, channel, playlist) without looking into each video."""
        with self.ydl(lang, extract_flat="in_playlist", playlist_items=f"{first}-{last}") as y:
            return extract(y, url)

    def streams(self, video_id, lang):
        with self.ydl(lang, format=FORMAT) as y:
            return extract(y, "https://www.youtube.com/watch?v=" + video_id)

    def play(self, video_id, lang):
        """isoPod's answer for a video: the picture, the sound beside it, and the headers."""
        info = self.streams(video_id, lang)
        chosen = info.get("requested_formats") or [info]
        video = next((f for f in chosen if f.get("vcodec") not in (None, "none")), chosen[0])
        audio = next((f for f in chosen if f is not video and f.get("acodec") not in (None, "none")), None)
        answer = {"url": video["url"], "title": info.get("title") or video_id,
                  "headers": video.get("http_headers") or info.get("http_headers") or {}}
        if audio:
            answer["audio"] = audio["url"]
        return answer, info


def extract(y, url):
    try:
        return y.extract_info(url, download=False)
    except Exception as e:
        message = str(e)
        for words, key in TROUBLE:
            if words.lower() in message.lower():
                raise Trouble(key) from None
        print("ytlib:", url, message, file=sys.stderr)
        raise Trouble("unavailable") from None


def videos(result):
    """The videos of a flat list, leaving out channels, playlists and the like."""
    return [e for e in result.get("entries") or [] if isinstance(e, dict) and e.get("id") and
            (e.get("ie_key") in (None, "Youtube") or "watch?v=" in (e.get("url") or ""))]


def update(library, lang):
    """The latest yt-dlp from its releases, checked against their checksums, for the next
    start: YouTube changes, and yt-dlp follows it within days. A page saying how it went."""
    t = TEXT[lang]

    def page(words):
        return {"title": t["update"], "items": [], "empty": words}
    try:
        sums = urllib.request.urlopen(RELEASES + "SHA2-256SUMS", timeout=30).read().decode()
        digest = next(line.split()[0] for line in sums.splitlines() if line.split()[1:] == ["yt-dlp"])
        body = urllib.request.urlopen(RELEASES + "yt-dlp", timeout=120).read()
    except (OSError, ValueError, StopIteration) as e:
        return page(t["update_failed"].format(e=e))
    if hashlib.sha256(body).hexdigest() != digest:
        return page(t["update_failed"].format(e="checksum"))
    os.makedirs(DATA, exist_ok=True)
    with open(UPDATED + ".part", "wb") as f:
        f.write(body)
    version = zip_version(UPDATED + ".part")
    if not version or version <= library.version:
        os.unlink(UPDATED + ".part")
        return page(t["latest"].format(v=library.version))
    os.replace(UPDATED + ".part", UPDATED)
    return page(t["updated"].format(v=version))


# --- Words -------------------------------------------------------------------------------

def clock(seconds):
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        return ""
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def views(n, lang):
    if not isinstance(n, int):
        return ""
    units = ((100_000_000, "억"), (10_000, "만"), (1_000, "천")) if lang == "ko" else \
        ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K"))
    for unit, word in units:
        if n >= unit:
            return TEXT[lang]["views"].format(n=f"{n / unit:.1f}".rstrip("0").rstrip(".") + word)
    return TEXT[lang]["views"].format(n=n)


def length(entry, lang):
    return TEXT[lang]["live"] if entry.get("live_status") == "is_live" else clock(entry.get("duration"))


# --- Questions and answers --------------------------------------------------------------

def serve(page, play, langs=("ko", "en")):
    """isoPod's questions on stdin, answered on stdout: page(path, query, lang) and
    play(id, lang) give the answer, or raise Trouble for words to show instead."""
    out = sys.stdout
    sys.stdout = sys.stderr  # stdout is for answers only
    name = os.path.basename(sys.argv[0])
    for line in sys.stdin:
        try:
            question = json.loads(line)
        except ValueError:
            continue
        if not isinstance(question, dict):
            continue
        lang = question.get("lang") if question.get("lang") in langs else langs[-1]
        started = time.monotonic()
        try:
            if question.get("op") == "play":
                answer = play(str(question.get("play", "")), lang)
            else:
                answer = page(str(question.get("path") or "/"), question.get("query"), lang)
        except Trouble as e:
            answer = {"error": TEXT[lang][e.key].format(**e.args_)}
        except Exception as e:  # one bad answer should not end the app
            print(name, repr(e), file=sys.stderr)
            answer = {"error": TEXT[lang]["unavailable"]}
        print(f"{name}: {question.get('op')} {question.get('path') or question.get('play')} "
              f"{time.monotonic() - started:.1f}s", file=sys.stderr)
        answer["id"] = question.get("id")
        out.write(json.dumps(answer, ensure_ascii=False) + "\n")
        out.flush()
