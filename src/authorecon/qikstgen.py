#!/usr/bin/env python3
"""
============================================================
authorecon.qikstgen — QuickStatements for the works that
                      have no Wikidata item yet
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

authorecon can already tell you a work has no Wikidata item.
Knowing is not the same as fixing, and the fix - twenty items
typed by hand into a form - is exactly the job nobody does.

So this writes the QuickStatements batch instead. Metadata
comes from Zenodo, which is the source of record for these
deposits, not from anything a second system says about them.
That distinction matters: this tool was written after two
findings in a row turned out to be one system's incomplete
view of another's correct data.

  authorecon-qikstgen 0009-0005-3640-014X > batch.qs

Then read the batch. Then paste it into QuickStatements. It
does not submit anything - a tool that writes to a public
knowledge graph without a person reading the diff first is a
tool for making messes at scale.

WHAT IT REFUSES TO DO

  - emit an item for a DOI that already has one, checked
    against both the version and the concept DOI
  - guess an author. Without a Wikidata item for the ORCID it
    emits the author as a name string and says so, because a
    wrong P50 is worse than an honest P2093
  - invent a type. An upload type it does not recognise is
    reported and skipped rather than defaulted to "article"

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.parse

from .discover import (Problem, WIKIDATA, fetch, from_orcid, normalise_orcid,
                       valid_checksum, zenodo_concept)

ZENODO_RECORD = "https://zenodo.org/api/records/{}"

#: Zenodo upload type -> Wikidata instance-of. Anything absent is skipped and
#: named, rather than filed under a guess.
TYPES = {
    "publication/preprint": ("Q580922", "preprint"),
    "publication/article": ("Q13442814", "scholarly article"),
    "publication/report": ("Q10870555", "report"),
    "publication/workingpaper": ("Q1266946", "working paper"),
    "publication/book": ("Q571", "book"),
    "publication/section": ("Q1980247", "chapter"),
    "publication/conferencepaper": ("Q23927052", "conference paper"),
    "publication/technicalnote": ("Q10870555", "report"),
    "publication/other": ("Q234460", "text"),
    "software": ("Q7397", "software"),
    "dataset": ("Q1172284", "data set"),
    "poster": ("Q429785", "poster"),
    "presentation": ("Q604733", "presentation"),
}


def wikidata_item_for(doi):
    """The item whose P356 is this DOI, or None."""
    params = {"action": "query", "list": "search",
              "srsearch": "haswbstatement:P356=" + doi.upper(),
              "srlimit": "1", "format": "json"}
    try:
        doc = fetch(WIKIDATA + "?" + urllib.parse.urlencode(params))
    except Problem:
        return None
    hits = (doc.get("query") or {}).get("search") or []
    return hits[0]["title"] if hits else None


def author_item(orcid):
    """The Wikidata item whose P496 is this ORCID, or None."""
    params = {"action": "query", "list": "search",
              "srsearch": "haswbstatement:P496=" + orcid,
              "srlimit": "1", "format": "json"}
    try:
        doc = fetch(WIKIDATA + "?" + urllib.parse.urlencode(params))
    except Problem:
        return None
    hits = (doc.get("query") or {}).get("search") or []
    return hits[0]["title"] if hits else None


def zenodo_record(doi):
    m = re.search(r"zenodo\.(\d+)$", doi or "", re.I)
    if not m:
        return None
    try:
        return fetch(ZENODO_RECORD.format(m.group(1)))
    except Problem:
        return None


def qs_string(text):
    """A QuickStatements string literal. Quotes and newlines would break it."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return '"' + clean.replace('\\', '').replace('"', "'") + '"'


