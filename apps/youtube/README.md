# YouTube

YouTube as an isoPod list app: isoPod shows its pages as its own lists, and plays a video
in its own player, so the volume, the lid, a headset's buttons and Home work as they do
for a video from the card (see [ytdlp/](../../ytdlp) for how it reaches YouTube, and the
licences). There is no account.

- Search, with isoPod's keyboard. The searches made lately are kept.
- A video opens on a page of its own: Play, Save, and its channel. A live stream plays as
  it goes; it cannot be saved.
- A channel found in the results shows its videos, and can be kept on the first page.
- The videos watched are kept too.
- Saved videos go into Videos, in a folder named `YouTube`, one MP4 file each: they play
  without the network, from Saved here or from Videos, and are there over the cable.
  Saving goes on after the app is left. When nothing plays isoPod puts the device to
  sleep, and the saving waits for it; one cut off goes on when the app is opened again.
- Settings: the quality to play in and to save in, 360p to 1080p (480p, the screen's, unless
  chosen otherwise); clearing the searches and the videos watched; and "Update yt-dlp" for
  when YouTube has changed.

A row that does something rather than open a page (Save, a quality, clearing) shows a few
words of what it did and leaves the page where it is; the page shows the change when it is
opened again.

[youtube.py](youtube.py) has the pages.
