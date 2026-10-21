# SPDX-License-Identifier: GPL-2.0-or-later
"""What isoPod's list apps that play from YouTube share: yt-dlp, loaded once and in the
background, the questions-and-answers loop isoPod talks with, the app's kept state,
fetching a newer yt-dlp, and saving videos to watch without the network.

An app (youtube.py) lies beside this, with yt-dlp's zipimport release in share/yt-dlp and
QuickJS-NG's qjs and FFmpeg's ffmpeg in bin/, as ytdlp/build.sh leaves them. It answers
isoPod on stdout, one JSON line each, and ends when stdin closes; anything else it would
print goes to stderr, which is isopodd's log.
"""

import contextlib
import fcntl
import glob
import hashlib
import json
import os
import re
import subprocess
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
FFMPEG = os.path.join(APP, "bin", "ffmpeg")
VIDEOS = "/storage/videos"  # isoPod's Videos
RELEASES = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
WATCH = "https://www.youtube.com/watch?v="
HEIGHTS = (360, 480, 720, 1080)
HEIGHT = 480  # the screen's 640x480


def formats(height, only=""):
    """Up to that height, H.264 where there is a choice (the CPU decodes it) with AAC beside
    it; `only` narrows every choice, as to what can be saved."""
    h = f"[height<={height}]{only}"
    return "/".join((f"bv*{h}[vcodec^=avc1]+ba[acodec^=mp4a]{only}", f"b{h}[vcodec^=avc1]",
                     f"bv*{h}+ba{only}", f"b{h}", f"b{only}"))


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

    def about(self, video_id, lang):
        """A video's title, channel and the like, without picking its streams."""
        with self.ydl(lang) as y:
            try:
                return y.extract_info(WATCH + video_id, download=False, process=False)
            except Exception as e:
                return extract_failed(WATCH + video_id, e)

    def streams(self, video_id, lang, height=HEIGHT):
        with self.ydl(lang, format=formats(height)) as y:
            return extract(y, WATCH + video_id)

    def play(self, video_id, lang, height=HEIGHT):
        """isoPod's answer for a video: the picture, the sound beside it, and the headers."""
        info = self.streams(video_id, lang, height)
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
        return extract_failed(url, e)


def extract_failed(url, e):
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


# --- Saved videos --------------------------------------------------------------------------

