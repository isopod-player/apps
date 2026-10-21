# SPDX-License-Identifier: GPL-2.0-or-later
"""A site as Gemini, for Lagrange on isoPod: what every such app's converter shares.

The app's own module (share/site.py) describes its site with a Site and calls run(). This
module is then a Gemini server on localhost: gemini://localhost/<path> goes to the site's
pages, and as Lagrange's HTTP proxy it also takes the http(s) links found in them. The
site's own addresses open as its pages, pictures come back with their real type (behind
addresses ending as image files do, so Lagrange shows them in place), and other pages are
cut down to their text and links.

    site.py --cert PEM [--key PEM] --data DIR [--port 1965] [-- PROGRAM ARGS...]

With a program after `--` it serves until that program ends, and ends with it; the program
is started even when the port is taken, by an older server say, or when this Python has
no TLS. Python's standard library is all it needs.
"""

import argparse
import asyncio
import base64
import gzip
import os
import re
import signal
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser

try:
    import ssl
except ImportError:  # a Python without TLS can serve no Gemini; the program runs alone
    ssl = None

UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0 Mobile Safari/537.36")
ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
GEMTEXT = "text/gemini; charset=utf-8"
PAGE_LIMIT = 8 << 20
MEDIA_LIMIT = 32 << 20
LANG = os.environ.get("ISOPOD_LANG") if os.environ.get("ISOPOD_LANG") in ("ko", "en") else "ko"
BASE = "gemini://localhost/"  # set by run() from --port
DATA = "."                    # set by run() from --data
SITE = None                   # set by run()

TEXT = {
    "ko": {"picture": "이미지 {n}", "video": "동영상", "sound": "소리", "embedded": "삽입된 내용",
           "youtube": "유튜브 영상", "failed": "연결하지 못했습니다", "retry": "다시 시도", "home": "처음으로",
           "missing": "없는 페이지입니다", "refused": "이 주소는 받지 않습니다", "broken": "변환 중 오류"},
    "en": {"picture": "Picture {n}", "video": "Video", "sound": "Sound", "embedded": "Embedded",
           "youtube": "YouTube video", "failed": "Could not connect", "retry": "Try again", "home": "Home",
           "missing": "No such page", "refused": "Not an address this takes", "broken": "Conversion failed"},
}


def t(key, **args):
    return TEXT[LANG][key].format(**args)


# --- Fetching ---------------------------------------------------------------------------

class Fetched:
    def __init__(self, url, status, headers, body):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def mime(self):
        return (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    @property
    def text(self):
        m = re.search(r"charset=([\w-]+)", self.headers.get("Content-Type") or "", re.I)
        if not m:
            m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", self.body[:4096], re.I)
            charset = m.group(1).decode() if m else "utf-8"
        else:
            charset = m.group(1)
        try:
            return self.body.decode(charset, "replace")
        except LookupError:
            return self.body.decode("utf-8", "replace")


class Failed(Exception):
    pass


def fetch(url, data=None, headers=None, limit=PAGE_LIMIT):
    """GET (or POST with data) as a phone's browser would. An HTTP error with a page comes
    back like any other answer."""
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8", "Accept-Encoding": "gzip",
        **(headers or {})})
    try:
        r = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as e:
        r = e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Failed(str(getattr(e, "reason", e))) from None
    try:
        body = r.read(limit + 1)
    except OSError as e:
        raise Failed(str(e)) from None
    finally:
        r.close()
    if len(body) > limit:
        raise Failed("too big")
    encoding = (r.headers.get("Content-Encoding") or "").lower()
    try:
        if encoding == "gzip":
            body = gzip.decompress(body)
        elif encoding == "deflate":
            body = zlib.decompress(body)
    except (OSError, zlib.error, EOFError) as e:
        raise Failed(str(e)) from None
    return Fetched(r.geturl(), getattr(r, "status", None) or r.code, r.headers, body)


