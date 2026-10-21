#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Hacker News as Gemini, for the isoPod app that reads it in Lagrange.

The front page and HN's other lists come from its API, thirty stories to a page. A story
comes with its comments as a thread: the whole tree from Algolia's HN API in one answer,
the first level in HN's own order. The story's own page is a link away, read through the
server as text. gemserve.py, beside this, is the server.
"""

import concurrent.futures
import json
import threading
import time
import urllib.parse

import gemserve
from gemserve import Failed, Writer, fetch, here, link, not_found, ok, parse

API = "https://hacker-news.firebaseio.com/v0/"
ALGOLIA = "https://hn.algolia.com/api/v1/items/"
HN = "https://news.ycombinator.com/"
PER_PAGE = 30
COMMENTS_PER_PAGE = 120
LISTS = (("top", "topstories"), ("new", "newstories"), ("best", "beststories"), ("ask", "askstories"),
         ("show", "showstories"), ("jobs", "jobstories"))
LIST_PATHS = {"": "top", "news": "top", "newest": "new", "best": "best", "ask": "ask", "show": "show",
              "jobs": "jobs", "front": "top"}
CACHE = {}  # url -> (when, value)
CACHE_LOCK = threading.Lock()

TEXT = {
    "ko": {"top": "인기", "new": "최신", "best": "베스트", "ask": "Ask HN", "show": "Show HN", "jobs": "채용",
           "read": "글 읽기", "comments": "댓글 {n}", "no_comments": "댓글이 없습니다.", "points": "{n}점",
           "next": "다음 쪽", "prev": "이전 쪽", "more": "다음 댓글", "less": "이전 댓글", "home": "처음으로",
           "on_hn": "HN에서 보기", "gone": "지워진 글입니다.", "story": "글",
           "ago": {"s": "방금", "m": "{n}분 전", "h": "{n}시간 전", "d": "{n}일 전", "y": "{n}년 전"}},
    "en": {"top": "Top", "new": "New", "best": "Best", "ask": "Ask HN", "show": "Show HN", "jobs": "Jobs",
           "read": "Read the story", "comments": "{n} comments", "no_comments": "No comments.",
           "points": "{n} points", "next": "Next page", "prev": "Previous page", "more": "More comments",
           "less": "Earlier comments", "home": "Home", "on_hn": "On HN", "gone": "This story is gone.",
           "story": "Story",
           "ago": {"s": "just now", "m": "{n} min ago", "h": "{n} h ago", "d": "{n} days ago", "y": "{n} years ago"}},
}


def t(key, **args):
    value = TEXT[gemserve.LANG][key]
    return value.format(**args) if isinstance(value, str) else value


def ok_page(lines):
    return ok(lines, lang="en")  # the stories and comments are in English


def get_json(url, seconds=0):
    """An API answer, kept for a while when asked."""
    with CACHE_LOCK:
        if seconds and url in CACHE and time.monotonic() - CACHE[url][0] < seconds:
            return CACHE[url][1]
    r = fetch(url, headers={"Accept": "application/json"})
    if r.status != 200:
        raise Failed(f"HTTP {r.status}")
    try:
        value = json.loads(r.text)
    except ValueError:
        raise Failed("bad answer") from None
    if seconds:
        with CACHE_LOCK:
            CACHE[url] = (time.monotonic(), value)
    return value


def ago(when):
    if not isinstance(when, (int, float)):
        return ""
    s = max(0, time.time() - when)
    words = t("ago")
    for limit, unit, size in ((60, "s", 1), (3600, "m", 60), (86400, "h", 3600), (86400 * 365, "d", 86400)):
        if s < limit:
            return words[unit].format(n=int(s // size))
    return words["y"].format(n=int(s // (86400 * 365)))


def domain(url):
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


# --- Pages ------------------------------------------------------------------------------

def home():
    return ok_page(["# Hacker News", ""] + [link(here(f"l/{name}"), t(name)) for name, _ in LISTS])


def story_label(item):
    title = item.get("title") or "?"
    site = domain(item.get("url"))
    if site:
        title += f" ({site})"
    if item.get("descendants"):
        title += f" [{item['descendants']}]"
    return title


def listing(name, page):
    api = dict(LISTS).get(name)
    if not api:
        return not_found()
    ids = get_json(API + api + ".json", seconds=120)
    chosen = ids[(page - 1) * PER_PAGE:page * PER_PAGE]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        items = list(pool.map(lambda i: get_json(f"{API}item/{i}.json", seconds=120), chosen))
    lines = [f"# {t(name)}" + (f" ({page})" if page > 1 else ""), ""]
    for n, item in enumerate(items, (page - 1) * PER_PAGE + 1):
        if isinstance(item, dict) and not item.get("deleted") and not item.get("dead"):
            lines.append(link(here(f"i/{item['id']}"), f"{n}. {story_label(item)}"))
    lines.append("")
    if len(ids) > page * PER_PAGE:
        lines.append(link(here(f"l/{name}/{page + 1}"), t("next")))
    if page > 1:
        lines.append(link(here(f"l/{name}/{page - 1}"), t("prev")))
    lines.append(link(here(""), t("home")))
    return ok_page(lines)


class HNWriter(Writer):
    def frame_line(self, src):
        return link(src, src)


def html_lines(markup, base):
    return HNWriter(base).write(parse(markup or ""))


def thread(children, depth=0):
    """The comments under one, depth first, each with how deep it is."""
    for c in children or []:
        if not isinstance(c, dict):
            continue
        if c.get("text") or c.get("children"):
            yield depth, c
            yield from thread(c.get("children"), depth + 1)


def comment_lines(depth, c, base):
    mark = "" if not depth else ("↳" * depth if depth <= 5 else f"↳×{depth}") + " "
    who = c.get("author") or "[deleted]"
    lines = [f"* {mark}{who} · {ago(c.get('created_at_i'))}"]
    return lines + html_lines(c.get("text"), base) + [""]


def story(item_id, part):
    try:
        tree = get_json(ALGOLIA + item_id, seconds=60)
    except Failed:
        tree = None
    if not isinstance(tree, dict) or tree.get("type") not in ("story", "job", "poll"):
        if isinstance(tree, dict) and tree.get("type") == "comment" and tree.get("story_id"):
            return story(str(tree["story_id"]), 1)
        return ok_page([f"# {t('story')}", "", t("gone"), "", link(here(""), t("home"))])
    hn_url = f"{HN}item?id={item_id}"
    # HN orders the first level of comments by its own ranking; Algolia by time.
    try:
        ranked = get_json(f"{API}item/{item_id}.json", seconds=60).get("kids") or []
    except (Failed, AttributeError):
        ranked = []
    rank = {k: n for n, k in enumerate(ranked)}
    top = sorted(tree.get("children") or [], key=lambda c: rank.get(c.get("id"), len(rank)))
    comments = list(thread(top))
    # Pages of comments end where a new first-level comment starts.
    pages, current = [], []
    for depth, c in comments:
        if depth == 0 and len(current) >= COMMENTS_PER_PAGE:
            pages.append(current)
            current = []
        current.append((depth, c))
    pages.append(current)
    part = min(max(part, 1), len(pages))
    facts = [domain(tree.get("url")), t("points", n=tree.get("points") or 0),
             tree.get("author") or "", ago(tree.get("created_at_i"))]
    lines = [f"# {tree.get('title') or '?'}", " · ".join(f for f in facts if f), ""]
    if part == 1:
        if tree.get("url"):
            lines.append(link(tree["url"], t("read")))
        if tree.get("text"):
            lines += [""] + html_lines(tree["text"], hn_url)
        lines.append("")
    else:
        lines += [link(here(f"i/{item_id}"), t("story")), ""]
    lines.append(f"## {t('comments', n=len(comments))}" + (f" ({part}/{len(pages)})" if len(pages) > 1 else ""))
    lines.append("")
    for depth, c in pages[part - 1]:
        lines += comment_lines(depth, c, hn_url)
    if not comments:
        lines += [t("no_comments"), ""]
    if part < len(pages):
        lines.append(link(here(f"i/{item_id}/{part + 1}"), t("more")))
    if part > 1:
        lines.append(link(here(f"i/{item_id}/{part - 1}"), t("less")))
    lines.append(link(here(""), t("home")))
    return ok_page(lines)


def number(text, default=1):
    return int(text) if text and text.isdigit() and 0 < int(text) < 100000 else default


class HackerNews(gemserve.Site):
    def local(self, path):
        parts = [p for p in path.split("?")[0].split("/") if p]
        if not parts:
            return home()
        if parts[0] == "l" and len(parts) >= 2:
            return listing(parts[1], number(parts[2] if len(parts) > 2 else None))
        if parts[0] == "i" and len(parts) >= 2 and parts[1].isdigit():
            return story(parts[1], number(parts[2] if len(parts) > 2 else None))
        return not_found()

    def address(self, url):
        u = urllib.parse.urlsplit(url)
        if (u.hostname or "").lower() != "news.ycombinator.com":
            return None
        q = urllib.parse.parse_qs(u.query)
        name = u.path.strip("/")
        if name == "item" and (q.get("id") or [""])[0].isdigit():
            return f"i/{q['id'][0]}"
        if name in LIST_PATHS:
            return f"l/{LIST_PATHS[name]}/{number((q.get('p') or [''])[0])}"
        return None


if __name__ == "__main__":
    gemserve.run(HackerNews())
