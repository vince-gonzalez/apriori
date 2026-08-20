```
╔════════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                            ║
║    █████╗ ██╗   ██╗████████╗██╗  ██╗ ██████╗ ██████╗ ███████╗ ██████╗ ██████╗ ███╗   ██╗   ║
║   ██╔══██╗██║   ██║╚══██╔══╝██║  ██║██╔═══██╗██╔══██╗██╔════╝██╔════╝██╔═══██╗████╗  ██║   ║
║   ███████║██║   ██║   ██║   ███████║██║   ██║██████╔╝█████╗  ██║     ██║   ██║██╔██╗ ██║   ║
║   ██╔══██║██║   ██║   ██║   ██╔══██║██║   ██║██╔══██╗██╔══╝  ██║     ██║   ██║██║╚██╗██║   ║
║   ██║  ██║╚██████╔╝   ██║   ██║  ██║╚██████╔╝██║  ██║███████╗╚██████╗╚██████╔╝██║ ╚████║   ║
║   ╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝   ║
║                                                                                            ║
║               does every place your work lives still agree with the others?                ║
║                                                                                            ║
╚════════════════════════════════════════════════════════════════════════════════════════════╝
```

Reconciles a body of published work against every place it lives.

Publishing is easy. Keeping twenty-nine deposits, twenty-eight Wikidata items,
three OEIS sequences and a hundred-odd citation edges in agreement with each
other is the part that gets harder every time you publish. This does that part.

    ZENODO_TOKEN=... python build_works.py     # rebuild works.json from live data
    ZENODO_TOKEN=... python authorecon.py      # check everything, report the news

`authorecon.py` exits non-zero when something is wrong and unexplained, so it
can run on a schedule and stay silent until it has something to say.

## What it checks

| check | question |
|---|---|
| COVERAGE | does every deposit have a Wikidata item, or a stated reason it doesn't? |
| INTEGRITY | does every item still resolve, carry the right DOI, and name the right author? |
| INDEXING | is every work in OpenAlex, and has anyone cited it since last run? |
| OEIS | does every sequence link the paper it came from? |
| GRAPH | how much of the citation list is expressible on Wikidata? |

## What it will not do

It does not invent identifiers. A work with no Wikidata item is recorded as
`"wikidata": null`, not guessed at. A deliberate absence carries an
`exclude_reason` and is reported as *skipped*, never as a problem — record 21876791
is out of the graph on purpose while it is under journal review.

It does not treat a self-citation as a citation. On the first run OpenAlex
reported two citations of the gonzalgo Indexes; both were the Kernel Trust
Profile, the author's own work, double-counted because OpenAlex holds two
records for it.

## Findings from the first run

- `Q140936313` (OpticQuiz PPPG) carries the **version** DOI in `P356` where
  every other item carries the **concept** DOI. Recorded rather than silently
  patched.
- Three OEIS sequences — A398262, A398309, A398310 — do not link
  *First-Return Walks on Vertex-Transitive Graphs*, the paper they come from.
- Eight recent deposits are not yet in OpenAlex; ingestion lags publication.

## works.json

One row per work: Zenodo id, title, both DOIs, date, type, Wikidata QID, OEIS
sequence numbers, source path, and every identifier it cites. `build_works.py`
rewrites it from live data and preserves the hand-maintained fields
(`oeis`, `source`, `exclude_reason`, `note`).

`state.json` holds only the last-seen citation counts, so a new citation is
reported once instead of every run.

---

```
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║      ███████╗      ██╗  ██╗███████╗██╗   ██╗███████╗       ║
║      ██╔════╝      ██║ ██╔╝██╔════╝╚██╗ ██╔╝██╔════╝       ║
║      █████╗  █████╗█████╔╝ █████╗   ╚████╔╝ ███████╗       ║
║      ██╔══╝  ╚════╝██╔═██╗ ██╔══╝    ╚██╔╝  ╚════██║       ║
║      ██║           ██║  ██╗███████╗   ██║   ███████║       ║
║      ╚═╝           ╚═╝  ╚═╝╚══════╝   ╚═╝   ╚══════╝       ║
║                                                            ║
║               ·   C  R  E  A  T  I  V  E   ·               ║
║                                                            ║
║          ────────────────────────────────────────          ║
║                                                            ║
║                      Vincent Gonzalez                      ║
║                         f-keys.com                         ║
║                 ORCID 0009-0005-3640-014X                  ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
```

Part of [F-Keys](https://f-keys.com) — independent hardware, software
and internet products. See the [working log](https://f-keys.com/log/)
and [live status](https://f-keys.com/status/).
