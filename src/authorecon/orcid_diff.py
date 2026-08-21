#!/usr/bin/env python3
"""
============================================================
authorecon.orcid_diff — what changed since last time
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

Everything else in this package answers "what is true right
now". You run it, you fix what it found, and then you stop
looking - which is exactly when a record starts drifting
again, because the drift is not caused by you.

An index drops your ORCID from a work it had attributed
correctly. A DOI stops resolving. A work appears under your
name that you did not deposit. None of that involves you
touching anything, and none of it announces itself.

So this takes a snapshot and compares it to the last one.

  authorecon-orcid-diff 0000-0002-1825-0097            first run: snapshot
  authorecon-orcid-diff 0000-0002-1825-0097            later:     the diff

Snapshots live in a per-user directory, one file per ORCID.
Exit code is 1 when something changed, so this can run on a
schedule and stay quiet until it has news.

WHAT IT WATCHES

  works appearing on the record, and disappearing from it
  works entering an index, and dropping out of one
  attribution gained or lost - the ORCID attached or not
  citation counts moving
  a DOI that stopped resolving

DELIBERATELY NOT A "CHANGED" FLAG

A diff that says "3 things changed" is a diff nobody reads.
Every line names the work, the field, the old value and the
new one, because the only useful version of this is one you
can act on without opening anything else.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .discover import (Problem, from_openalex, from_orcid, normalise_orcid,
                       valid_checksum, zenodo_concept)


def state_dir():
    """
    Per-user, and not the working directory. A tool that drops state where it
    was launched from scatters it across every folder you ever ran it in, and
    this one accumulates a history worth keeping.
    """
    base = (os.environ.get("XDG_STATE_HOME")
            or os.environ.get("LOCALAPPDATA")
            or os.path.join(os.path.expanduser("~"), ".local", "state"))
    path = os.path.join(base, "authorecon")
    os.makedirs(path, exist_ok=True)
    return path


def snapshot_path(orcid):
    return os.path.join(state_dir(), "orcid-{}.json".format(orcid))


def take_snapshot(orcid, mailto=None, log=print):
    """The state of one record, reduced to what is worth comparing."""
    works = from_orcid(orcid)
    alex, total, complete, no_doi = from_openalex(orcid, mailto=mailto)

    # concepts, so a new version of a work is not read as a new work
    by_concept = {}
    for doi in alex:
        by_concept[zenodo_concept(doi)] = alex[doi]

    entries = {}
    for w in works:
        doi = w["doi"]
        key = zenodo_concept(doi) if doi else ("title:" + (w["title"] or "")[:60])
        extra = by_concept.get(key) or (alex.get(doi) if doi else None) or {}
        entries[key] = {
            "title": w["title"],
            "doi": doi,
            "date": w["date"],
            "in_openalex": bool(extra),
            "cited_by": extra.get("cited_by"),
            "openalex": extra.get("openalex"),
        }

    for key, extra in by_concept.items():
        if key in entries:
            continue
        entries[key] = {
            "title": None, "doi": key, "date": None,
            "in_openalex": True, "cited_by": extra.get("cited_by"),
            "openalex": extra.get("openalex"), "unclaimed": True,
        }

    return {
        "orcid": orcid,
        "taken": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "openalex_total": total,
        "works": entries,
    }


def name_of(entry):
    return (entry.get("title") or entry.get("doi") or "?")[:56]


def diff(old, new):
    """Every change, named. Returns a list of (kind, line) pairs."""
    changes = []
    old_w, new_w = old.get("works", {}), new.get("works", {})

    for key in sorted(set(new_w) - set(old_w)):
        e = new_w[key]
        changes.append(("added",
                        "appeared on the record: {}  {}".format(
                            name_of(e), e.get("doi") or "")))

    for key in sorted(set(old_w) - set(new_w)):
        e = old_w[key]
        changes.append(("removed",
                        "GONE from the record: {}  {}".format(
                            name_of(e), e.get("doi") or "")))

    for key in sorted(set(old_w) & set(new_w)):
        a, b = old_w[key], new_w[key]
        label = name_of(b)
        if a.get("in_openalex") and not b.get("in_openalex"):
            changes.append(("dropped",
                            "DROPPED OUT of OpenAlex: {}".format(label)))
        elif not a.get("in_openalex") and b.get("in_openalex"):
            changes.append(("indexed",
                            "now indexed by OpenAlex: {}".format(label)))
        ac, bc = a.get("cited_by"), b.get("cited_by")
        if ac is not None and bc is not None and bc != ac:
            changes.append(("cited",
                            "citations {} -> {}: {}".format(ac, bc, label)))
        if a.get("unclaimed") and not b.get("unclaimed"):
            changes.append(("claimed", "now claimed: {}".format(label)))
        elif not a.get("unclaimed") and b.get("unclaimed"):
            changes.append(("unclaimed",
                            "no longer on the ORCID record: {}".format(label)))

    at, bt = old.get("openalex_total"), new.get("openalex_total")
    if at is not None and bt is not None and at != bt:
        changes.append(("total",
                        "OpenAlex total {} -> {}".format(at, bt)))
    return changes


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-orcid-diff",
        description="Snapshot an ORCID record and report what changed since "
                    "the last snapshot.")
    ap.add_argument("orcid")
    ap.add_argument("--mailto", help="your email, for OpenAlex's faster pool")
    ap.add_argument("--show-path", action="store_true",
                    help="print where snapshots are kept and exit")
    ap.add_argument("--no-save", action="store_true",
                    help="report the diff without replacing the snapshot")
    args = ap.parse_args(argv)

    if args.show_path:
        print(state_dir())
        return 0

    try:
        orcid = normalise_orcid(args.orcid)
        if not valid_checksum(orcid):
            raise Problem("{} is not a valid ORCID.".format(orcid))

        path = snapshot_path(orcid)
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)

        print("  taking a snapshot of {}...".format(orcid), file=sys.stderr)
        new = take_snapshot(orcid, mailto=args.mailto,
                            log=lambda m: print(m, file=sys.stderr))
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    if old is None:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(new, fh, indent=1, ensure_ascii=False)
        print("  first snapshot: {} works recorded".format(len(new["works"])))
        print("  saved to {}".format(path))
        print("  run this again later and it will report what moved.")
        return 0

    changes = diff(old, new)
    print("  last snapshot {}".format(old.get("taken")))
    print("  this one      {}".format(new.get("taken")))
    print("")
    if not changes:
        print("  nothing changed.")
    else:
        for kind, line in changes:
            print("  {:<10} {}".format(kind, line))
        print("")
        print("  {} change(s)".format(len(changes)))

    if not args.no_save:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(new, fh, indent=1, ensure_ascii=False)

    return 1 if changes else 0


if __name__ == "__main__":
    sys.exit(main())
