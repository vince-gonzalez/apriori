#!/usr/bin/env python3
"""
============================================================
authorecon.deposit_lint — check a deposit before it becomes
                          a correction
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

Every defect found while building the rest of this package was
a metadata defect, and every one of them was cheap to prevent
and expensive to fix once a DOI had been minted:

  a type nothing downstream could map
  a title too long for a Wikidata label
  a date too vague to become a publication date
  a creator with no ORCID, so attribution rests on a name
  no link from a paper to the code it describes

Zenodo will happily publish all of that. Once published the
DOI is permanent, the record is citable, and correcting it
means a new version and every index re-ingesting it.

So this runs first.

  authorecon-deposit-lint 10.5281/zenodo.19348704
  authorecon-deposit-lint 0009-0005-3640-014X --all

FAIL means something downstream will silently do the wrong
thing with this record. WARN means it will work and be worse.
Nothing here is a style opinion.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import re
import sys
import time

from .discover import Problem, from_orcid, fetch, normalise_orcid, valid_checksum
from .qikstgen import TYPES, ZENODO_RECORD

#: Wikidata refuses a label longer than this, and qikstgen has to truncate.
LABEL_MAX = 245

FAIL, WARN, OK = "FAIL", "WARN", "ok"


class Finding(object):
    __slots__ = ("level", "check", "detail")

    def __init__(self, level, check, detail):
        self.level, self.check, self.detail = level, check, detail


def record_for(doi_or_id):
    m = re.search(r"(\d+)\s*$", str(doi_or_id))
    if not m:
        raise Problem("Expected a Zenodo DOI or record id, got {!r}".format(doi_or_id))
    return fetch(ZENODO_RECORD.format(m.group(1)))


def lint(rec):
    """Every check, in the order a reader would want to hear them."""
    md = rec.get("metadata") or {}
    out = []

    def add(level, check, detail):
        out.append(Finding(level, check, detail))

    # ── identity ────────────────────────────────────────────
    creators = md.get("creators") or []
    if not creators:
        add(FAIL, "creators", "the record has no creators")
    else:
        without = [c.get("name") or "?" for c in creators if not c.get("orcid")]
        if without:
            add(FAIL, "creator ORCID",
                "{} of {} creators have no ORCID: {}. Attribution then rests "
                "on a name string, and indexes drop it."
                .format(len(without), len(creators), ", ".join(without[:3])))
        else:
            add(OK, "creator ORCID", "every creator has one")

    # ── type ────────────────────────────────────────────────
    rt = md.get("resource_type") or {}
    upload = (rt.get("type") or md.get("upload_type") or "").lower()
    sub = (rt.get("subtype") or md.get("publication_type") or "").lower()
    key = upload + ("/" + sub if sub else "")
    if not upload:
        add(FAIL, "type", "no resource type at all")
    elif not (TYPES.get(key) or TYPES.get(upload)):
        add(FAIL, "type",
            "{!r} maps to nothing downstream, so no Wikidata item can state "
            "what this is".format(key or upload))
    else:
        add(OK, "type", key or upload)

    # ── title ───────────────────────────────────────────────
    title = (md.get("title") or "").strip()
    if not title:
        add(FAIL, "title", "empty")
    elif len(title) > LABEL_MAX:
        add(WARN, "title",
            "{} characters. Wikidata caps a label at {}, so it will be "
            "truncated there while the full title survives as P1476."
            .format(len(title), LABEL_MAX))
    else:
        add(OK, "title", "{} characters".format(len(title)))

    # ── date ────────────────────────────────────────────────
    date = str(md.get("publication_date") or "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        add(FAIL, "publication date",
            "{!r} is not a full date, so it cannot become a publication date "
            "statement".format(date))
    else:
        add(OK, "publication date", date)

    # ── licence ─────────────────────────────────────────────
    lic = md.get("license")
    lic_id = lic.get("id") if isinstance(lic, dict) else lic
    if not lic_id:
        add(FAIL, "licence",
            "none. Nobody may legally reuse this, and aggregators that "
            "require a licence will skip it.")
    else:
        add(OK, "licence", str(lic_id))

    # ── the link back to the thing it describes ─────────────
    rel = md.get("related_identifiers") or []
    kinds = {(r.get("relation") or "").lower() for r in rel}
    if upload == "software" and not (kinds & {"issupplementto", "isdescribedby",
                                              "isreferencedby", "iscitedby"}):
        add(WARN, "related identifiers",
            "software with no link to the paper that describes it")
    elif upload == "publication" and not (kinds & {"issupplementedby",
                                                   "references", "cites",
                                                   "isderivedfrom"}):
        add(WARN, "related identifiers",
            "a publication with no link to its code, data or sources")
    else:
        add(OK, "related identifiers", "{} recorded".format(len(rel)))

    # ── findability ─────────────────────────────────────────
    kw = md.get("keywords") or []
    if not kw:
        add(WARN, "keywords", "none, so subject search will not find it")
    else:
        add(OK, "keywords", "{} recorded".format(len(kw)))

    desc = re.sub(r"<[^>]+>", "", md.get("description") or "").strip()
    if len(desc) < 120:
        add(WARN, "description",
            "{} characters of text. Abstracts shorter than a paragraph carry "
            "little for an index to match on.".format(len(desc)))
    else:
        add(OK, "description", "{} characters".format(len(desc)))

    if not md.get("language"):
        add(WARN, "language", "unset")
    else:
        add(OK, "language", str(md.get("language")))

    return out


def report(rec, findings, log=print):
    md = rec.get("metadata") or {}
    log("  {}".format((md.get("title") or "?")[:66]))
    log("  {}".format(rec.get("doi") or "no DOI"))
    log("")
    for f in findings:
        mark = {FAIL: "FAIL", WARN: "WARN", OK: "  ok"}[f.level]
        log("  {}  {:<22} {}".format(mark, f.check, f.detail))
    fails = sum(1 for f in findings if f.level == FAIL)
    warns = sum(1 for f in findings if f.level == WARN)
    log("")
    log("  {} fail, {} warn, {} ok".format(
        fails, warns, sum(1 for f in findings if f.level == OK)))
    return fails


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-deposit-lint",
        description="Check a Zenodo deposit for the metadata faults that "
                    "become corrections once a DOI is minted.")
    ap.add_argument("target", help="a Zenodo DOI or record id, or an ORCID with --all")
    ap.add_argument("--all", action="store_true",
                    help="lint every deposit on an ORCID record")
    args = ap.parse_args(argv)

    try:
        if args.all:
            orcid = normalise_orcid(args.target)
            if not valid_checksum(orcid):
                raise Problem("{} is not a valid ORCID.".format(orcid))
            works = [w for w in from_orcid(orcid) if w["doi"]]
            print("  linting {} deposits\n".format(len(works)), file=sys.stderr)
            worst, summary = 0, []
            for w in works:
                try:
                    rec = record_for(w["doi"])
                except Problem as err:
                    summary.append((FAIL, w["doi"], str(err)[:50]))
                    continue
                findings = lint(rec)
                fails = sum(1 for f in findings if f.level == FAIL)
                warns = sum(1 for f in findings if f.level == WARN)
                worst = max(worst, fails)
                summary.append((FAIL if fails else (WARN if warns else OK),
                                w["doi"],
                                "{} fail, {} warn  {}".format(
                                    fails, warns, (w["title"] or "")[:40])))
                time.sleep(0.1)
            for level, doi, line in summary:
                print("  {:<4} {:<32} {}".format(
                    {FAIL: "FAIL", WARN: "WARN", OK: "  ok"}[level], doi, line))
            return 1 if worst else 0

        rec = record_for(args.target)
        return 1 if report(rec, lint(rec)) else 0
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
