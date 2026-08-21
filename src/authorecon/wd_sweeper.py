#!/usr/bin/env python3
"""
============================================================
authorecon.wd_sweeper — stray Wikidata, in both directions
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

A Wikidata item existing for your work is not the same as
Wikidata knowing the work is yours, and neither is the same as
your record listing it. Three states that look identical from
any one of them.

Measured on the record this was written against: 28 works had
items and 5 of those items named the author. The other 23 were
attributed by a name string or not at all, so an author page
built from Wikidata showed 5 works out of 52. Nothing anywhere
reported that, because each system was internally consistent.

  authorecon-wd-sweeper 0000-0002-1825-0097

WHAT IT SWEEPS, BOTH WAYS

  no item        on the ORCID record, no Wikidata item exists
  unattributed   an item exists for the DOI, but it does not
                 name the author. The work is on Wikidata and
                 the author is not connected to it
  stray          Wikidata attributes a work to this author that
                 the ORCID record does not list. Sometimes an
                 unclaimed work, sometimes somebody else's

The third is the one worth having. An item wrongly attributed
to you is not visible from your side at all, and it is the
failure mode that matters when a stranger is deciding whether
a body of work is what it claims.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse

from .discover import (Problem, fetch, from_orcid, normalise_orcid,
                       valid_checksum, zenodo_concept)
from .qikstgen import author_item, wikidata_item_for

SPARQL = "https://query.wikidata.org/sparql"


def works_attributed_to(qid):
    """Everything Wikidata says this author wrote, by P50."""
    query = """SELECT ?work ?workLabel ?doi WHERE {
      ?work wdt:P50 wd:%s .
      OPTIONAL { ?work wdt:P356 ?doi }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    } LIMIT 2000""" % qid
    url = SPARQL + "?" + urllib.parse.urlencode(
        {"query": query, "format": "json"})
    doc = fetch(url, accept="application/sparql-results+json")
    out = {}
    for row in (doc.get("results") or {}).get("bindings") or []:
        item = row["work"]["value"].rsplit("/", 1)[-1]
        doi = (row.get("doi") or {}).get("value", "").lower()
        out[item] = {
            "item": item,
            "doi": doi or None,
            "title": (row.get("workLabel") or {}).get("value", ""),
        }
    return out


def sweep(orcid, log=print):
    qid = author_item(orcid)
    if not qid:
        raise Problem(
            "No Wikidata item carries this ORCID (P496), so there is no "
            "author to sweep against. Create the author item first.")
    log("  author item {}".format(qid))

    attributed = works_attributed_to(qid)
    log("  wikidata attributes {} works to that item".format(len(attributed)))

    works = from_orcid(orcid)
    log("  the ORCID record lists {} works".format(len(works)))

    by_doi = {}
    for entry in attributed.values():
        if entry["doi"]:
            by_doi[zenodo_concept(entry["doi"])] = entry

    no_item, unattributed, matched = [], [], []
    for w in works:
        if not w["doi"]:
            continue
        concept = zenodo_concept(w["doi"])
        if concept in by_doi:
            matched.append((w, by_doi[concept]))
            continue
        item = None
        for candidate in {w["doi"], concept}:
            item = wikidata_item_for(candidate)
            if item:
                break
            time.sleep(0.12)
        if item:
            unattributed.append((w, item))
        else:
            no_item.append(w)

    claimed_concepts = {zenodo_concept(w["doi"]) for w in works if w["doi"]}
    stray = [e for doi, e in by_doi.items() if doi not in claimed_concepts]
    stray += [e for e in attributed.values() if not e["doi"]]

    return {
        "author_item": qid,
        "no_item": no_item,
        "unattributed": unattributed,
        "stray": stray,
        "matched": matched,
    }


def report(result, log=print):
    log("")
    log("  MATCHED - item exists and names the author")
    log("    {}".format(len(result["matched"])))

    un = result["unattributed"]
    log("")
    log("  UNATTRIBUTED - {} item(s) exist for these works and do not name "
        "the author".format(len(un)))
    if un:
        log("    An author page built from Wikidata will not show them.")
        for w, item in un[:12]:
            log("    {:<11} {}".format(item, (w["title"] or "")[:56]))
        if len(un) > 12:
            log("    ... and {} more".format(len(un) - 12))

    ni = result["no_item"]
    log("")
    log("  NO ITEM - {} work(s) on the record have none".format(len(ni)))
    for w in ni[:8]:
        log("    {}  {}".format(w["doi"], (w["title"] or "")[:48]))
    if len(ni) > 8:
        log("    ... and {} more".format(len(ni) - 8))

    st = result["stray"]
    log("")
    log("  STRAY - {} item(s) Wikidata attributes to this author that the "
        "ORCID record does not list".format(len(st)))
    if st:
        log("    Check each. An item wrongly attributed to you is invisible")
        log("    from your side and is what a stranger sees first.")
        for e in st[:12]:
            log("    {:<11} {:<46} {}".format(
                e["item"], (e["title"] or "")[:46], e["doi"] or "no DOI"))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-wd-sweeper",
        description="Find Wikidata that disagrees with an ORCID record, in "
                    "both directions.")
    ap.add_argument("orcid")
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args(argv)

    try:
        orcid = normalise_orcid(args.orcid)
        if not valid_checksum(orcid):
            raise Problem("{} fails its check digit".format(orcid))
        result = sweep(orcid, log=lambda m: print(m, file=sys.stderr))
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    report(result, log=print)

    if args.json:
        payload = {
            "author_item": result["author_item"],
            "no_item": [{"doi": w["doi"], "title": w["title"]}
                        for w in result["no_item"]],
            "unattributed": [{"doi": w["doi"], "title": w["title"],
                              "item": item}
                             for w, item in result["unattributed"]],
            "stray": result["stray"],
            "matched_count": len(result["matched"]),
        }
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
        print("\n  wrote {}".format(args.json))

    return 1 if (result["unattributed"] or result["stray"]) else 0


if __name__ == "__main__":
    sys.exit(main())
