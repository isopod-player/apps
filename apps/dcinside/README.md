# DCInside (디시인사이드)

DCInside to read on isoPod: galleries, posts and their comments, and the pictures in them,
in Lagrange (see [lagrange/](../../lagrange) for the buttons, the build and the licences).

[dcinside.py](dcinside.py) reads DCInside's mobile pages and answers with gemtext. Nothing
in it needs typing:

- The start page lists the galleries kept there; a gallery's page has a link to keep it or
  let it go, and the list is put in order on another page.
- Galleries are found in DCInside's own lists: popular galleries, popular minor galleries,
  every main gallery by its first letter, and every minor gallery by its field and then its
  first letter.
- A gallery's posts come thirty to a page, with its recommended posts (개념글) a link away.
- A post's comments come oldest first, a hundred to a page; DCInside's emoticons and
  pictures open under their links. A link to another post opens here too.

Writing posts and comments is not part of it.
