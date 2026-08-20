# authorecon

Four checks that run before research output leaves your hands. No dependencies,
each one exits non-zero when it finds something, so they gate a build or a send.

```
pip install authorecon
```

## `submission-scrub`

Refuses to let a file reach a human with agent artifacts still in it.

```
submission-scrub paper.tex
submission-scrub --dir submission/
```

It looks where prose review does not: LaTeX `%` comments, HTML and markdown
comments, code comments, and instruction-shaped sentences addressed to the
author rather than the reader. Reading a file over is not a check.

This exists because a `.tex` formatted with AI assistance was submitted to a
journal with the assistant's own instructions still in the source. The file read
fine. Nobody scrolled the comments. The editor issued a one-year ban.

## `slop-scan`

Finds the structural habits that make prose read as machine-written.

```
slop-scan paper.md
slop-scan --strict draft.md      # fail on any hit, not only blocking ones
```

The usual advice is to grep for a word list — `delve`, `tapestry`, `leverage`.
That catches the vocabulary and misses the writing. What actually reads as
generated is structural: the contrastive pair that asserts a thing by denying
its opposite, the announced candour that tells the reader a sentence is honest
instead of being honest, the triad padded from two real items to three, the
paragraph that ends by restating itself, em dashes three to a paragraph.

None of those contain a flagged word. All of them survive a word-list scan.
So this looks for shapes. Hits are a reading list rather than an edit —
a genuine contrast is a genuine contrast — and the blocking classes are the ones
that have never once been right.

## `software-inventory`

Reports which of your repositories are in a state anyone could actually cite.

```
software-inventory ~/code/project-a ~/code/project-b --json out.json
software-inventory . --markdown
```

Per tree: remote, branch, licence, citation metadata, entry points, and every
module with its first docstring line. Then the gaps as a list. A tree with no
licence cannot be reused by someone who read the paper it belongs to; a module
with no docstring cannot be understood without reading it.

It reads the working copy rather than the remote, which is how it caught a
repository whose licence existed on GitHub while the code did not exist there
at all.

## `zenodo-precheck`

Refuses to deposit something already deposited.

```
zenodo-precheck "A Title You Are About To Deposit"
zenodo-precheck --all-drafts papers/
zenodo-precheck --software ./my-repo --related 10.5281/zenodo.1234567
```

Set `ZENODO_TOKEN` to include your own unpublished drafts, which no public
search can see.

The title mode catches a record you forgot you made. The `--software` mode
answers a different question: it lists the files attached to every related
record, looks inside any archive among them, and compares that against what your
repository actually tracks. A title check answers *has this name been used*. It
cannot answer *has this content been deposited*, and for software the second
question is the one that matters — source is routinely published as a zip
attached to a paper, under a name that resembles nothing.

Both failures these guard against happened, a few hours apart, to the author.

## Licence

MIT.
