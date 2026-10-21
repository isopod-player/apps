#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# yt-dlp for an isoPod list app that plays from YouTube: an app's build.sh runs this with
# the folder to fill, then adds its app.json and its module beside ytlib.py. Runs in
# debian:bookworm (arm64); the device's Python runs the app.
set -e
OUT=$1
HERE=$(cd "$(dirname "$0")" && pwd)
YT_DLP=2026.08.19
YT_DLP_SHA256=1fa6733c37ea6fb51c99ad8fe785e7b7e5f3246c9b980230329d4fb72ed8d4d6
QUICKJS=0.17.0
QUICKJS_SHA256=559bc4c420475e55c7ab4510adbc562f55d7524d75e8e89d79ce4bb02f5687d9
FFMPEG=9.0.2
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends >/dev/null 2>&1 build-essential cmake ca-certificates curl xz-utils

WORK=$(mktemp -d)
cd "$WORK"
# yt-dlp's zipimport release runs on the device's Python and carries yt-dlp-ejs, the
# scripts that answer YouTube's player.
curl -fsSLo yt-dlp "https://github.com/yt-dlp/yt-dlp/releases/download/$YT_DLP/yt-dlp"
curl -fsSLo yt-dlp.LICENSE "https://raw.githubusercontent.com/yt-dlp/yt-dlp/$YT_DLP/LICENSE"
curl -fsSLo quickjs.tar.gz "https://github.com/quickjs-ng/quickjs/archive/refs/tags/v$QUICKJS.tar.gz"
curl -fsSLo ffmpeg.tar.xz "https://ffmpeg.org/releases/ffmpeg-$FFMPEG.tar.xz"
sha256sum -c - <<SUMS
$YT_DLP_SHA256  yt-dlp
$QUICKJS_SHA256  quickjs.tar.gz
$FFMPEG_SHA256  ffmpeg.tar.xz
SUMS

# QuickJS-NG's qjs, the JavaScript engine yt-dlp runs those scripts with.
tar xzf quickjs.tar.gz
{
    cmake -S "quickjs-$QUICKJS" -B qjs-build -DCMAKE_BUILD_TYPE=Release &&
        cmake --build qjs-build -j "$(nproc)" --target qjs_exe
} >qjs-build.log 2>&1 || { tail -n 60 qjs-build.log; exit 1; }

# FFmpeg's ffmpeg, only for yt-dlp to put a saved video's picture and sound in one MP4 file:
# it copies them as they are, so there are no codecs, and no network. Linked statically.
tar xJf ffmpeg.tar.xz
(
    cd "ffmpeg-$FFMPEG" &&
        ./configure --disable-everything --disable-autodetect --disable-doc --disable-debug \
            --disable-ffplay --disable-ffprobe --disable-network --disable-avdevice --enable-small \
            --enable-protocol=file,pipe --enable-demuxer=mov,matroska,aac,mpegts \
            --enable-muxer=mp4,mov,ipod,matroska,webm --enable-parser=h264,hevc,aac,vp9,av1,opus \
            --enable-bsf=aac_adtstoasc,extract_extradata,vp9_superframe \
            --extra-ldflags=-static --pkg-config-flags=--static &&
        make -j "$(nproc)" ffmpeg
) >ffmpeg-build.log 2>&1 || { tail -n 60 ffmpeg-build.log; exit 1; }

mkdir -p "$OUT/bin" "$OUT/share" "$OUT/licenses"
install -m 755 qjs-build/qjs "$OUT/bin/qjs"
strip "$OUT/bin/qjs"
install -m 755 "ffmpeg-$FFMPEG/ffmpeg" "$OUT/bin/ffmpeg"
strip "$OUT/bin/ffmpeg"
cp yt-dlp "$OUT/share/yt-dlp"
cp "$HERE/ytlib.py" "$OUT/"
cp yt-dlp.LICENSE "$OUT/licenses/yt-dlp.txt"
cp "quickjs-$QUICKJS/LICENSE" "$OUT/licenses/QuickJS-NG.txt"
cp "ffmpeg-$FFMPEG/COPYING.LGPLv2.1" "$OUT/licenses/FFmpeg.txt"