# --- A small HTML tree ------------------------------------------------------------------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {k: (v or "") for k, v in attrs}
        self.children = []
        self.parent = parent

    @property
    def classes(self):
        return self.attrs.get("class", "").split()

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find_all(self, tag=None, cls=None, **attrs):
        for n in self.walk():
            if ((tag is None or n.tag == tag) and (cls is None or cls in n.classes)
                    and all(n.attrs.get(k) == v for k, v in attrs.items())):
                yield n

    def find(self, tag=None, cls=None, **attrs):
        return next(self.find_all(tag, cls, **attrs), None)

    def text(self, skip=("script", "style")):
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                elif child.tag not in skip:
                    collect(child)
        collect(self)
        return " ".join("".join(parts).split())


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node("#root", (), None)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node.parent is not None and node.tag != tag:
            node = node.parent
        if node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(markup):
    tree = Tree()
    tree.feed(markup)
    tree.close()
    return tree.root


def cut(markup, start, end=None):
    """The part of a page from one marker to another, to spare parsing the rest."""
    i = markup.find(start)
    if i < 0:
        return ""
    i = markup.rfind("<", 0, i)
    j = markup.find(end, i) if end else -1
    return markup[i:j if j > 0 else len(markup)]


# --- Gemtext ----------------------------------------------------------------------------

def link(target, label):
    return f"=> {target} {' '.join(label.split())}".rstrip()


def here(path):
    return BASE + path.lstrip("/")


def plain(line):
    """A line of text that gemtext will not take for a link, heading, list or quote."""
    return " " + line if re.match(r"(=>|#|\*|>|```)", line) else line


def tidy(lines):
    out = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


def image_link(url):
    """Our own address for an image, ending as an image file does so Lagrange shows it in place."""
    token = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return here(f"img/{token}.jpg")


BLOCK = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote",
         "section", "article", "figure", "figcaption", "center", "pre", "hr", "dl", "dt", "dd", "header",
         "footer", "main", "nav", "aside", "details", "summary"}
SKIP = {"script", "style", "noscript", "button", "select", "input", "textarea", "form", "svg", "template",
        "head", "title"}
LOADING = re.compile(r"/loading|data:image|spacer\.gif|blank\.gif")


class Writer:
    """HTML as gemtext: a line for each paragraph, the links found in one listed after it,
    and every picture as a link to itself. A site's own kind may name its pictures and
    embeds better, or take over some nodes (special)."""

    loading = LOADING

    def __init__(self, base, images=None):
        self.base = base
        self.out = []
        self.line = []
        self.links = []
        self.images = images if images is not None else [0]

    def end(self, blank=False):
        text = " ".join("".join(self.line).split())
        self.line = []
        if text and not any(label == text for _, label in self.links):
            self.out.append(plain(text))
        elif blank:
            self.out.append("")
        self.out.extend(link(href, label) for href, label in self.links)
        self.links = []

    def absolute(self, url):
        url = (url or "").strip()
        if not url or url.startswith(("javascript:", "#", "data:", "mailto:", "tel:")):
            return None
        url = urllib.parse.urljoin(self.base, url)
        path = SITE.address(url) if SITE else None
        return here(path) if path else url

    def picture_label(self, node, src):
        self.images[0] += 1
        return t("picture", n=self.images[0])

    def picture(self, node):
        src = None
        for key in ("data-original", "data-gif", "data-src", "src"):
            value = self.absolute(node.attrs.get(key))
            if value and not self.loading.search(value):
                src = value
                break
        if not src:
            return
        self.end()
        self.out.append(link(image_link(src) if src.startswith("http") else src, self.picture_label(node, src)))

    def frame_line(self, src):
        m = re.search(r"youtube(?:-nocookie)?\.com/embed/([\w-]+)", src)
        if m:
            return link(f"https://www.youtube.com/watch?v={m.group(1)}", t("youtube"))
        return link(src, t("embedded"))

    def special(self, node):
        return False

    def node(self, node):
        tag = node.tag
        if tag in SKIP or self.special(node):
            return
        if tag == "br":
            self.end(blank=True)
            return
        if tag == "img":
            self.picture(node)
            return
        if tag in ("iframe", "embed"):
            src = self.absolute(node.attrs.get("src") or node.attrs.get("data-src"))
            if src:
                self.end()
                self.out.append(self.frame_line(src))
            return
        if tag in ("video", "audio"):
            src = self.absolute(node.attrs.get("src") or node.attrs.get("data-src"))
            source = node.find("source")
            src = src or (source and self.absolute(source.attrs.get("src")))
            if src:
                self.end()
                self.out.append(link(src, t("video") if tag == "video" else t("sound")))
            return
        if tag == "pre":
            self.end()
            text = "".join(_raw(node))
            self.out += ["```"] + text.strip("\n").splitlines() + ["```"]
            return
        block = tag in BLOCK
        if block:
            self.end()
        if tag in ("h1", "h2", "h3"):
            heading = node.text()
            if heading:
                self.out.append("#" * int(tag[1]) + " " + heading)
                return
        start = len(self.out)
        for child in node.children:
            if isinstance(child, str):
                self.line.append(child)
            else:
                self.node(child)
        if tag == "a":
            href = self.absolute(node.attrs.get("href"))
            label = node.text() or href
            if href and len(self.out) == start:
                self.links.append((href, " ".join(label.split())))
        if block:
            self.end()

    def write(self, node):
        self.node(node)
        self.end()
        return tidy(self.out)