class Saves:
    """Videos saved to watch without the network: in a folder of isoPod's Videos, so they
    are there and over the cable too. A process of its own does the saving (the app run with
    --save, calling work()), since isoPod stops a list app nobody asks anything of for five
    minutes; it leaves that process alone. The two share the list in saved.json, each
    changing it under a lock. An entry is the video's id, title, channel and length, the
    height asked for, and how it is going: waiting, saving (with percent), done (with file
    and size) or failed."""

    def __init__(self, folder):
        self.folder = os.path.join(VIDEOS, folder) if os.path.isdir(VIDEOS) else os.path.join(DATA, "videos")
        self.path = os.path.join(DATA, "saved.json")
        self.worker = None

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                found = json.load(f)
        except (OSError, ValueError):
            return []
        return [e for e in found if isinstance(e, dict) and e.get("id")] if isinstance(found, list) else []

    @contextlib.contextmanager
    def edit(self):
        """The list, written back when changed."""
        os.makedirs(DATA, exist_ok=True)
        with open(self.path + ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            entries = self._read()
            before = json.dumps(entries)
            yield entries
            if json.dumps(entries) != before:
                with open(self.path + ".part", "w", encoding="utf-8") as f:
                    json.dump(entries, f, ensure_ascii=False, indent=1)
                os.replace(self.path + ".part", self.path)

    def all(self):
        """Newest first; one whose file has gone (taken off over the cable, say) is let go."""
        entries = self._read()
        if any(e.get("state") == "done" and not os.path.exists(e.get("file") or "") for e in entries):
            with self.edit() as entries:
                entries[:] = [e for e in entries
                              if e.get("state") != "done" or os.path.exists(e.get("file") or "")]
        return entries

    def get(self, video_id):
        return next((e for e in self.all() if e["id"] == video_id), None)

    def add(self, about, height, lang):
        """Save a video, unless it is saved or on its way already: what it was before."""
        with self.edit() as entries:
            found = next((e for e in entries if e["id"] == about["id"]), None)
            if found and found.get("state") != "failed":
                return found
            entries[:] = [e for e in entries if e["id"] != about["id"]]
            entries.insert(0, {**about, "height": height, "lang": lang, "state": "waiting", "percent": 0})
        self.wake()
        return found

    def drop(self, video_id):
        """Stop saving a video, or delete it once saved: what it was."""
        with self.edit() as entries:
            found = next((e for e in entries if e["id"] == video_id), None)
            entries[:] = [e for e in entries if e["id"] != video_id]
        if found and found.get("state") != "saving":  # the saving process tidies up after itself
            self.clean(video_id)
        return found

    def clean(self, video_id):
        """A video's file, and the parts of one being saved."""
        for path in glob.glob(os.path.join(glob.escape(self.folder), "*" + glob.escape(f"[{video_id}]") + "*")):
            with contextlib.suppress(OSError):
                os.unlink(path)

    def wake(self):
        """Start the saving process, when something waits and none is at it."""
        if self.worker and self.worker.poll() is None:
            return
        if not any(e.get("state") in ("waiting", "saving") for e in self._read()) or self._busy():
            return
        with open(os.path.join(DATA, "saving.log"), "w") as log:
            self.worker = subprocess.Popen(
                [sys.executable, os.path.abspath(sys.argv[0]), "--save"], cwd=APP, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)

    def _busy(self):
        with open(os.path.join(DATA, "saving.lock"), "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            return False

    def work(self):
        """The saving process: one video after another, the oldest first, until none waits."""
        os.makedirs(DATA, exist_ok=True)
        held = open(os.path.join(DATA, "saving.lock"), "w")
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return  # another is at it
        library = Library()
        with self.edit() as entries:
            for e in entries:
                if e.get("state") == "saving":  # left by one that was stopped
                    e["state"] = "waiting"
        while True:
            with self.edit() as entries:
                job = next((e for e in reversed(entries) if e.get("state") == "waiting"), None)
                if job is None:
                    held.close()  # with the list locked: what is added from now on starts another
                    return
                job.update(state="saving", percent=0)
                job = dict(job)
            try:
                file, height = self._save(library, job)
            except Exception as e:
                cancelled = library.module and isinstance(e, library.module.utils.DownloadCancelled)
                if not cancelled:
                    print("ytlib: saving", job["id"], repr(e), file=sys.stderr)
                with self.edit() as entries:
                    for entry in entries:
                        if entry["id"] == job["id"] and entry.get("state") == "saving":
                            entry["state"] = "failed"
                if cancelled:
                    self.clean(job["id"])
                continue
            with self.edit() as entries:
                entry = next((e for e in entries if e["id"] == job["id"] and e.get("state") == "saving"), None)
                if entry:
                    entry.update(state="done", percent=100, file=file, size=os.path.getsize(file),
                                 height=height or entry.get("height"))
            if not entry:  # let go of while it was being put together
                self.clean(job["id"])

    def _save(self, library, job):
        """One video into the folder, as one MP4 file: its path and height."""
        os.makedirs(self.folder, exist_ok=True)
        total, got, shown = [0], {}, [time.monotonic()]

        def progress(d):
            if d.get("status") not in ("downloading", "finished"):
                return
            got[d.get("filename")] = d.get("downloaded_bytes") or d.get("total_bytes") or 0
            if time.monotonic() - shown[0] < 2:
                return
            shown[0] = time.monotonic()
            with self.edit() as entries:
                entry = next((e for e in entries if e["id"] == job["id"]), None)
                if not entry or entry.get("state") != "saving":
                    raise library.module.utils.DownloadCancelled("let go of")
                if total[0]:
                    entry["percent"] = min(99, int(100 * sum(got.values()) / total[0]))

        options = {"format": formats(job.get("height") or HEIGHT, "[protocol=https]"),
                   "merge_output_format": "mp4", "windowsfilenames": True,
                   "outtmpl": os.path.join(self.folder, "%(title).80B [%(id)s].%(ext)s"),
                   "progress_hooks": [progress], "retries": 10, "noprogress": True}
        if os.path.exists(FFMPEG):
            options["ffmpeg_location"] = FFMPEG
        with library.ydl(job.get("lang") or "en", **options) as y:
            info = extract(y, WATCH + job["id"])
            total[0] = sum(f.get("filesize") or f.get("filesize_approx") or 0
                           for f in info.get("requested_formats") or [info])
            info = y.process_ie_result(info, download=True)
        file = ((info.get("requested_downloads") or [{}])[0].get("filepath") or info.get("filepath") or
                y.prepare_filename(info))
        if not os.path.exists(file):
            raise OSError("no file after saving")
        return file, info.get("height")


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
