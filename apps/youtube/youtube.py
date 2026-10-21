#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""YouTube for isoPod, as a list app.

isoPod asks for pages and shows them as its own lists; a video it plays in its own player.
Pages: search (with isoPod's keyboard), the searches made lately, channels kept here and
each channel's videos, the videos watched, the videos saved, and settings. A video's own
page plays it, saves it and leads to its channel. There is no account. ytlib.py, beside
this, holds yt-dlp, the saving and the talk with isoPod.

A row that does something rather than open a page (save, clear, a setting) is one isoPod
plays; the answer is the words isoPod shows for it, so the page stays where it is.
"""

import sys
import urllib.parse

import ytlib
from ytlib import TEXT as LIB, HEIGHT, HEIGHTS, Library, Saves, State, length, videos, views

PER_PAGE = 20

TEXT = {
    "ko": {"search": "검색", "prompt": "찾을 영상", "recent": "최근 검색", "channels": "채널",
           "watched": "본 영상", "results": "'{q}' 검색 결과", "more": "더 보기", "channel": "채널",
           "keep": "채널 목록에 넣기", "drop": "채널 목록에서 빼기",
           "none": "결과가 없습니다. 로그인해야 볼 수 있는 검색어일 수도 있습니다.",
           "no_videos": "영상이 없습니다.", "no_watched": "아직 본 영상이 없습니다.",
           "play": "재생", "save": "저장", "unsave": "저장 취소", "delete": "저장한 영상 지우기",
           "save_again": "다시 저장", "saved": "저장한 영상", "no_saved": "저장한 영상이 없습니다.",
           "waiting": "저장 대기", "saving": "저장하는 중 {p}%", "failed": "저장하지 못했습니다",
           "started": "저장을 시작했습니다", "already": "이미 저장했습니다", "cancelled": "저장을 취소했습니다",
           "deleted": "저장한 영상을 지웠습니다", "not_saved": "저장한 영상이 아닙니다",
           "settings": "설정", "play_height": "재생 화질", "save_height": "저장 화질",
           "current": "사용 중", "set": "{what}: {h}p",
           "clear_recent": "검색 기록 지우기", "clear_history": "본 영상 기록 지우기",
           "cleared_recent": "검색 기록을 지웠습니다", "cleared_history": "본 영상 기록을 지웠습니다"},
    "en": {"search": "Search", "prompt": "Videos", "recent": "Recent searches", "channels": "Channels",
           "watched": "Watched", "results": "Results for '{q}'", "more": "More", "channel": "Channel",
           "keep": "Keep this channel", "drop": "Let this channel go",
           "none": "Nothing found. The search may need signing in.",
           "no_videos": "No videos.", "no_watched": "Nothing watched yet.",
           "play": "Play", "save": "Save", "unsave": "Stop saving", "delete": "Delete saved video",
           "save_again": "Save again", "saved": "Saved", "no_saved": "No saved videos.",
           "waiting": "Waiting to save", "saving": "Saving {p}%", "failed": "Could not save",
           "started": "Saving", "already": "Already saved", "cancelled": "Saving stopped",
           "deleted": "Saved video deleted", "not_saved": "Not a saved video",
           "settings": "Settings", "play_height": "Playback quality", "save_height": "Saving quality",
           "current": "In use", "set": "{what}: {h}p",
           "clear_recent": "Clear searches", "clear_history": "Clear watched",
           "cleared_recent": "Searches cleared", "cleared_history": "Watched cleared"},
}
ABOUT = ("id", "title", "channel", "channel_id", "duration", "live_status", "view_count")


def about(entry, **more):
    """What a video's page and rows show, from a list or from yt-dlp."""
    return {**{k: entry.get(k) for k in ABOUT if entry.get(k) is not None}, **more}


def video_item(entry, lang, channel=True, subtitle=None):
    """A row that opens a video: its title, with who made it and how long it is under it."""
    parts = [entry.get("channel") or entry.get("uploader")] if channel else []
    parts.append(length(entry, lang))
    if not channel:
        parts.append(views(entry.get("view_count"), lang))
    return {"title": entry.get("title") or entry["id"],
            "subtitle": subtitle or " · ".join(p for p in parts if p), "path": "/v/" + entry["id"]}


def size(n):
    return f"{n / 1e9:.1f}GB" if n >= 1e9 else f"{max(1, round(n / 1e6))}MB"


class YouTube:
    def __init__(self):
        self.library = Library()
        self.state = State("youtube.json", {"recent": [], "channels": [], "history": [],
                                            "play_height": HEIGHT, "save_height": HEIGHT},
                           {"recent": 8, "history": 50})
        self.saves = Saves("YouTube")
        self.seen = {}  # video id -> about it, from every list read
        self.channel_names = {}  # channel id -> name, from every list read

    def page(self, path, query, lang):
        t = TEXT[lang]
        parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/") if p]
        if query is not None:
            return self.search(query.strip(), 1, lang)
        if not parts:
            return self.home(lang)
        if parts[0] == "q" and len(parts) >= 2:
            return self.search(parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1, lang)
        if parts[0] == "c" and len(parts) >= 2:
            if len(parts) > 2 and parts[2] in ("keep", "drop"):
                self.keep(parts[1], parts[2] == "keep")
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            return self.channel(parts[1], page, lang)
        if parts[0] == "v" and len(parts) >= 2:
            return self.video(parts[1], lang)
        if parts[0] == "watched":
            for v in self.state["history"]:
                self.seen.setdefault(v["id"], v)
            items = [video_item(v, lang) for v in self.state["history"]]
            return {"title": t["watched"], "items": items, "empty": t["no_watched"]}
        if parts[0] == "saved":
            return self.saved(lang)
        if parts[0] == "settings":
            return self.settings(parts[1] if len(parts) > 1 else None, lang)
        if parts[0] == "update":
            return ytlib.update(self.library, lang)
        return {"title": "", "items": []}

    def home(self, lang):
        t = TEXT[lang]
        items = [{"title": t["search"], "search": "/search", "prompt": t["prompt"]}]
        if self.state["recent"]:
            items.append({"title": t["recent"], "header": True})
            items += [{"title": q, "path": "/q/" + urllib.parse.quote(q, safe="")} for q in self.state["recent"]]
        if self.state["channels"]:
            items.append({"title": t["channels"], "header": True})
            items += [{"title": c["name"], "path": "/c/" + c["id"]} for c in self.state["channels"]]
        items.append({"title": t["watched"], "path": "/watched"})
        saved = {"title": t["saved"], "path": "/saved"}
        saving = next((e for e in self.saves.all() if e.get("state") == "saving"), None)
        if saving:
            saved["subtitle"] = t["saving"].format(p=saving.get("percent", 0))
        items.append(saved)
        items.append({"title": t["settings"], "path": "/settings"})
        self.saves.wake()  # a saving cut off (the device turned off, say) goes on
        return {"title": "YouTube", "items": items}

    def search(self, words, page, lang):
        t = TEXT[lang]
        if not words:
            return self.home(lang)
        first = (page - 1) * PER_PAGE + 1
        result = self.library.flat(f"ytsearch{page * PER_PAGE}:{words}", lang, first, page * PER_PAGE)
        found = videos(result)
        if found and page == 1:
            self.state.remember("recent", words, lambda q: q == words)
        for e in found:
            self.seen[e["id"]] = about(e)
        items = [video_item(e, lang) for e in found]
        channels = {}
        for e in found:
            if e.get("channel_id") and e.get("channel"):
                channels.setdefault(e["channel_id"], e["channel"])
        self.channel_names.update(channels)
        if channels and page == 1:
            items.append({"title": t["channels"], "header": True})
            items += [{"title": name, "subtitle": t["channel"], "path": "/c/" + cid}
                      for cid, name in list(channels.items())[:5]]
        if len(found) >= PER_PAGE:
            items.append({"title": t["more"], "path": f"/q/{urllib.parse.quote(words, safe='')}/{page + 1}"})
        return {"title": t["results"].format(q=words), "items": items, "empty": t["none"]}

    def channel(self, channel_id, page, lang):
        t = TEXT[lang]
        first = (page - 1) * PER_PAGE + 1
        result = self.library.flat(f"https://www.youtube.com/channel/{channel_id}/videos", lang,
                                   first, page * PER_PAGE)
        name = result.get("channel") or result.get("uploader") or channel_id
        self.channel_names[channel_id] = name
        found = videos(result)
        for e in found:
            self.seen[e["id"]] = about(e, channel=name, channel_id=channel_id)
        kept = False
        for c in self.state["channels"]:
            if c["id"] == channel_id:
                kept = True
                if c["name"] != name:
                    c["name"] = name
                    self.state.save()
        items = []
        if page == 1:
            items.append({"title": t["drop"] if kept else t["keep"],
                          "path": f"/c/{channel_id}/{'drop' if kept else 'keep'}"})
        items += [video_item(e, lang, channel=False) for e in found]
        if len(found) >= PER_PAGE:
            items.append({"title": t["more"], "path": f"/c/{channel_id}/{page + 1}"})
        return {"title": name, "items": items, "empty": t["no_videos"]}

    def keep(self, channel_id, keep):
        if keep:
            if not any(c["id"] == channel_id for c in self.state["channels"]):
                self.state["channels"].append({"id": channel_id,
                                               "name": self.channel_names.get(channel_id, channel_id)})
        else:
            self.state["channels"] = [c for c in self.state["channels"] if c["id"] != channel_id]
        self.state.save()

    def lookup(self, video_id, lang):
        """About a video: from a list read, the saved ones, or else yt-dlp."""
        if video_id not in self.seen:
            saved = self.saves.get(video_id)
            self.seen[video_id] = about(saved) if saved else about(self.library.about(video_id, lang))
        return self.seen[video_id]

    def video(self, video_id, lang):
        """A video's page: play it, save it (or stop, or delete it), and its channel."""
        t = TEXT[lang]
        v = self.lookup(video_id, lang)
        saved = self.saves.get(video_id)
        state = saved and saved.get("state")
        facts = [length(v, lang), views(v.get("view_count"), lang)]
        if state == "done":
            facts = [t["saved"], f"{saved.get('height')}p", size(saved.get("size") or 0)]
        items = [{"title": t["play"], "subtitle": " · ".join(f for f in facts if f), "play": video_id}]
        if v.get("live_status") not in ("is_live", "is_upcoming", "post_live"):
            save = {"title": t["save"], "subtitle": f"{self.state['save_height']}p", "play": "save:" + video_id}
            if state == "done":
                save = {"title": t["delete"], "play": "unsave:" + video_id}
            elif state in ("waiting", "saving"):
                save = {"title": t["unsave"], "play": "unsave:" + video_id,
                        "subtitle": t["saving"].format(p=saved.get("percent", 0))
                        if state == "saving" else t["waiting"]}
            elif state == "failed":
                save = {"title": t["save_again"], "subtitle": t["failed"], "play": "save:" + video_id}
            items.append(save)
        if v.get("channel_id"):
            items.append({"title": v.get("channel") or t["channel"], "subtitle": t["channel"],
                          "path": "/c/" + v["channel_id"]})
        return {"title": v.get("title") or video_id, "items": items}

    def saved(self, lang):
        t = TEXT[lang]
        items = []
        for e in self.saves.all():
            self.seen.setdefault(e["id"], about(e))
            state = e.get("state")
            note = (t["saving"].format(p=e.get("percent", 0)) if state == "saving" else
                    t["waiting"] if state == "waiting" else t["failed"] if state == "failed" else None)
            items.append(video_item(e, lang, subtitle=note))
        return {"title": t["saved"], "items": items, "empty": t["no_saved"]}

    def settings(self, which, lang):
        t = TEXT[lang]
        if which in ("play", "save"):
            current = self.state[which + "_height"]
            items = [{"title": f"{h}p", "subtitle": t["current"] if h == current else None,
                      "play": f"set:{which}:{h}"} for h in HEIGHTS]
            return {"title": t[which + "_height"], "items": items}
        return {"title": t["settings"], "items": [
            {"title": t["play_height"], "subtitle": f"{self.state['play_height']}p", "path": "/settings/play"},
            {"title": t["save_height"], "subtitle": f"{self.state['save_height']}p", "path": "/settings/save"},
            {"title": t["clear_recent"], "play": "clear:recent"},
            {"title": t["clear_history"], "play": "clear:history"},
            {"title": LIB[lang]["update"], "subtitle": self.library.version, "path": "/update"}]}

    def play(self, target, lang):
        if ":" in target:
            return {"error": self.act(*target.split(":", 1), lang)}
        saved = self.saves.get(target)
        if saved and saved.get("state") == "done":
            answer = {"url": saved["file"], "title": saved.get("title") or target}
            seen = about(saved)
        else:
            answer, info = self.library.play(target, lang, self.state["play_height"])
            seen = about(info, id=target)
        self.seen[target] = seen
        self.state.remember("history", seen, lambda v: v.get("id") == target)
        return answer

    def act(self, what, arg, lang):
        """A row that does something: the words isoPod shows for it."""
        t = TEXT[lang]
        if what == "save":
            was = self.saves.add(about(self.lookup(arg, lang)), self.state["save_height"], lang)
            state = was and was.get("state")
            return (t["already"] if state == "done" else
                    t["saving"].format(p=was.get("percent", 0)) if state == "saving" else
                    t["waiting"] if state == "waiting" else t["started"])
        if what == "unsave":
            was = self.saves.drop(arg)
            return t["not_saved"] if not was else t["deleted"] if was.get("state") == "done" else t["cancelled"]
        if what == "clear" and arg in ("recent", "history"):
            self.state[arg] = []
            self.state.save()
            return t["cleared_" + arg]
        if what == "set":
            which, _, h = arg.partition(":")
            if which in ("play", "save") and h.isdigit() and int(h) in HEIGHTS:
                self.state[which + "_height"] = int(h)
                self.state.save()
                return t["set"].format(what=t[which + "_height"], h=h)
        return LIB[lang]["unavailable"]


if __name__ == "__main__":
    if sys.argv[1:] == ["--save"]:
        Saves("YouTube").work()
    else:
        app = YouTube()
        ytlib.serve(app.page, app.play)
