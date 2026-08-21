#!/usr/bin/env python3
"""
============================================================
authorecon.venue_reality — where was this actually published?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

"Published" covers two very different things. A work in a
peer-reviewed journal passed through other people. A work in a
repository was posted by its author. Both are legitimate, both
get a DOI, both appear on a record identically, and a list of
DOIs does not distinguish them.

Anyone assessing an unfamiliar body of work wants that split
first, and getting it currently means opening every DOI.

  authorecon-venue-reality 0000-0002-1825-0097

WHAT IT REPORTS

  repository   posted by the author. Zenodo, arXiv, OSF, SSRN
  journal      a periodical, with its ISSN and DOAJ listing
  conference   proceedings
  unknown      no venue OpenAlex can name

WHAT IT REFUSES TO DO

Score a venue. There is no reliable public list of predatory
journals, the well-known one was withdrawn under legal
pressure, and a tool that labels a venue disreputable on a
guess would do real harm to somebody's career.

It also does not read DOAJ absence as a warning. The
Proceedings of the National Academy of Sciences is not in
DOAJ, because DOAJ lists open access journals and PNAS is not
one. Absence there means "not an open access journal", nothing
more, and treating it as a quality signal would be worse than
reporting nothing.

The one thing it does flag: a venue OpenAlex calls a journal
while holding no ISSN for it. A periodical with no ISSN is
genuinely unusual and worth a human looking.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time

from .discover import (Problem, fetch, from_orcid, normalise_orcid,
                       valid_checksum)

OPENALEX_WORK = "https://api.openalex.org/works/doi:{}"


def venue_of(doi):
    try:
        w = fetch(OPENALEX_WORK.format(doi))
    except Problem:
        return None
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    if not src:
        return {"kind": "unknown", "name": None, "issn": None,
                "doaj": None, "apc": None, "publisher": None}
    return {
        "kind": src.get("type") or "unknown",
        "name": src.get("display_name"),
        "issn": src.get("issn_l"),
        "doaj": src.get("is_in_doaj"),
        "apc": src.get("apc_usd"),
        "publisher": src.get("host_organization_name"),
    }


def survey(orcid, log=print):
    works = [w for w in from_orcid(orcid) if w["doi"]]
    log("  {} works with a DOI".format(len(works)))
    rows = []
    for w in works:
        v = venue_of(w["doi"])
        if v is None:
            rows.append({"doi": w["doi"], "title": w["title"],
                         "kind": "not indexed", "name": None, "issn": None,
                         "doaj": None, "apc": None, "publisher": None})
        else:
            v.update({"doi": w["doi"], "title": w["title"]})
            rows.append(v)
        time.sleep(0.08)
    return rows


def report(rows, log=print):
    kinds = collections.Counter(r["kind"] for r in rows)
    total = len(rows)
    log("")
    log("  {} works".format(total))
    for kind, n in kinds.most_common():
        log("    {:<14} {:>3}   ({:.0f}%)".format(kind, n, 100.0 * n / total))

    venues = collections.Counter(
        r["name"] for r in rows if r["name"])
    if venues:
        log("")
        log("  VENUES")
        for name, n in venues.most_common(12):
            sample = next(r for r in rows if r["name"] == name)
            bits = [sample["kind"]]
            if sample["issn"]:
                bits.append("ISSN " + sample["issn"])
            if sample["doaj"]:
                bits.append("in DOAJ")
            if sample["apc"]:
                bits.append("APC ${}".format(sample["apc"]))
            log("    {:>3}  {:<44} {}".format(n, name[:44], ", ".join(bits)))

    repos = kinds.get("repository", 0)
    journals = kinds.get("journal", 0)
    if repos and not journals:
        log("")
        log("  Every work here is a repository deposit. None appears in a")
        log("  journal, which means none of it went through peer review at")
        log("  the venue. That is a legitimate way to publish and it is not")
        log("  the same thing, so it is stated rather than left to be")
        log("  discovered.")
    elif repos and journals:
        log("")
        log("  {} in journals, {} deposited to repositories.".format(
            journals, repos))

    odd = [r for r in rows if r["kind"] == "journal" and not r["issn"]]
    if odd:
        log("")
        log("  NO ISSN - {} work(s) in something called a journal that has "
            "none".format(len(odd)))
        for r in odd[:8]:
            log("    {}  {}".format(r["name"], r["doi"]))
        log("  A periodical without an ISSN is unusual. This is the only")
        log("  thing here worth a second look, and it is a prompt to look,")
        log("  not a verdict.")

    missing = [r for r in rows if r["kind"] == "not indexed"]
    if missing:
        log("")
        log("  {} work(s) are not in OpenAlex, so no venue could be read"
            .format(len(missing)))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-venue-reality",
        description="Split a body of work by where it was actually published.")
    ap.add_argument("orcid")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    try:
        orcid = normalise_orcid(args.orcid)
        if not valid_checksum(orcid):
            raise Problem("{} fails its check digit".format(orcid))
        rows = survey(orcid, log=lambda m: print(m, file=sys.stderr))
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    report(rows, log=print)

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"orcid": orcid, "works": rows}, fh, indent=1,
                      ensure_ascii=False)
        print("\n  wrote {}".format(args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
