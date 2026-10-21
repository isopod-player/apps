#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Pomodoro, a timer for isoPod: pomodoro.c against the device's SDL2, with stb_truetype
# for text. Runs in debian:bookworm (arm64) with the folder to fill as its argument.
set -e
OUT=$1
HERE=$(cd "$(dirname "$0")" && pwd)
STB=6e9f34d5429cf16790ec43c9bac3f1ee4ad1f760
STB_TRUETYPE_SHA256=ecd30b05e0dd4fea3a13c26810dd9e1992dc379049482c393d5a19e6b5090aab

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends >/dev/null 2>&1 build-essential libsdl2-dev ca-certificates curl

WORK=$(mktemp -d)
cd "$WORK"
curl -fsSLo stb_truetype.h "https://raw.githubusercontent.com/nothings/stb/$STB/stb_truetype.h"
echo "$STB_TRUETYPE_SHA256  stb_truetype.h" | sha256sum -c -

mkdir -p "$OUT/bin"
gcc -O2 -Wall -Wno-unused-function -I. "$HERE/pomodoro.c" -o "$OUT/bin/pomodoro" $(sdl2-config --cflags --libs) -lm
strip "$OUT/bin/pomodoro"
cp "$HERE/app.json" "$HERE/README.md" "$OUT/"
