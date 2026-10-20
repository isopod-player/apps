#!/bin/sh
# Build one app for isoPod (aarch64): dist/<app>/ is the folder to copy into Apps.
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)
APP=$1
if [ -z "$APP" ] || [ ! -f "$ROOT/apps/$APP/build.sh" ]; then
    echo "usage: $0 <app>, one of: $(ls "$ROOT/apps" | tr '\n' ' ')" >&2
    exit 2
fi
rm -rf "$ROOT/dist/$APP" "$ROOT/dist/$APP.zip"
mkdir -p "$ROOT/dist/$APP"
docker run --rm --platform linux/arm64 -v "$ROOT":/src -w "/src/apps/$APP" debian:bookworm \
    sh "/src/apps/$APP/build.sh" "/src/dist/$APP"
cd "$ROOT/dist"
zip -qr "$APP.zip" "$APP"
