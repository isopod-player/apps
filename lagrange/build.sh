#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Lagrange for an isoPod app that reads a site as Gemini: an app's build.sh runs this with
# the folder to fill, then adds its app.json and its site module as share/site.py. Runs in
# debian:bookworm (arm64).
set -e
OUT=$1
HERE=$(cd "$(dirname "$0")" && pwd)
LAGRANGE=1.21.2
LAGRANGE_SHA256=ae9439b26d569d1d3efa682f591cc0e34eb5314f13ef18840c18a2d57e8cd677
PRETENDARD=1.3.9
PRETENDARD_SHA256=04be351a74d6bf7d60c480a3087e51d185485d35a52023142af1df19eb8c428a
LIBDIR=/usr/lib/aarch64-linux-gnu

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends >/dev/null 2>&1 \
    build-essential cmake meson ninja-build pkg-config patch ca-certificates curl unzip zip openssl \
    libsdl2-dev libssl-dev libpcre2-dev libwebp-dev zlib1g-dev libfribidi-dev libunistring-dev

WORK=$(mktemp -d)
cd "$WORK"
curl -fsSLo lagrange.tar.gz \
    "https://github.com/skyjake/lagrange/releases/download/v$LAGRANGE/lagrange-$LAGRANGE.tar.gz"
curl -fsSLo pretendard.zip \
    "https://github.com/orioncactus/pretendard/releases/download/v$PRETENDARD/Pretendard-$PRETENDARD.zip"
sha256sum -c - <<EOF
$LAGRANGE_SHA256  lagrange.tar.gz
$PRETENDARD_SHA256  pretendard.zip
EOF

# Lagrange, with isoPod's changes. HarfBuzz is its own copy, built in; OpenSSL, PCRE2 and
# libwebp are linked statically, by hiding their shared libraries from the linker. The
# device's SDL2 and zlib are used, and FriBidi and libunistring (LGPL) go in lib/.
tar xzf lagrange.tar.gz
cd "lagrange-$LAGRANGE"
for p in "$HERE"/patches/*.patch; do
    patch -p1 <"$p"
done
sed -i 's/libwebpdecoder/libwebp/' cmake/Depends.cmake  # Debian packages only the whole libwebp
for lib in ssl crypto pcre2-8 webp; do
    rm "$LIBDIR/lib$lib.so"
done
# Its many warnings (OpenSSL 3 deprecations) go to a log, shown only if the build fails.
{
    cmake -S . -B build -Wno-dev -DCMAKE_BUILD_TYPE=Release \
        -DENABLE_HARFBUZZ_MINIMAL=ON -DENABLE_FRIBIDI_BUILD=OFF -DENABLE_WEBP=ON \
        -DENABLE_GAMEPAD=OFF -DENABLE_POPUP_MENUS=OFF -DENABLE_IPC=OFF -DENABLE_X11_XLIB=OFF \
        -DENABLE_MPG123=OFF -DENABLE_OPUS=OFF -DENABLE_JXL=OFF -DTFDN_ENABLE_WARN_ERROR=OFF &&
        cmake --build build -j "$(nproc)"
} >build.log 2>&1 || { tail -n 60 build.log; exit 1; }

mkdir -p "$OUT/bin" "$OUT/lib" "$OUT/share/lagrange" "$OUT/licenses"
install -m 755 build/lagrange "$OUT/bin/lagrange"
strip "$OUT/bin/lagrange"
install -m 755 "$HERE/start.sh" "$OUT/bin/start"
cp build/resources.lgr "$OUT/share/lagrange/"
for lib in libfribidi.so.0 libunistring.so.2; do
    cp -L "$LIBDIR/$lib" "$OUT/lib/"
done
cp "$HERE/gemserve.py" "$OUT/share/"

# Pretendard as a fontpack, found by Lagrange beside its resources.
mkdir fontpack
unzip -q -j ../pretendard.zip -d fontpack \
    public/static/Pretendard-Regular.otf public/static/Pretendard-SemiBold.otf \
    public/static/Pretendard-Bold.otf LICENSE.txt
cp "$HERE/fontpack.ini" fontpack/
(cd fontpack && zip -q -9 "$OUT/share/lagrange/pretendard.fontpack" fontpack.ini *.otf)

# The certificate the site's server shows localhost with. The start script keeps the first
# one it finds, as Lagrange remembers it.
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 36500 \
    -subj /CN=localhost -addext subjectAltName=DNS:localhost \
    -keyout key.pem -out cert.pem 2>/dev/null
cat cert.pem key.pem >"$OUT/share/localhost.pem"

L=$OUT/licenses
cp LICENSE.md "$L/Lagrange.md"
cp lib/the_Foundation/LICENSE "$L/the_Foundation.txt"
cp lib/harfbuzz/COPYING "$L/HarfBuzz.txt"
cp res/fonts/LICENSE_OFL.txt "$L/OFL-Lagrange-fonts.txt"
cp res/fonts/LICENSE_Roboto.txt "$L/Roboto.txt"
cp res/fonts/LICENSE_SmolEmoji.txt "$L/SmolEmoji.txt"
cp fontpack/LICENSE.txt "$L/Pretendard-OFL.txt"
cp /usr/share/doc/libfribidi0/copyright "$L/FriBidi.txt"
cp /usr/share/doc/libunistring2/copyright "$L/libunistring.txt"
cp /usr/share/doc/libssl3/copyright "$L/OpenSSL.txt"
cp /usr/share/doc/libpcre2-8-0/copyright "$L/PCRE2.txt"
cp /usr/share/doc/libwebp7/copyright "$L/libwebp.txt"
