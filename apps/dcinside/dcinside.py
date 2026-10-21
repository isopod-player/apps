#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""DCInside (디시인사이드) as Gemini, for the isoPod app that reads it in Lagrange.

DCInside's mobile pages in gemtext: the start page with the galleries kept there, a
gallery's posts, a post with its comments, and a finder for galleries. Nothing on them
needs typing. gemserve.py, beside this, is the server.
"""

import html
import json
import os
import re
import threading
import time
import urllib.parse

import gemserve
from gemserve import ACCEPT, Failed, Writer, cut, fetch, here, link, not_found, parse

MOBILE = "https://m.dcinside.com"
GALLERY = re.compile(r"^[A-Za-z0-9_]{1,64}$")
DEFAULT_GALLERIES = [{"id": "dcbest", "name": "실시간 베스트"}, {"id": "hit", "name": "HIT 갤러리"}]
NAMES = {}  # gallery id -> name, from every page read
LOCK = threading.Lock()
CACHE = {}  # url -> (when, markup), for the gallery lists that change little and weigh a lot
CACHE_SECONDS = 1800


def ok(lines):
    return gemserve.ok(lines, lang="ko")


class DCWriter(Writer):
    """DCInside's posts: pictures waiting for their lazy loader, DCInside's own emoticons
    (디시콘), its voice and video players, and link preview cards."""

    loading = re.compile(r"nstatic\.dcinside\.com/dc/m/img/|/loading|data:image")

    def picture_label(self, node, src):
        if "dccon" in src or "written_dccon" in node.classes:
            return f"디시콘 {node.attrs.get('title') or ''}".strip()
        self.images[0] += 1
        return f"이미지 {self.images[0]}"

    def frame_line(self, src):
        if "/voice/player" in src:
            return "(음성 댓글)"
        if "/movie/player" in src:
            return "(동영상)"  # DCInside's own player, which Lagrange cannot play
        return super().frame_line(src)

    def special(self, node):
        if node.tag == "a" and "og-wrap" in node.classes:  # a link's preview card: its title is enough
            href = self.absolute(node.attrs.get("href"))
            title = node.find(cls="og-tit") or node.find(cls="og-txt")
            if href:
                self.end()
                self.out.append(link(href, title.text() if title and title.text() else href))
            return True
        return False


# --- Saved galleries --------------------------------------------------------------------

def galleries_path():
    return os.path.join(gemserve.DATA, "galleries.json")


def load_galleries():
    try:
        with open(galleries_path(), encoding="utf-8") as f:
            found = json.load(f)
        return [g for g in found if isinstance(g, dict) and GALLERY.match(str(g.get("id", "")))]
    except (OSError, ValueError):
        return [dict(g) for g in DEFAULT_GALLERIES]


def save_galleries(galleries):
    os.makedirs(gemserve.DATA, exist_ok=True)
    path = galleries_path()
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(galleries, f, ensure_ascii=False, indent=1)
    os.replace(path + ".part", path)


def gallery_name(gid):
    if gid not in NAMES:
        for g in load_galleries():
            NAMES.setdefault(g["id"], g.get("name") or g["id"])
    return NAMES.get(gid, gid)


# --- DCInside pages ---------------------------------------------------------------------

def dc_get(url, cache=False):
    """A DCInside page. A browser that says it takes WebP gets WebP pictures; any other gets a
    picture saying so."""
    if cache and url in CACHE and time.monotonic() - CACHE[url][0] < CACHE_SECONDS:
        return None, CACHE[url][1]
    r = fetch(url, headers={"Referer": MOBILE + "/", "Accept": ACCEPT})
    if cache and r.status == 200:
        CACHE[url] = (time.monotonic(), r.text)
    return r, r.text


def gallery_title(markup):
    h3 = parse(cut(markup, 'class="gall-tit"', "</h3>")).find("h3")
    name = h3.text() if h3 else ""
    if not name:
        m = re.search(r"<title>\s*(.*?)\s*-\s*커뮤니티 포털", markup)
        name = m.group(1) if m else ""
    return re.sub(r"\s*(마이너\s*)?갤러리$", "", name).strip()


def missing(what, status):
    return ok([f"# {what}", "", f"디시인사이드가 HTTP {status}(으)로 답했습니다.", "", link(here(""), "처음으로")])


def number(text, default=1):
    return int(text) if text and text.isdigit() and 0 < int(text) < 100000 else default


def gallery(gid, page=1, best=False):
    url = f"{MOBILE}/board/{gid}?page={page}" + ("&recommend=1" if best else "")
    r, markup = dc_get(url)
    if r.status != 200:
        return missing("갤러리를 열 수 없습니다", r.status)
    name = gallery_title(markup) or gid
    NAMES[gid] = name
    doc = parse(cut(markup, 'class="gall-detail-lst', "</section>"))
    lines = [f"# {name}" + (" 개념글" if best else ""), ""]
    saved = any(g["id"] == gid for g in load_galleries())
    posts = 0
    for box in doc.find_all("div", cls="gall-detail-lnktb"):
        a = box.find("a", cls="lt")
        m = re.search(r"/board/(\w+)/(\d+)", a.attrs.get("href", "")) if a else None
        subject = box.find("span", cls="subjectin")
        if not m or not subject:
            continue
        count = box.find("span", cls="ct")
        count = count.text() if count else ""
        title = subject.text() or "(제목 없음)"
        if count and count != "0":
            title += f" [{count}]"
        lines.append(link(here(f"p/{m.group(1)}/{m.group(2)}"), title))
        posts += 1
    if not posts:
        lines.append("글이 없습니다.")
    lines.append("")
    kind = "best/" if best else ""
    if posts:
        lines.append(link(here(f"g/{gid}/{kind}{page + 1}"), "다음 쪽"))
    if page > 1:
        lines.append(link(here(f"g/{gid}/{kind}{page - 1}"), "이전 쪽"))
    lines.append(link(here(f"g/{gid}" if best else f"g/{gid}/best/1"), "전체 글" if best else "개념글"))
    lines.append(link(here(f"{'del' if saved else 'add'}/{gid}"),
                      "처음 화면에서 빼기" if saved else "처음 화면에 넣기"))
    lines.append(link(here(""), "처음으로"))
    if page > 1:
        lines[0] += f" ({page}쪽)"
    return ok(lines)


COMMENTS_PER_PAGE = 100  # DCInside's, and ours


def comments(markup, base):
    """The comments in a page of them, by their place among all of a post's (a reply comes
    right after what it answers), each as gemtext lines."""
    found = []
    for li in parse(markup).find_all("li"):
        classes = li.classes
        if "comment" not in classes and "comment-add" not in classes:
            continue
        nick = li.find(cls="nick")
        who = nick.text() if nick else "?"
        ip = li.find(cls="ip")
        if ip and ip.text():
            who += ip.text()
        date = li.find(cls="date")
        head = who + (f" · {date.text()}" if date and date.text() else "")
        lines = ["* " + ("↳ " if "comment-add" in classes else "") + head]
        txt = li.find("p", cls="txt") or li.find(cls="txt")
        lines += DCWriter(base).write(txt) if txt else []
        found.append((number(li.attrs.get("ch"), 0), lines + [""]))
    return found


def comments_ajax(gid, no, cpage, token):
    data = urllib.parse.urlencode({"id": gid, "no": no, "cpage": cpage, "managerskill": "", "csort": "",
                                   "permission_pw": ""}).encode()
    r = fetch(f"{MOBILE}/ajax/response-comment", data=data, headers={
        "Referer": f"{MOBILE}/board/{gid}/{no}", "X-CSRF-TOKEN": token, "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    if r.status != 200:
        raise Failed(f"HTTP {r.status}")
    return r.text


def post(gid, no, part=None):
    """A post and a page of its comments. Comments run oldest first, as a talk does, a
    hundred to a page. DCInside's own first page is its newest hundred, so one of ours can
    take two of DCInside's."""
    url = f"{MOBILE}/board/{gid}/{no}"
    r, markup = dc_get(url)
    if r.status in (403, 404) or "gallview-tit-box" not in markup:
        return ok(["# 글이 없습니다", "", "지워졌거나 볼 수 없는 글입니다.", "",
                   link(here(f"g/{gid}"), gallery_title(markup) or "목록")])
    gname = gallery_title(markup) or gid
    NAMES[gid] = gname
    head = parse(cut(markup, "gallview-tit-box", 'class="gall-thum-btm'))
    tit = head.find(cls="tit")
    title = tit.text(skip=("script", "style", "button")) if tit else ""  # a button marks the kind of post
    title = title or "(제목 없음)"
    info = head.find("ul", cls="ginfo2")
    items = [li for li in info.find_all("li")] if info else []
    author = items[0].text() if items else ""
    date = items[-1].text() if len(items) > 1 else ""
    stats = parse(cut(markup, "gall-thum-btm-inner", 'class="thum-txt'))
    numbers = [li.text() for li in stats.find_all("li")]
    total = re.search(r'id="reple_totalCnt"[^>]*value="(\d+)"', markup)
    total = int(total.group(1)) if total else 0
    pages = max(1, -(-total // COMMENTS_PER_PAGE))
    part = min(max(part or 1, 1), pages)
    lines = [f"# {title}", " · ".join(x for x in (author, date) if x)]
    if numbers:
        lines.append(" · ".join(numbers))
    lines.append("")
    if part == 1:
        body = parse(cut(markup, 'class="thum-txtin', 'class="reco-search') or "")
        found = body.find(cls="thum-txtin")
        lines += DCWriter(url).write(found) if found else ["(본문 없음)"]
    else:
        lines.append(link(here(f"p/{gid}/{no}"), "본문"))
    lines.append("")
    lines.append(f"## 댓글 {total}" + (f" ({part}/{pages})" if pages > 1 else ""))
    lines.append("")
    first, last = (part - 1) * COMMENTS_PER_PAGE + 1, part * COMMENTS_PER_PAGE
    wanted = sorted({max(1, -(-(total - i + 1) // COMMENTS_PER_PAGE)) for i in (first, min(last, total))})
    found = []
    token = re.search(r'name="csrf-token" content="([^"]*)"', markup)
    for cpage in wanted if total else ():
        try:
            section = (cut(markup, 'class="all-comment-lst', 'class="update-re') if cpage == 1 else
                       comments_ajax(gid, no, cpage, token.group(1) if token else ""))
        except Failed as e:
            lines += [f"댓글을 가져오지 못했습니다: {e}", link(here(f"p/{gid}/{no}/{part}"), "다시 시도"), ""]
            continue
        found += comments(section, url)
    if pages > 1:
        found = [c for c in found if first <= c[0] <= last]
    for _, comment in sorted(found, key=lambda c: c[0]):
        lines += comment
    if not total:
        lines += ["댓글이 없습니다.", ""]
    if part < pages:
        lines.append(link(here(f"p/{gid}/{no}/{part + 1}"), "다음 댓글"))
    if part > 1:
        lines.append(link(here(f"p/{gid}/{no}/{part - 1}" if part > 2 else f"p/{gid}/{no}"), "이전 댓글"))
    lines.append(link(here(f"g/{gid}"), gname))
    return ok(lines)


# --- Finding galleries ------------------------------------------------------------------

def ranking(url):
    r = fetch(url)
    text = r.text.strip()
    text = text[1:-1] if text.startswith("(") else text
    try:
        found = json.loads(text)
    except ValueError:
        raise Failed("bad ranking") from None
    return [(g["id"], g.get("ko_name") or g["id"]) for g in found
            if isinstance(g, dict) and GALLERY.match(str(g.get("id", "")))]


CHOSEONG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
PLAIN_CHOSEONG = "ㄱㄱㄴㄷㄷㄹㅁㅂㅂㅅㅅㅇㅈㅈㅊㅋㅌㅍㅎ"
INITIALS = list(dict.fromkeys(PLAIN_CHOSEONG)) + ["A", "0"]
INITIAL_NAMES = {"A": "A–Z", "0": "숫자·기호"}


def initial(name):
    c = name[:1]
    if "가" <= c <= "힣":
        return PLAIN_CHOSEONG[(ord(c) - 0xAC00) // 588]
    if c in CHOSEONG:
        return PLAIN_CHOSEONG[CHOSEONG.index(c)]
    if c.isascii() and c.isalpha():
        return "A"
    return "0"


def gallery_links(markup):
    """Every gallery a list page links to, once each, in its order."""
    found = {}
    for m in re.finditer(r'<a href="https://m\.dcinside\.com/board/(\w+)"[^>]*>([^<]+)</a>', markup):
        name = " ".join(html.unescape(m.group(2)).split())
        if name:
            found.setdefault(m.group(1), name)
    return list(found.items())


def minor_categories():
    _, markup = dc_get(f"{MOBILE}/mcategory", cache=True)
    found = {}
    for m in re.finditer(r'href="https://m\.dcinside\.com/mcategory/(\d+)"[^>]*>([^<]+)<', markup):
        found.setdefault(m.group(1), " ".join(html.unescape(m.group(2)).split()))
    return list(found.items())


def by_initial(path, title, found, back):
    """A long list of galleries, first by the letter they start with."""
    parts = path.split("/")
    if len(parts) < 1 or not parts[-1] or parts[-1] not in INITIALS:
        counts = {}
        for _, name in found:
            counts[initial(name)] = counts.get(initial(name), 0) + 1
        lines = [f"# {title}", ""]
        for key in INITIALS:
            if counts.get(key):
                label = INITIAL_NAMES.get(key, key)
                lines.append(link(here(f"{path}/{urllib.parse.quote(key)}"), f"{label} ({counts[key]})"))
        return ok(lines + ["", back])
    key = parts[-1]
    chosen = [(gid, name) for gid, name in found if initial(name) == key]
    return listing(f"{title} · {INITIAL_NAMES.get(key, key)}", chosen, back)


def listing(title, found, back):
    for gid, name in found:
        NAMES.setdefault(gid, name)
    return ok([f"# {title}", ""] + [link(here(f"g/{gid}"), name) for gid, name in found] + ["", back])


def find(path):
    parts = path.split("/")[1:]
    back = link(here("find"), "갤러리 찾기")
    if not parts:
        return ok(["# 갤러리 찾기", "",
                   link(here("find/hot"), "흥한 갤러리"),
                   link(here("find/minor"), "흥한 마이너 갤러리"),
                   link(here("find/all"), "메인 갤러리 (가나다)"),
                   link(here("find/m"), "마이너 갤러리 (분야별)"),
                   "", link(here(""), "처음으로")])
    if parts[0] == "hot":
        return listing("흥한 갤러리", ranking("https://json2.dcinside.com/json1/ranking_gallery.php"), back)
    if parts[0] == "minor":
        return listing("흥한 마이너 갤러리",
                       ranking("https://json2.dcinside.com/json1/mgallmain/mgallery_ranking.php"), back)
    if parts[0] == "all":
        _, markup = dc_get(f"{MOBILE}/galltotal", cache=True)
        key = urllib.parse.unquote(parts[1]) if len(parts) > 1 else ""
        return by_initial("find/all" + (f"/{key}" if key else ""), "메인 갤러리", gallery_links(markup), back)
    if parts[0] == "m":
        categories = minor_categories()
        if len(parts) < 2:
            return ok(["# 마이너 갤러리", ""] + [link(here(f"find/m/{n}"), name) for n, name in categories]
                      + ["", back])
        if not parts[1].isdigit():
            return not_found()
        name = dict(categories).get(parts[1], "마이너 갤러리")
        _, markup = dc_get(f"{MOBILE}/mcategory/{parts[1]}", cache=True)
        key = urllib.parse.unquote(parts[2]) if len(parts) > 2 else ""
        return by_initial(f"find/m/{parts[1]}" + (f"/{key}" if key else ""), name, gallery_links(markup),
                          link(here("find/m"), "마이너 갤러리"))
    return not_found()


def home():
    lines = ["# 디시인사이드", ""]
    galleries = load_galleries()
    lines += [link(here(f"g/{g['id']}"), g.get("name") or g["id"]) for g in galleries]
    if not galleries:
        lines.append("넣어 둔 갤러리가 없습니다.")
    lines += ["", link(here("find"), "갤러리 찾기")]
    if galleries:
        lines.append(link(here("edit"), "목록 정리"))
    return ok(lines)


def edit():
    galleries = load_galleries()
    lines = ["# 목록 정리", ""]
    if len(galleries) > 1:
        lines += ["## 위로 올리기"] + [link(here(f"edit/up/{g['id']}"), g.get("name") or g["id"])
                                    for g in galleries[1:]] + [""]
    if galleries:
        lines += ["## 빼기"] + [link(here(f"edit/del/{g['id']}"), g.get("name") or g["id"])
                              for g in galleries] + [""]
    else:
        lines += ["넣어 둔 갤러리가 없습니다.", ""]
    return ok(lines + [link(here(""), "처음으로")])


def change(action, gid, back):
    """Add, remove or raise a gallery, then go back to the page the change was made on."""
    with LOCK:
        galleries = load_galleries()
        ids = [g["id"] for g in galleries]
        if action == "add" and gid not in ids:
            name = gallery_name(gid)
            if name == gid:
                try:
                    _, markup = dc_get(f"{MOBILE}/board/{gid}")
                    name = gallery_title(markup) or gid
                except Failed:
                    pass
            galleries.append({"id": gid, "name": name})
        elif action == "del" and gid in ids:
            galleries.pop(ids.index(gid))
        elif action == "up" and gid in ids and ids.index(gid) > 0:
            i = ids.index(gid)
            galleries[i - 1], galleries[i] = galleries[i], galleries[i - 1]
        save_galleries(galleries)
    return "30", back, b""


class DCInside(gemserve.Site):
    def local(self, path):
        parts = [p for p in path.split("?")[0].split("/") if p]
        if not parts:
            return home()
        head = parts[0]
        if head == "g" and len(parts) >= 2 and GALLERY.match(parts[1]):
            best = len(parts) >= 3 and parts[2] == "best"
            page = number(parts[3] if best and len(parts) > 3 else parts[2] if not best and len(parts) > 2
                          else None)
            return gallery(parts[1], page, best)
        if head == "p" and len(parts) >= 3 and GALLERY.match(parts[1]) and parts[2].isdigit():
            return post(parts[1], parts[2], number(parts[3]) if len(parts) > 3 else 1)
        if head == "find":
            return find("/".join(parts))
        if head == "edit" and len(parts) == 1:
            return edit()
        if head == "edit" and len(parts) == 3 and parts[1] in ("del", "up") and GALLERY.match(parts[2]):
            return change(parts[1], parts[2], here("edit"))
        if head in ("add", "del") and len(parts) == 2 and GALLERY.match(parts[1]):
            return change(head, parts[1], here(f"g/{parts[1]}"))
        return not_found()

    def address(self, url):
        """DCInside's own addresses for a gallery or a post, as our path; None for any other."""
        u = urllib.parse.urlsplit(url)
        host = (u.hostname or "").lower()
        q = urllib.parse.parse_qs(u.query)
        if host in ("m.dcinside.com", "dcinside.com", "www.dcinside.com"):
            m = re.match(r"/board/(\w+)(?:/(\d+))?/?$", u.path)
            if m and m.group(2):
                return f"p/{m.group(1)}/{m.group(2)}"
            if m:
                best = "best/" if q.get("recommend") == ["1"] else ""
                return f"g/{m.group(1)}/{best}{number((q.get('page') or [''])[0])}"
        if host == "gall.dcinside.com":
            gid = (q.get("id") or [""])[0]
            if GALLERY.match(gid):
                if "/view" in u.path and (q.get("no") or [""])[0].isdigit():
                    return f"p/{gid}/{q['no'][0]}"
                if "/lists" in u.path or u.path in ("/list.php", "/board/lists", "/mgallery/board/lists"):
                    return f"g/{gid}/{number((q.get('page') or [''])[0])}"
        return None

    def media_host(self, host):
        return re.match(r"(dcimg\d*|image|nstatic)\.dcinside\.(co\.kr|com)$", host) is not None

    def media_headers(self, url):
        return {"Referer": MOBILE + "/"}

    def writer(self, base):
        return DCWriter(base)


if __name__ == "__main__":
    gemserve.run(DCInside())
