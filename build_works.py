#!/usr/bin/env python3
"""Build works.json from what is actually live.

    ZENODO_TOKEN=... python build_works.py

Reads every published Zenodo deposition, finds the Wikidata item that carries
its concept DOI, and records both. Nothing is invented: a work with no Wikidata
item is written with "wikidata": null rather than guessed at, and the checker
decides whether that is a problem or a deliberate choice.

Run this after depositing something new. It rewrites works.json in place,
preserving the hand-maintained fields (oeis, source, exclude_reason).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
WORKS = HERE / "works.json"
UA = {"User-Agent": "authorecon/0.1 (mailto:vincegonzalez@me.com)"}
WD = "https://www.wikidata.org/w/api.php"

# Deliberate exclusions -- absence is intended, so the checker must not nag.
EXCLUDE = {
    21876791: "under review at an academic journal; no public Wikidata item "
              "until that resolves",
}
# The Modulign corpus is managed separately.
MODULIGN = {19348704, 19350848, 19351056, 19351250, 19432926, 19557382,
            19559602, 19559689, 19578571, 19642385, 19642437, 19642557,
            19643322, 19644043, 19644070, 19726994, 19726226, 19726393,
            19726401, 19726407}


def wikidata_by_doi(session, doi):
    """Find an item whose P356 is this DOI. Wikidata stores DOIs uppercase."""
    r = session.get(WD, params={
        "action": "query", "list": "search",
        "srsearch": f"haswbstatement:P356={doi.upper()}",
        "srlimit": 1, "format": "json"}, headers=UA, timeout=60)
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def main() -> None:
    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        sys.exit("Set ZENODO_TOKEN.")
    p = {"access_token": token}
    s = requests.Session()

    prior = {}
    if WORKS.exists():
        for w in json.loads(WORKS.read_text(encoding="utf-8"))["works"]:
            prior[w["zenodo"]] = w

    deps = s.get("https://zenodo.org/api/deposit/depositions",
                 params={**p, "size": 100}, timeout=90).json()
    works = []
    for d in deps:
        rid = d["id"]
        if not d.get("submitted") or rid in MODULIGN:
            continue
        md = d["metadata"]
        concept = d.get("conceptdoi")
        old = prior.get(rid, {})
        qid = old.get("wikidata")
        if not qid and concept:
            qid = wikidata_by_doi(s, concept)
            time.sleep(0.2)
        works.append({
            "zenodo": rid,
            "title": md["title"],
            "doi": md.get("doi"),
            "concept_doi": concept,
            "date": md.get("publication_date"),
            "type": md.get("upload_type"),
            "wikidata": qid,
            # hand-maintained, preserved across rebuilds
            "oeis": old.get("oeis", []),
            "source": old.get("source"),
            "exclude_reason": EXCLUDE.get(rid, old.get("exclude_reason")),
            "cites": sorted({r["identifier"]
                             for r in md.get("related_identifiers", [])
                             if r.get("relation") in ("cites", "references")}),
        })
    works.sort(key=lambda w: w["zenodo"])
    WORKS.write_text(json.dumps(
        {"author": {"name": "Vincent Gonzalez",
                    "orcid": "0009-0005-3640-014X",
                    "wikidata": "Q140936504"},
         "works": works}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    linked = sum(1 for w in works if w["wikidata"])
    print(f"{len(works)} works  |  {linked} with a Wikidata item  |  "
          f"{sum(len(w['cites']) for w in works)} citation edges recorded")
    print(f"wrote {WORKS}")


if __name__ == "__main__":
    main()
