#!/usr/bin/env python3
"""
============================================================
authorecon.pdf_conform — does the document agree with the
                         record describing it?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

The record and the document are entered separately. One is a
form, the other is a file, and nothing checks that they say the
same thing. A title edited in the metadata and not in the PDF,
an author added to one and not the other, a DOI printed in a
paper that belongs to a different deposit - all of it survives
publication because nobody opens both at once.

Everything else in this package compares one system's view of a
work to another's. This compares a record to the thing it is a
record OF.

  authorecon-pdf-conform 10.5281/zenodo.21769846
  authorecon-pdf-conform 0000-0002-1825-0097 --all

WHAT IT COMPARES

  title    the metadata title against the text of the document
  doi      whether the record's DOI appears in its own document
  authors  each creator's family name, against the document
  version  a version in the metadata, against the document

WHAT "NOT FOUND" MEANS

Not a mismatch. PDF text extraction fails on scanned pages,
unusual encodings and heavy typesetting, and a title split
across lines by a layout engine is not a title that disagrees.
Anything it could not locate is reported as not located, never
as wrong - the opposite would flag a correct record as broken
and the tool would be off within a week.

Needs the optional extra:  pip install "authorecon[pdf]"
============================================================
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
import urllib.request

from .discover import (Problem, fetch, from_orcid, normalise_orcid,
                       valid_checksum)
from .qikstgen import ZENODO_RECORD
from .abstract_op import normalise

UA = "authorecon/0.12 (+https://f-keys.com)"

MATCH, DIFFERS, NOT_FOUND = "match", "DIFFERS", "not found"
#: Reported, never counted as a problem. A Zenodo DOI is minted after the
#: file is uploaded, so a deposit CANNOT normally print its own DOI - the
#: identifier did not exist when the document was written. Flagging that
#: marked 41 of 53 records and made the tool useless. Only fields whose
#: absence is actually odd are counted.
INFORMATIONAL = ("doi", "version")


def record_for(doi):
    m = re.search(r"zenodo\.(\d+)$", doi or "", re.I)
    if not m:
        raise Problem("Expected a Zenodo DOI, got {!r}".format(doi))
    return fetch(ZENODO_RECORD.format(m.group(1)))


def first_pdf(rec):
    for f in rec.get("files") or []:
        name = f.get("key") or f.get("filename") or ""
        if name.lower().endswith(".pdf"):
            return name, (f.get("links") or {}).get("self")
    return None, None


def pdf_text(url, pages=3):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise Problem(
            'Reading a PDF needs the optional extra:\n'
            '  pip install "authorecon[pdf]"')
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:pages])


def squash(text):
    """Compare on letters and digits only: layout inserts spaces and breaks."""
    return re.sub(r"[^a-z0-9]", "", normalise(text).lower())


def check(doi, log=print, quiet=False):
    rec = record_for(doi)
    md = rec.get("metadata") or {}
    name, url = first_pdf(rec)
    if not url:
        if not quiet:
            log("  {}  no PDF on the record".format(doi))
        return None

    text = pdf_text(url)
    if not (text or "").strip():
        log("  {}  {} yielded no extractable text (scanned, or an "
            "encoding this cannot read)".format(doi, name))
        return None

    flat = squash(text)
    findings = []

    title = (md.get("title") or "").strip()
    if title:
        findings.append(("title", MATCH if squash(title) in flat else NOT_FOUND,
                         title[:64]))

    own = (rec.get("doi") or md.get("doi") or "").lower()
    if own:
        findings.append(("doi", MATCH if squash(own) in flat else NOT_FOUND,
                         own))

    for c in (md.get("creators") or []):
        person = (c.get("name") or "").strip()
        family = person.split(",")[0].strip()
        if not family:
            continue
        findings.append(("author", MATCH if squash(family) in flat
                         else NOT_FOUND, person))

    version = (md.get("version") or "").strip()
    if version:
        findings.append(("version", MATCH if squash(version) in flat
                         else NOT_FOUND, version))

    # Another deposit's DOI printed inside this one is the finding worth
    # having: it means a file was reused across records.
    foreign = set()
    for found in re.findall(r"10\.5281/zenodo\.\d+", text, re.I):
        if squash(found) != squash(own):
            foreign.add(found.lower())

    notable = [f for f in findings if f[0] not in INFORMATIONAL]
    if quiet and all(f[1] == MATCH for f in notable) and not foreign:
        return {"doi": doi, "findings": findings, "foreign": foreign}

    log("")
    # Zenodo resolves an older version DOI to the latest record, so the
    # record fetched is not always the one asked for. Naming both stops a
    # reader comparing a result against a record it did not come from.
    fetched = (rec.get("doi") or "").lower()
    if fetched and fetched != doi.lower():
        log("  {}  ->  resolved to {}".format(doi, fetched))
        log("     [{}]".format(name))
    else:
        log("  {}   [{}]".format(doi, name))
    for field, state, value in findings:
        log("    {:<8} {:<10} {}".format(field, state, value[:60]))
    if foreign:
        log("    OTHER DOIs printed in this document:")
        for f in sorted(foreign):
            log("      {}".format(f))
        log("    A file carrying another deposit's identifier was probably")
        log("    reused. Worth confirming which record it belongs to.")
    return {"doi": doi, "findings": findings, "foreign": foreign}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-pdf-conform",
        description="Check that a deposited document agrees with its record.")
    ap.add_argument("target")
    ap.add_argument("--all", action="store_true",
                    help="check every deposit on an ORCID record")
    ap.add_argument("--quiet", action="store_true",
                    help="report only records with something to say")
    args = ap.parse_args(argv)

    try:
        if args.all:
            orcid = normalise_orcid(args.target)
            if not valid_checksum(orcid):
                raise Problem("{} fails its check digit".format(orcid))
            works = [w for w in from_orcid(orcid) if w["doi"]]
            print("  checking {} deposits".format(len(works)), file=sys.stderr)
            flagged = 0
            for w in works:
                try:
                    r = check(w["doi"], log=print, quiet=args.quiet)
                except Problem as err:
                    print("  {}  {}".format(w["doi"], err), file=sys.stderr)
                    continue
                if r and (any(f[1] != MATCH for f in r["findings"]
                              if f[0] not in INFORMATIONAL)
                          or r["foreign"]):
                    flagged += 1
                time.sleep(0.15)
            print("")
            print("  {} of {} deposits have something to look at".format(
                flagged, len(works)))
            return 1 if flagged else 0

        r = check(args.target, log=print)
        if not r:
            return 2
        return 1 if (any(f[1] != MATCH for f in r["findings"]
                        if f[0] not in INFORMATIONAL)
                     or r["foreign"]) else 0
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