def _raw(node):
    for child in node.children:
        if isinstance(child, str):
            yield child
        elif child.tag == "br":
            yield "\n"
        elif child.tag not in SKIP:
            yield from _raw(child)


def main_content(doc):
    """The part of a page that is its text: the article, or else what holds the most
    paragraphs' worth of words; menus, footers and the like are left out."""
    articles = [a for a in doc.find_all("article")]
    if articles:
        return max(articles, key=lambda a: len(a.text()))
    found = doc.find("main")
    if found:
        return found
    best, best_score = None, 0
    for n in doc.walk():
        if n.tag not in ("div", "section", "td", "body"):
            continue
        score = sum(len(c.text()) for c in n.children if isinstance(c, Node) and c.tag == "p")
        if score > best_score:
            best, best_score = n, score
    return best or doc.find("body") or doc


# --- Answers ----------------------------------------------------------------------------

def ok(lines, lang=None):
    """A page of gemtext; lang="" for a page in a language not known."""
    lang = LANG if lang is None else lang
    return "20", GEMTEXT + (f"; lang={lang}" if lang else ""), ("\n".join(tidy(lines)) + "\n").encode()


def not_found():
    return "51", t("missing"), b""


SNIFF = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png"), (b"GIF8", "image/gif"),
         (b"BM", "image/bmp"))


def media_type(body, given):
    for magic, mime in SNIFF:
        if body.startswith(magic):
            return mime
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body[4:8] == b"ftyp":
        return "video/mp4"
    return given or "application/octet-stream"


def media(url, headers=None):
    """A picture or other file as it is, with the type its bytes say it has."""
    r = fetch(url, headers=headers, limit=MEDIA_LIMIT)
    if r.status != 200:
        return "51", f"HTTP {r.status}", b""
    return "20", media_type(r.body, r.mime), r.body


def image(token):
    token = token.rsplit(".", 1)[0]
    try:
        url = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return not_found()
    if not url.startswith(("http://", "https://")):
        return not_found()
    return media(url, SITE.media_headers(url) if SITE else None)


