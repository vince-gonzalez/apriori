#!/usr/bin/env python3
"""
============================================================
authorecon.self_citation — of the citations this work
                           received, how many are its own?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

A citation count is the number everyone reads and nobody
qualifies. Two authors with twenty citations each are not
comparable if one has twenty from strangers and the other has
twenty from themselves.

The distinction is public, computable, and almost never shown.
Profiles report a total; the composition of that total is left
to whoever cares to check by hand, which means nobody.

  authorecon-self-citation 0000-0002-1825-0097

WHAT IT SEPARATES

  external   cited by a work this author did not write
  self       cited by another of their own works

This is not an accusation. Citing your own prior work is
normal and often necessary - a series builds on itself. The
point is that the two numbers answer different questions, and
only one of them is evidence that somebody else read it.

WHAT IT WILL NOT DO

Judge. It reports the split and the works involved. A rate is
high or low relative to a field, a career stage and a
publication pattern, none of which this tool knows.

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

WORKS = "https://api.openalex.org/works"
OPENALEX_WORK = "https://api.openalex.org/works/doi:{}"


def bare(orcid_url):
    return (orcid_url or "").rstrip("/").rsplit("/", 1)[-1] or None


def work_id(doi):
    try:
        w = fetch(OPENALEX_WORK.format(doi))
    except Problem:
        return None
    return (w.get("id") or "").rsplit("/", 1)[-1] or None


def citing_works(oa_id, mailto=None, cap=500):
    """Everything OpenAlex says cites this work."""
    out, cursor = [], "*"
    while cursor and len(out) < cap:
        params = {"filter": "cites:" + oa_id, "per-page": "200",
                  "cursor": cursor}
        if mailto:
            params["mailto"] = mailto
        try:
            doc = fetch(WORKS + "?" + urllib.parse.urlencode(params))
        except Problem:
            break
        results = doc.get("results") or []
        if not results:
            break
        out.extend(results)
        cursor = (doc.get("meta") or {}).get("next_cursor")
        time.sleep(0.1)
    return out


def analyse(orcid, mailto=None, log=print):
    works = [w for w in from_orcid(orcid) if w["doi"]]
    log("  {} works with a DOI".format(len(works)))

    # Identifying a self-citation by the ORCID on the citing work fails
    # exactly where it matters. An index that dropped the author's ORCID -
    # which index-lag measures happening to 8 of 41 works on this very record
    # - makes the author's own paper look like a stranger's, and turns a self
    # citation into evidence somebody else read it. Two of them did here.
    #
    # So membership is decided by the work, not by whether an index
    # remembered who wrote it. A citing DOI that is on this ORCID record is a
    # self citation regardless of what the index attached.
    own = {zenodo_concept(w["doi"]) for w in works}
    own |= {w["doi"] for w in works}

    rows, external, selfcit = [], 0, 0
    for w in works:
        oa = work_id(w["doi"])
        if not oa:
            continue
        citers = citing_works(oa, mailto=mailto)
        if not citers:
            time.sleep(0.08)
            continue
        mine, theirs = [], []
        for c in citers:
            orcids = {bare((a.get("author") or {}).get("orcid"))
                      for a in (c.get("authorships") or [])}
            cdoi = (c.get("doi") or "").lower()
            if cdoi.startswith("https://doi.org/"):
                cdoi = cdoi[len("https://doi.org/"):]
            is_self = (orcid in orcids
                       or cdoi in own
                       or (cdoi and zenodo_concept(cdoi) in own))
            (mine if is_self else theirs).append(c)
        external += len(theirs)
        selfcit += len(mine)
        rows.append({
            "doi": w["doi"],
            "title": (w["title"] or "")[:64],
            "cited_by": len(citers),
            "self": len(mine),
            "external": len(theirs),
            "external_titles": [(c.get("title") or "")[:60] for c in theirs[:5]],
        })
        log("    {:<30} {} cited  ({} external, {} self)".format(
            w["doi"], len(citers), len(theirs), len(mine)))
        time.sleep(0.08)
    return rows, external, selfcit


def report(rows, external, selfcit, log=print):
    total = external + selfcit
    log("")
    log("  {} citation(s) across {} cited work(s)".format(total, len(rows)))
    if not total:
        log("  Nothing cites this record yet, so there is no split to report.")
        return
    log("    external  {:>4}   ({:.0f}%)".format(
        external, 100.0 * external / total))
    log("    self      {:>4}   ({:.0f}%)".format(
        selfcit, 100.0 * selfcit / total))
    log("")
    log("  External citations are the ones that evidence somebody else read")
    log("  it. Self-citation is normal and is counted separately, not judged.")

    ext = [r for r in rows if r["external"]]
    if ext:
        log("")
        log("  CITED BY OTHERS")
        for r in ext:
            log("    {}  ({})".format(r["title"], r["external"]))
            for t in r["external_titles"]:
                log("        {}".format(t))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-self-citation",
        description="Split a citation count into external and self.")
    ap.add_argument("orcid")
    ap.add_argument("--mailto")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    try:
        orcid = normalise_orcid(args.orcid)
        if not valid_checksum(orcid):
            raise Problem("{} fails its check digit".format(orcid))
        rows, external, selfcit = analyse(
            orcid, mailto=args.mailto, log=lambda m: print(m, file=sys.stderr))
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    report(rows, external, selfcit, log=print)

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"orcid": orcid, "external": external, "self": selfcit,
                       "works": rows}, fh, indent=1, ensure_ascii=False)
        print("\n  wrote {}".format(args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
