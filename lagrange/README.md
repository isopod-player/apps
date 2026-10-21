# Lagrange for site apps

What the apps that read a website in [Lagrange](https://gmi.skyjake.fi/lagrange/), the
Gemini browser, share: the build of Lagrange with isoPod's patches, Pretendard, the start
script, and `gemserve.py`, the server that turns the site into Gemini. This folder is not an
app itself; an app's `build.sh` runs `build.sh` here with the folder to fill, then adds its
`app.json` and its site module as `share/site.py`:

```sh
sh "$HERE/../../lagrange/build.sh" "$OUT"
cp "$HERE/app.json" "$OUT/"
cp "$HERE/mysite.py" "$OUT/share/site.py"
```

The site module describes the site with a `gemserve.Site` (its pages for
`gemini://localhost/<path>`, which of the site's own addresses are its pages, which hosts
serve pictures) and calls `gemserve.run()`. The start script runs it beside Lagrange, as
Lagrange's HTTP proxy too, and it ends with Lagrange. Other web pages are cut down to their
text and links, and pictures open under their links. It needs only the Python on the device.

## Buttons

| Button | |
| --- | --- |
| Up, Down | The link above or below; where there is none in sight, a few lines |
| A | Open the link; a picture opens under it, and closes again |
| B | Back; on the start page, or with nothing to go back to, close the app |
| Left, Right | A screen up or down |
| X | The start page |
| Y | Reload |
| L1, R1 | Smaller or larger text |
| Select | Close a menu or a question |

Start, L2 and R2 are isoPod's, for the music. The buttons are typed as keys (`keys` in the
app's `app.json`): Lagrange moves between links only with the mouse or with letter keys,
so a patch here makes Up and Down go from link to link and Return open it. B closes the app
from its start page, as Back does on a phone; Home, then the app under Open Apps, then Close
does it from anywhere.

## The build

`build.sh` builds Lagrange from its release source, with HarfBuzz built in and OpenSSL,
PCRE2 and libwebp linked statically; it uses the device's SDL2 and zlib. FriBidi and
libunistring are in `lib/`. Pretendard is made into a Lagrange fontpack for the pages
(Lagrange's own font stays for its buttons, with Pretendard for their Hangul), and a
certificate for localhost is made for the server; the start script keeps the first one in
the app's settings, since Lagrange remembers it. The screen's 230 dpi would make Lagrange
draw everything twice as large, so the start script holds it to 96.

`patches/` holds what isoPod changes in Lagrange, applied in their order:

1. `keyboard-links`: Up and Down move from link to link, shown as a touched link is on a
   phone, and scroll to it; Return opens it as a click does.
2. `no-site-banner`: no site name over the page, on a screen 480 pixels high.
3. `tall-images`: a picture is held to the screen's width only. Lagrange holds it to the
   screen's height too, which on a 640×480 screen squeezes long pictures to slivers.
4. `back-quits`: Back on the start page (the bookmark tagged as the home page), or with
   nothing left to go back to, ends Lagrange.

## Licences

Lagrange and the_Foundation are BSD-2-Clause, HarfBuzz MIT, FriBidi LGPL-2.1-or-later,
libunistring LGPL-3.0-or-later, OpenSSL Apache-2.0, PCRE2 BSD-3-Clause, libwebp
BSD-3-Clause, and Pretendard and the fonts Lagrange carries the SIL Open Font License 1.1
(Roboto Apache-2.0). Their texts are in `licenses/` in a built app. `gemserve.py`, the
patches and the scripts are GPL-2.0-or-later.
