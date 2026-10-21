# yt-dlp for list apps

What isoPod's list apps that play from YouTube share: [yt-dlp](https://github.com/yt-dlp/yt-dlp)
and [QuickJS-NG](https://quickjs-ng.github.io/quickjs/), and `ytlib.py`. This folder is not
an app itself; an app's `build.sh` runs `build.sh` here with the folder to fill, then adds
its `app.json` and its module beside `ytlib.py`:

```sh
sh "$HERE/../../ytdlp/build.sh" "$OUT"
cp "$HERE/app.json" "$HERE/myapp.py" "$OUT/"
```

- yt-dlp is its zipimport release, which runs on the device's Python and carries
  [yt-dlp-ejs](https://github.com/yt-dlp/ejs), the scripts that answer YouTube's player;
  QuickJS-NG's `qjs`, built here, runs them.
- `ytlib.py` imports yt-dlp once, in the background as the app starts, since that takes
  seconds on the device; answers isoPod's questions; keeps the app's state in its data
  folder; and picks streams for the screen: up to 480p, H.264 where YouTube offers it, with
  AAC beside it, played by isoPod with the sound as a second file.
- The app's "Update yt-dlp" fetches the latest yt-dlp, checked against its release's
  checksums, into the app's data folder for the next start: YouTube changes often, and
  yt-dlp follows within days.

Some searches YouTube in Korea answers only to an account that has proved its age; they
come back empty. There is no account.

## Licences

yt-dlp and yt-dlp-ejs are Unlicense (yt-dlp-ejs bundles MIT and ISC code, whose notices are
in its scripts), QuickJS-NG MIT; their texts are in `licenses/` in a built app.
`ytlib.py` and the scripts are GPL-2.0-or-later.
