#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""YouTube for isoPod, as a list app.

isoPod asks for pages and shows them as its own lists; a video it plays in its own player.
Pages: search (with isoPod's keyboard), the searches made lately, channels kept here and
each channel's videos, and the videos watched. There is no account. ytlib.py, beside this,
holds yt-dlp and the talk with isoPod.
"""

import urllib.parse

import ytlib
from ytlib import TEXT as LIB, Library, State, length, videos, views

PER_PAGE = 20

TEXT = {
    "ko": {"search": "검색", "prompt": "찾을 영상", "recent": "최근 검색", "channels": "채널",
           "watched": "본 영상", "results": "'{q}' 검색 결과", "more": "더 보기", "channel": "채널",
           "keep": "채널 목록에 넣기", "drop": "채널 목록에서 빼기",
           "none": "결과가 없습니다. 로그인해야 볼 수 있는 검색어일 수도 있습니다.",
           "no_videos": "영상이 없습니다.", "no_watched": "아직 본 영상이 없습니다."},
    "en": {"search": "Search", "prompt": "Videos", "recent": "Recent searches", "channels": "Channels",
           "watched": "Watched", "results": "Results for '{q}'", "more": "More", "channel": "Channel",
           "keep": "Keep this channel", "drop": "Let this channel go",
           "none": "Nothing found. The search may need signing in.",
           "no_videos": "No videos.", "no_watched": "Nothing watched yet."},
}


def video_item(entry, lang, channel=True):
    """A row that plays a video: its title, with who made it and how long it is under it."""
    parts = [entry.get("channel") or entry.get("uploader")] if channel else []
    parts.append(length(entry, lang))
    if not channel:
        parts.append(views(entry.get("view_count"), lang))
    return {"title": entry.get("title") or entry["id"], "subtitle": " · ".join(p for p in parts if p),
            "play": entry["id"]}


class YouTube:
    def __init__(self):
        self.library = Library()
        self.state = State("youtube.json", {"recent": [], "channels": [], "history": []},
                           {"recent": 8, "history": 50})
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
        if parts[0] == "watched":
            items = [video_item(v, lang) for v in self.state["history"]]
            return {"title": t["watched"], "items": items, "empty": t["no_watched"]}
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
        items.append({"title": LIB[lang]["update"], "subtitle": self.library.version, "path": "/update"})
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

    def play(self, video_id, lang):
        answer, info = self.library.play(video_id, lang)
        seen = {"id": video_id, "title": info.get("title"), "channel": info.get("channel"),
                "channel_id": info.get("channel_id"), "duration": info.get("duration")}
        self.state.remember("history", seen, lambda v: v.get("id") == video_id)
        return answer


if __name__ == "__main__":
    app = YouTube()
    ytlib.serve(app.page, app.play)
