#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# YouTube for isoPod, a list app: youtube.py on ytdlp/ (yt-dlp and QuickJS-NG).
set -e
OUT=$1
HERE=$(cd "$(dirname "$0")" && pwd)
sh "$HERE/../../ytdlp/build.sh" "$OUT"
cp "$HERE/app.json" "$HERE/youtube.py" "$HERE/README.md" "$OUT/"
