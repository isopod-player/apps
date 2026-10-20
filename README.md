# isoPod apps

Apps for [isoPod](https://github.com/hypulse/isopod), the iPod-like system for the Anbernic
RG35XX SP. Each folder in `apps/` builds into a folder that goes into the device's `Apps`
storage over the USB cable. What an app folder holds and how isoPod runs it:
[docs/apps.md](https://github.com/hypulse/isopod/blob/isopod/isopod/docs/apps.md).

## Apps

None yet.

## Install

Build an app, or take its zip from the latest run of the `Build` workflow, and copy the
folder (`dist/<app>/`, or the one inside the zip) into `Apps` over the cable. It is under
Apps on the home screen within seconds.

## Build

```sh
./build.sh <app>
```

This needs Docker and builds in an arm64 Debian bookworm container, natively on Apple
silicon or an arm64 Linux machine. It writes `dist/<app>/` and `dist/<app>.zip`.

## Adding an app

`apps/<app>/build.sh` runs in that container with the folder to fill as its argument: it
installs what it needs with apt, builds, and leaves `app.json` and everything the app runs
from in that folder. Bookworm's glibc (2.36) is older than the device's (2.44), so its
programs run there; libraries the device lacks go in the app's `lib/`.

## Licence

The build scripts and isoPod's own files here are GPL-2.0-or-later, as isoPod is. Each
program an app brings keeps its own licence, named in the app's folder.
