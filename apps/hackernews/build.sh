#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Hacker News for isoPod: Lagrange with hackernews.py as its site.
set -e
OUT=$1
HERE=$(cd "$(dirname "$0")" && pwd)
sh "$HERE/../../lagrange/build.sh" "$OUT"
cp "$HERE/app.json" "$HERE/README.md" "$OUT/"
cp "$HERE/hackernews.py" "$OUT/share/site.py"
