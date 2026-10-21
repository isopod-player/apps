#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# isoPod starts this: Lagrange, with the app's site module (share/site.py, on gemserve.py)
# beside it serving the site as Gemini on localhost until Lagrange ends. Lagrange's settings
# are made at its first start and are its own from then on, but for the few this app depends
# on, which are set at every start.
APP=$(cd "$(dirname "$0")/.." && pwd)
CONF=$HOME/.config/lagrange
DATA=$HOME/.config/gemserve
PORT=1965
mkdir -p "$CONF" "$DATA"
# The screen is small and sharp (about 230 dpi): Lagrange would draw everything twice as
# large for it, leaving room for a few lines.
export LAGRANGE_OVERRIDE_DPI=${LAGRANGE_OVERRIDE_DPI:-96}

# Lagrange remembers the certificate the server shows it, so it is kept here, where a newer
# build of the app cannot replace it.
[ -f "$DATA/localhost.pem" ] || cp "$APP/share/localhost.pem" "$DATA/localhost.pem"

set --
if [ ! -f "$CONF/prefs.cfg" ]; then
    # Pretendard for pages (the UI keeps Lagrange's font, Hangul from Pretendard), light and
    # white like isoPod, text as wide as the screen and nothing taller than it needs.
    cat >"$CONF/prefs.cfg" <<EOF
window.retain arg:1
window.setrect index:0 width:640 height:480 coord:0 0 snap:5
font.set ui:default heading:pretendard body:pretendard mono:iosevka monodoc:iosevka-body
linewidth.set arg:1000
theme.set arg:2 auto:0
ostheme arg:0
doctheme.light.set arg:4
imageloadscroll arg:0
memorysize.set arg:100
prefs.quote.italic.changed arg:0
prefs.font.warnmissing.changed arg:0
prefs.retaintabs.changed arg:1
prefs.biglede.changed arg:0
prefs.centershort.changed arg:0
EOF
    cat >"$CONF/bookmarks.ini" <<EOF
[1]
url = "gemini://localhost/"
title = "Home"
tags = ".homepage"
icon = 0x1f4f0
created = $(date +%s)
EOF
fi
[ -f "$CONF/state.lgr" ] || set -- --replace-tab gemini://localhost/

# Every start: the server as the proxy for web links, and the keys isoPod's buttons type.
# There is no mouse, so no link tooltip; the gamepad is isoPod's, typed as those keys.
cat >>"$CONF/prefs.cfg" <<EOF
proxy.http address:localhost:$PORT
prefs.gamepad.changed arg:0
prefs.menubar.changed arg:0
prefs.hidetabs.changed arg:1
prefs.hoverlink.changed arg:0
EOF
# Back is Backspace and the start page F2 (F1 is help); the rest are Lagrange's own keys.
cat >"$CONF/bindings.txt" <<EOF
30 8 0
1006 4000003b 0
EOF

if command -v python3 >/dev/null; then
    exec python3 "$APP/share/site.py" --cert "$DATA/localhost.pem" --data "$DATA" --port $PORT \
        -- "$APP/bin/lagrange" "$@"
fi
exec "$APP/bin/lagrange" "$@"
