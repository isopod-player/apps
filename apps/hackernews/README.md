# Hacker News

[Hacker News](https://news.ycombinator.com), the news site of programmers and founders
that GeekNews (news.hada.io) is made after, to read on isoPod in Lagrange (see
[lagrange/](../../lagrange) for the buttons, the build and the licences).

[hackernews.py](hackernews.py) answers with gemtext:

- Its lists, from HN's API: top, new, best, Ask HN, Show HN and jobs, thirty stories to a
  page, each with its site and how many comments it has.
- A story with its points, who posted it and when, a link to read it (the page is cut down
  to its text and pictures), and its comments as a thread: the whole tree from Algolia's HN
  API at once, the first level in HN's own order, a reply marked by how deep it is.
- An HN link in a comment opens here too.

Writing comments and voting are not part of it; there is no account.
