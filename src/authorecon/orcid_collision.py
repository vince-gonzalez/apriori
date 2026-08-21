#!/usr/bin/env python3
"""
============================================================
authorecon.orcid_collision — who else publishes under this
                             name?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

Your ORCID is unique. Your name is not.

Indexes reconcile authorship by name far more often than by
identifier, because most records arrive without an identifier
at all. So a body of work published under a name you share is
one bad match away from being attributed to you, or yours to
them - and neither of you can see it from your own record.

Measured on the record this was written against: thirteen
distinct authors in OpenAlex share the name, one of them with
a different ORCID and fifteen works, two more with no ORCID
and nineteen works between them.

  authorecon-orcid-collision 0000-0002-1825-0097

WHY IT MATTERS TO SOMEBODY ELSE

This is the tool an editor wants and an author rarely runs. A
submission from an unfamiliar name is assessed by searching
that name, and what comes back is every author who shares it.
Knowing which of those is the same person, and which is three
different people, is the first question - and nothing on the
author's own record answers it.

WHAT IT REPORTS

  same        the identifier matches. This is you
  no orcid    an author record with no identifier at all. Might
              be you unclaimed, might be somebody else. This is
              where a wrong merge comes from
  different   a different ORCID under the same name. A
              different person, unless two records exist for
              one person

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse

from .name_privacy import WITHHELD, fragmentation, redact
from .discover import (CONTACT, Problem, fetch, normalise_orcid, valid_checksum,
                       author_name)

AUTHORS = "https://api.openalex.org/authors"

SAME, NO_ORCID, DIFFERENT = "same", "no orcid", "different"


def bare(orcid_url):
    return (orcid_url or "").rstrip("/").rsplit("/", 1)[-1] or None


def candidates(name, mailto=None):
    params = {"filter": "display_name.search:" + name, "per-page": "50"}
    params["mailto"] = mailto or CONTACT
    doc = fetch(AUTHORS + "?" + urllib.parse.urlencode(params))
    return (doc.get("meta") or {}).get("count", 0), doc.get("results") or []


def classify(results, orcid):
    out = []
    for a in results:
        theirs = bare(a.get("orcid"))
        if theirs == orcid:
            kind = SAME
        elif not theirs:
            kind = NO_ORCID
        else:
            kind = DIFFERENT
        top = (a.get("topics") or [{}])
        out.append({
            "kind": kind,
            "id": (a.get("id") or "").rsplit("/", 1)[-1],
            "name": a.get("display_name") or "",
            "orcid": theirs,
            "works": a.get("works_count") or 0,
            "cited": a.get("cited_by_count") or 0,
            "field": (top[0].get("display_name") if top and top[0] else "") or "",
        })
    order = {SAME: 0, NO_ORCID: 1, DIFFERENT: 2}
    out.sort(key=lambda r: (order[r["kind"]], -r["works"]))
    return out


def report(name, total, rows, log=print):
    log("")
    log('  "{}"'.format(name))
    log("  {} author record(s) in OpenAlex share this name".format(total))
    log("")
    log("  {:<10} {:<12} {:<21} {:>6} {:>7}  {}".format(
        "", "id", "orcid", "works", "cited", "field"))
    for r in rows:
        log("  {:<10} {:<12} {:<21} {:>6} {:>7}  {}".format(
            r["kind"], r["id"], r["orcid"] or "-", r["works"], r["cited"],
            r["field"][:34]))

    # An ORCID should map to one author record. More than one means the
    # index has split the same person, and every count shown anywhere is a
    # count of one fragment. This is invisible from the author's own record,
    # which knows nothing about how an index has bucketed it.
    mine = [r for r in rows if r["kind"] == SAME]
    if len(mine) > 1:
        log("")
        log("  SPLIT IDENTITY - {} author records carry this same ORCID:"
            .format(len(mine)))
        for r in mine:
            log("    {}  {} works, {} citations, {}".format(
                r["id"], r["works"], r["cited"], r["field"][:38]))
        log("  One identifier, several author records. Anything that reports")
        log("  a total per author reports one fragment of the work.")

    unidentified = [r for r in rows if r["kind"] == NO_ORCID]
    if unidentified:
        works = sum(r["works"] for r in unidentified)
        log("")
        log("  {} author record(s) with no identifier, {} works between them."
            .format(len(unidentified), works))
        log("  Each is either yours unclaimed or somebody else's. An index")
        log("  reconciling by name cannot tell, and neither can your record.")

    # A name this author no longer uses is counted and not printed. The
    # fragmentation is the actionable half; the name is the half that can
    # hurt somebody. See name_privacy.
    split = fragmentation(rows, name)
    if split:
        log("")
        log("  {}".format(split))

    others = [r for r in rows if r["kind"] == DIFFERENT]
    if others:
        log("")
        log("  {} other identified author(s) under this name. Anyone assessing"
            .format(len(others)))
        log("  a submission by searching the name sees their work beside yours.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-orcid-collision",
        description="Find every author who publishes under the same name.")
    ap.add_argument("orcid")
    ap.add_argument("--name", help="search this name instead of the one ORCID "
                                   "publishes")
    ap.add_argument("--mailto")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    try:
        orcid = normalise_orcid(args.orcid)
        if not valid_checksum(orcid):
            raise Problem("{} fails its check digit".format(orcid))
        name = args.name or author_name(orcid)
        if not name:
            raise Problem(
                "That ORCID publishes no name, so there is nothing to search. "
                "Pass --name to search one anyway.")
        total, results = candidates(name, mailto=args.mailto)
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    rows = classify(results, orcid)
    report(name, total, rows, log=print)

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"name": name, "orcid": orcid, "total": total,
                       "names_withheld": WITHHELD,
                       "authors": redact(rows)}, fh, indent=1,
                      ensure_ascii=False)
        print("\n  wrote {}".format(args.json))

    return 1 if any(r["kind"] != SAME for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