def qs_date(value):
    """+YYYY-MM-DDT00:00:00Z/11, or None if the date is not a full one."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(value or ""))
    if not m:
        return None
    return "+{}-{}-{}T00:00:00Z/11".format(*m.groups())


def statements_for(rec, author_qid, author_name):
    """The QuickStatements lines that create one item, or a reason not to."""
    md = rec.get("metadata") or {}
    doi = (rec.get("doi") or md.get("doi") or "").lower()
    title = (md.get("title") or "").strip()
    if not doi or not title:
        return None, "no DOI or no title in the Zenodo record"

    # Zenodo's current API nests this as resource_type {type, subtype}.
    # upload_type/publication_type are the older flat shape and still appear
    # on some records, so both are read rather than one being assumed.
    rt = md.get("resource_type") or {}
    upload = (rt.get("type") or md.get("upload_type") or "").lower()
    sub = (rt.get("subtype") or md.get("publication_type") or "").lower()
    key = upload + ("/" + sub if sub else "")
    kind = TYPES.get(key) or TYPES.get(upload)
    if not kind:
        return None, "unmapped Zenodo type {!r}".format(key or upload)

    lines = ["CREATE"]
    # Labels are capped at 250 characters on Wikidata; titles do exceed that.
    label = title if len(title) <= 245 else title[:242].rstrip() + "..."
    lines.append("\t".join(["LAST", "Len", qs_string(label)]))
    lines.append("\t".join(["LAST", "P31", kind[0]]))
    lines.append("\t".join(["LAST", "P1476", "en:" + qs_string(title)]))
    lines.append("\t".join(["LAST", "P356", qs_string(doi.upper())]))

    date = qs_date(md.get("publication_date"))
    if date:
        lines.append("\t".join(["LAST", "P577", date]))

    if author_qid:
        lines.append("\t".join(["LAST", "P50", author_qid]))
    else:
        # A wrong P50 attributes somebody's work to somebody else. A name
        # string is weaker and true.
        lines.append("\t".join(["LAST", "P2093", qs_string(author_name)]))

    lines.append("\t".join(["LAST", "P953", qs_string("https://doi.org/" + doi)]))
    return lines, kind[1]


def generate(orcid, log=print, limit=None):
    orcid = normalise_orcid(orcid)
    if not valid_checksum(orcid):
        raise Problem("{} is not a valid ORCID.".format(orcid))

    works = from_orcid(orcid)
    log("  {} works on the ORCID record".format(len(works)))

    qid = author_item(orcid)
    name = None
    log("  author   {}".format(
        qid + " (P50)" if qid else "no Wikidata item for this ORCID; "
                                   "the batch will use a name string"))

    batch, skipped, existing = [], [], 0
    for w in works:
        if limit and len(batch) >= limit:
            break
        doi = w["doi"]
        if not doi:
            skipped.append((w["title"], "no DOI on the ORCID record"))
            continue
        # both identifiers, because an item may have been made against either
        found = None
        for candidate in {doi, zenodo_concept(doi)}:
            found = wikidata_item_for(candidate)
            if found:
                break
            time.sleep(0.15)
        if found:
            existing += 1
            continue

        rec = zenodo_record(doi)
        if not rec:
            skipped.append((w["title"], "not a resolvable Zenodo record"))
            continue
        name = name or (((rec.get("metadata") or {}).get("creators") or [{}])[0]
                        .get("name") or "")
        lines, why = statements_for(rec, qid, name)
        if not lines:
            skipped.append((w["title"], why))
            continue
        batch.append((w["title"], why, lines))
        time.sleep(0.1)

    log("  {} already have an item".format(existing))
    log("  {} to create".format(len(batch)))
    if skipped:
        log("  {} skipped:".format(len(skipped)))
        for title, why in skipped:
            log("     {}  <- {}".format((title or "?")[:46], why))
    return batch, skipped, existing


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-qikstgen",
        description="QuickStatements for the works on an ORCID record that "
                    "have no Wikidata item yet.")
    ap.add_argument("orcid")
    ap.add_argument("--out", help="write the batch here instead of stdout")
    ap.add_argument("--limit", type=int, help="stop after this many items")
    args = ap.parse_args(argv)

    try:
        batch, skipped, existing = generate(
            args.orcid, log=lambda m: print(m, file=sys.stderr),
            limit=args.limit)
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    if not batch:
        print("  nothing to create", file=sys.stderr)
        return 0

    out = []
    for title, kind, lines in batch:
        out.append("# {}  [{}]".format(re.sub(r"\s+", " ", title)[:70], kind))
        out.extend(lines)
        out.append("")
    text = "\n".join(out) + "\n"

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("  wrote {} ({} items)".format(args.out, len(batch)), file=sys.stderr)
    else:
        sys.stdout.write(text)
    print("  Paste into https://quickstatements.toolforge.org/#/batch after "
          "reading it.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
