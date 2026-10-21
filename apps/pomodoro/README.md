# Pomodoro (포모도로)

A timer for isoPod whose whole screen is its clock face, in flat colours. The time left is
the kind's colour and the time gone a deep shade of it, parted by a white hand that sweeps
from the top round, as a game shows a skill cooling down. A tick for each minute runs round
the edge of the screen, every fifth longer, and a white dial in the middle holds the time.
Focus is coral, a short break green, and the long break after four focuses indigo; when
the time runs out a chime rings, the screen flashes, and the next one waits for A.

| Button | |
| --- | --- |
| A | Start, stop |
| B | Close the app |
| X | Start this one over |
| Y | Skip to the next |
| Left, Right | Focus, short break or long break (while stopped) |
| Up, Down | How many minutes (while stopped) |

The screen stays lit while it is in front. The end is kept as a time of day, so a timer
goes on while the app waits behind Home, or after it is closed: it is there, or done, when
the app is back. The chime rings when the time runs out with the app in front; one that ran
out while it was away is shown, not rung. Minutes, the round of four and today's count are
kept in the app's data folder.

[pomodoro.c](pomodoro.c) draws everything itself, with edges blended by their distance, on
the device's SDL2; the text is Pretendard, isoPod's own font, through
[stb_truetype](https://github.com/nothings/stb) (public domain, or MIT).
