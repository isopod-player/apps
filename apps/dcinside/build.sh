#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# DCInside (디시인사이드) for isoPod: Lagrange with dcinside.py as its site.
set -e
OUT=$1
HERE=$(cd "$(dirname "$0")" && pwd)
sh "$HERE/../../lagrange/build.sh" "$OUT"
cp "$HERE/app.json" "$HERE/README.md" "$OUT/"
cp "$HERE/dcinside.py" "$OUT/share/site.py"