def web(url):
    """Any other page: its text and links. Pictures and files pass as they are."""
    r = fetch(url, limit=MEDIA_LIMIT)
    mime = r.mime
    if mime not in ("text/html", "application/xhtml+xml"):
        if mime in ("", "application/octet-stream"):
            mime = media_type(r.body, mime)
        return "20", mime or "application/octet-stream", r.body
    doc = parse(r.text)
    title = doc.find("title")
    lines = [f"# {title.text()}" if title and title.text() else f"# {url}", ""]
    if r.status != 200:
        lines += [f"HTTP {r.status}", ""]
    lines += (SITE.writer(r.url) if SITE else Writer(r.url)).write(main_content(doc))
    lines += ["", link(r.url, r.url)]
    return ok(lines, lang="")


class Site:
    """What a site gives the server. Its pages answer gemini://localhost/<path>."""

    def local(self, path):
        return not_found()

    def address(self, url):
        """The site's own http(s) address as one of its pages' paths, or None."""
        return None

    def media_host(self, host):
        """Whether files from this host pass through as they are, without being read as pages."""
        return False

    def media_headers(self, url):
        return None

    def writer(self, base):
        return Writer(base)


def answer(request):
    url = request.strip()
    try:
        u = urllib.parse.urlsplit(url)
        if u.scheme == "gemini" and (u.hostname or "") in ("localhost", "127.0.0.1", "::1"):
            path = urllib.parse.unquote(u.path)
            if path.startswith("/img/") and path.count("/") == 2:
                return image(path[5:])
            if u.query:
                path += "?" + u.query
            return SITE.local(path)
        if u.scheme in ("http", "https"):
            path = SITE.address(url)
            if path:
                return SITE.local(path)
            if SITE.media_host((u.hostname or "").lower()):
                return media(url, SITE.media_headers(url))
            return web(url)
        return "53", t("refused"), b""
    except Failed as e:
        return ok([f"# {t('failed')}", "", str(e), "", link(url, t("retry")), link(BASE, t("home"))])
    except Exception as e:  # a page the site changed should not end the server
        print(f"gemserve: {url}: {e!r}", file=sys.stderr)
        return "42", f"{t('broken')}: {type(e).__name__}", b""


# --- The server -------------------------------------------------------------------------

async def serve(reader, writer):
    try:
        request = await asyncio.wait_for(reader.readline(), 10)
        if len(request) > 1026 or not request.endswith(b"\n"):
            status, meta, body = "59", "bad request", b""
        else:
            status, meta, body = await asyncio.to_thread(answer, request.decode("utf-8", "replace"))
        writer.write(f"{status} {meta}\r\n".encode() + body)
        await writer.drain()
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ssl.SSLError):
            pass


async def main(args):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server = None
    for hosts in (["127.0.0.1", "::1"], "127.0.0.1"):
        try:
            server = await asyncio.start_server(serve, hosts, args.port, ssl=context)
            break
        except OSError as e:
            error = e
    if server is None:
        print(f"gemserve: cannot listen on {args.port}: {error}", file=sys.stderr)
        if not args.program:
            return 1
    if not args.program:
        async with server:
            await server.serve_forever()
        return 0
    proc = await asyncio.create_subprocess_exec(*args.program)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        loop.add_signal_handler(sig, lambda s=sig: proc.returncode is None and proc.send_signal(s))
    code = await proc.wait()
    if server:
        server.close()
    return code


def run(site):
    global BASE, DATA, SITE
    p = argparse.ArgumentParser(description="A site as Gemini, on localhost")
    p.add_argument("--cert", required=True)
    p.add_argument("--key", help="if not in the --cert file")
    p.add_argument("--data", default=os.path.expanduser("~/.config/gemserve"))
    p.add_argument("--port", type=int, default=1965)
    p.add_argument("program", nargs=argparse.REMAINDER)
    args = p.parse_args()
    if args.program[:1] == ["--"]:
        args.program = args.program[1:]
    BASE = "gemini://localhost/" if args.port == 1965 else f"gemini://localhost:{args.port}/"
    DATA = args.data
    SITE = site
    if ssl is None:
        print("gemserve: no ssl module", file=sys.stderr)
        if args.program:
            os.execvp(args.program[0], args.program)
        sys.exit(1)
    sys.exit(asyncio.run(main(args)))
