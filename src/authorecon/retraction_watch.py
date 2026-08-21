#!/usr/bin/env python3
"""
============================================================
authorecon.retraction_watch — is anything here, or anything
                              it cites, retracted?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

A retraction happens after publication, and nothing goes back
to tell the works that cited the paper. Your reference list was
correct the day you wrote it and may not be correct now.

Citing retracted work is a real hazard - it undermines the
argument that rests on it and it is the first thing a hostile
reader looks for. The data is public. Almost nobody checks,
because checking means resolving every reference by hand.

  authorecon-retraction-watch 0000-0002-1825-0097

TWO DIRECTIONS

  authored  a work on this record that has been retracted
  cited     a work this record cites that has been retracted

The second is the one that surprises people. The first is
rare and unmissable; the second accumulates silently as the
literature changes underneath a finished paper.

WHAT A CLEAN RESULT MEANS

That OpenAlex records no retraction for anything checked. A
retraction it has not ingested will not appear here, so a
clean result is evidence and not a guarantee - which is worth
saying because the opposite claim would be more useful and
less true.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

from .discover import (Problem, fetch, from_orcid, normalise_orcid,
                       valid_checksum)
from .qikstgen import ZENODO_RECORD

OPENALEX_WORK = "https://api.openalex.org/works/doi:{}"


def openalex(doi):
    try:
        return fetch(OPENALEX_WORK.format(doi))
    except Problem:
        return None


def cited_dois(doi):
    """The DOIs a Zenodo record says it cites or references."""
    m = re.search(r"zenodo\.(\d+)$", doi or "", re.I)
    if not m:
        return []
    try:
        rec = fetch(ZENODO_RECORD.format(m.group(1)))
    except Problem:
        return []
    out = []
    for rel in (rec.get("metadata") or {}).get("related_identifiers") or []:
        if (rel.get("relation") or "").lower() not in ("cites", "references"):
            continue
        ident = (rel.get("identifier") or "").strip()
        if ident.lower().startswith("10."):
            out.append(ident.lower())
    return out


def scan(orcid, log=print):
    works = [w for w in from_orcid(orcid) if w["doi"]]
    log("  {} works with a DOI".format(len(works)))

    authored, cited, unchecked, seen = [], [], [], {}
    for w in works:
        rec = openalex(w["doi"])
        if rec is None:
            unchecked.append((w["doi"], "not in OpenAlex"))
        elif rec.get("is_retracted"):
            authored.append({"doi": w["doi"], "title": w["title"]})
            log("    RETRACTED (authored)  {}".format(w["doi"]))

        for ref in cited_dois(w["doi"]):
            if ref in seen:
                state = seen[ref]
            else:
                r = openalex(ref)
                state = ("unknown" if r is None
                         else ("retracted" if r.get("is_retracted") else "ok"))
                seen[ref] = state
                time.sleep(0.1)
            if state == "retracted":
                cited.append({"from": w["doi"], "cites": ref,
                              "title": w["title"]})
                log("    RETRACTED (cited)     {} <- cited by {}".format(
                    ref, w["doi"]))
            elif state == "unknown":
                unchecked.append((ref, "cited, not in OpenAlex"))
        time.sleep(0.06)
    return authored, cited, unchecked, len(seen)


def report(authored, cited, unchecked, refs, log=print):
    log("")
    log("  {} distinct cited DOI(s) checked".format(refs))

    if authored:
        log("")
        log("  RETRACTED, AUTHORED - {}".format(len(authored)))
        for a in authored:
            log("    {}  {}".format(a["doi"], (a["title"] or "")[:56]))
    else:
        log("    nothing on this record is recorded as retracted")

    if cited:
        log("")
        log("  RETRACTED, CITED - {}".format(len(cited)))
        for c in cited:
            log("    {}".format(c["cites"]))
            log("      cited by {}  {}".format(c["from"],
                                                (c["title"] or "")[:44]))
    else:
        log("    nothing it cites is recorded as retracted")

    if unchecked:
        distinct = sorted({u[0] for u in unchecked})
        log("")
        log("  NOT CHECKED - {} identifier(s) OpenAlex does not hold, so no "
            "retraction status exists to read".format(len(distinct)))
        for d in distinct[:6]:
            log("    {}".format(d))
        if len(distinct) > 6:
            log("    ... and {} more".format(len(distinct) - 6))
        log("")
        log("  A clean result covers what was checkable. It is evidence that")
        log("  no retraction is recorded, not a guarantee that none exists.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-retraction-watch",
        description="Check a record and everything it cites for retractions.")
    ap.add_argument("orcid")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    try:
        orcid = normalise_orcid(args.orcid)
        if not valid_checksum(orcid):
            raise Problem("{} fails its check digit".format(orcid))
        authored, cited, unchecked, refs = scan(
            orcid, log=lambda m: print(m, file=sys.stderr))
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    report(authored, cited, unchecked, refs, log=print)

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"orcid": orcid, "authored": authored, "cited": cited,
                       "unchecked": [list(u) for u in unchecked]},
                      fh, indent=1, ensure_ascii=False)
        print("\n  wrote {}".format(args.json))
    return 1 if (authored or cited) else 0


if __name__ == "__main__":
    sys.exit(main())
