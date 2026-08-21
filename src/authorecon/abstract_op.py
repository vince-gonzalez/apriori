#!/usr/bin/env python3
"""
============================================================
authorecon.abstract_op — does every copy of the abstract say
                         the same thing?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

The abstract is the only part of a work most people read, and
it exists in several places at once: the repository record, the
index, and the document itself. Those are separate copies made
at separate times, and nothing keeps them in step.

A record edited after deposit, an index that ingested an
earlier version, a claim softened in the paper and not in the
metadata - all of it is invisible from any single copy, and all
of it is exactly what somebody assessing an unfamiliar body of
work would want to know.

  authorecon-abstract-op 10.5281/zenodo.21769846
  authorecon-abstract-op 0000-0002-1825-0097 --all

WHERE IT LOOKS

  zenodo    the deposit's own description
  openalex  reconstructed from the inverted index it stores
  pdf       the abstract section of the deposited document,
            only with the optional extra installed

ORCID is not a source: its work summary carries no abstract.
Every source found is compared against every other, not just
the first two.

THE BOUNDARY, KEPT SHARP

This compares abstracts to abstracts. It does not read the
paper and judge whether the abstract is supported by it - that
is a different tool, it needs judgement rather than comparison,
and building a weak version of it under this name would make
both useless.

WHAT A DIFFERENCE MEANS

Reformatting is not rewriting. Line wrapping, hyphenation,
ligatures and entity encoding all differ harmlessly between
copies, so text is normalised before comparison and the report
names WHERE the copies diverge rather than only that they do.
A reader can then tell a PDF artifact from a changed claim,
which a similarity score alone never permits.

No dependencies for the repository and index sources. The PDF
source needs `pip install "authorecon[pdf]"`.
============================================================
"""

from __future__ import annotations

import argparse
import difflib
import html
import re
import sys
import unicodedata

from .discover import Problem, fetch, from_orcid, normalise_orcid, valid_checksum
from .qikstgen import ZENODO_RECORD

OPENALEX_WORK = "https://api.openalex.org/works/doi:{}"

#: Below this, two copies are not the same text by any reasonable reading.
DIVERGENT = 0.98


def normalise(text):
    """
    Strip what differs harmlessly between copies, keep what carries meaning.

    HTML entities and tags, because a repository stores rich text and an index
    stores plain. Ligatures and smart punctuation, because a PDF extractor
    produces them and a form field does not. Whitespace, because line wrapping
    is not a difference in what was said.
    """
    if not text:
        return ""
    t = html.unescape(str(text))
    t = re.sub(r"<[^>]+>", " ", t)
    t = unicodedata.normalize("NFKD", t)
    t = (t.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-")
          .replace(" ", " "))
    t = re.sub(r"-\s*\n\s*", "", t)          # hyphenation across a line break
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def from_zenodo(doi):
    m = re.search(r"zenodo\.(\d+)$", doi or "", re.I)
    if not m:
        return None
    try:
        rec = fetch(ZENODO_RECORD.format(m.group(1)))
    except Problem:
        return None
    return (rec.get("metadata") or {}).get("description") or None


def from_openalex(doi):
    """Reconstructed from the inverted index OpenAlex stores instead of text."""
    try:
        w = fetch(OPENALEX_WORK.format(doi))
    except Problem:
        return None
    inv = w.get("abstract_inverted_index")
    if not inv:
        return None
    positions = {}
    for term, spots in inv.items():
        for i in spots:
            positions[i] = term
    return " ".join(positions[i] for i in sorted(positions))


def from_pdf(path):
    """
    The abstract section of a local PDF. Optional, because no standard library
    module reads PDF text and every other source here needs nothing installed.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise Problem(
            "Reading a PDF needs the optional extra:\n"
            '  pip install "authorecon[pdf]"')
    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages[:4])
    m = re.search(r"\babstract\b[:.\s]*(.+?)(?:\n\s*\n|\b(?:keywords|"
                  r"1\s+introduction|introduction)\b)", text,
                  re.I | re.S)
    return m.group(1) if m else None


def gather(doi, pdf=None, log=print):
    sources = {}
    z = from_zenodo(doi)
    if z:
        sources["zenodo"] = z
    a = from_openalex(doi)
    if a:
        sources["openalex"] = a
    if pdf:
        p = from_pdf(pdf)
        if p:
            sources["pdf"] = p
    return sources


def _skeleton(text):
    """
    The text with every space removed, for judging similarity only.

    Collapsing runs of whitespace is not enough: one copy writes "m <= 1" and
    another "m<=1", and a thousand-character abstract full of notation scores
    95% on nothing but that. Judging on the skeleton makes a spacing-only
    difference score 100, which is what it is. Differences are still SHOWN
    with their spaces, because a human has to read them.
    """
    return re.sub(r"\s+", "", text)


def compare(sources):
    """Every source against every other, not just the first two."""
    names = sorted(sources)
    pairs = []
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            a, b = normalise(sources[left]), normalise(sources[right])
            # autojunk=False is load-bearing. SequenceMatcher treats any
            # element appearing in more than 1% of a sequence of 200 or more
            # as junk and refuses to match on it - a heuristic meant for
            # lines of code, applied here to CHARACTERS, where it discards
            # every common letter in the language. It scored one pair of
            # abstracts at 0.0482 that are 0.2894 alike, and flagged another
            # at 0.9778 that is 0.9809 - across the threshold, so the tool
            # reported a divergence that does not exist.
            ratio = difflib.SequenceMatcher(
                None, _skeleton(a), _skeleton(b), autojunk=False).ratio()
            pairs.append({"left": left, "right": right, "ratio": ratio,
                          "len_left": len(a), "len_right": len(b),
                          "a": a, "b": b})
    return pairs


def show_divergence(pair, log=print, limit=4):
    """Name where they differ, so a reader can judge what kind of difference."""
    a, b = pair["a"], pair["b"]
    matcher = difflib.SequenceMatcher(None, a, b)
    shown = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal" or shown >= limit:
            continue
        left = a[i1:i2].strip()
        right = b[j1:j2].strip()
        if not left and not right:
            continue
        shown += 1
        log("      at character {}:".format(i1))
        if left:
            log("        {:<9} {}".format(pair["left"], left[:96]))
        else:
            log("        {:<9} (nothing)".format(pair["left"]))
        if right:
            log("        {:<9} {}".format(pair["right"], right[:96]))
        else:
            log("        {:<9} (nothing)".format(pair["right"]))


def check(doi, pdf=None, log=print, quiet=False):
    sources = gather(doi, pdf=pdf, log=log)
    if not sources:
        log("  {}  no abstract in any source".format(doi))
        return None
    if len(sources) == 1:
        only = list(sources)[0]
        if not quiet:
            log("  {}  only one copy exists ({}), nothing to compare"
                .format(doi, only))
        return {"doi": doi, "sources": list(sources), "pairs": []}

    pairs = compare(sources)
    worst = min(p["ratio"] for p in pairs)
    if quiet and worst >= DIVERGENT:
        return {"doi": doi, "sources": list(sources), "pairs": pairs}

    log("")
    log("  {}".format(doi))
    log("    copies: {}".format(", ".join(
        "{} ({} chars)".format(n, len(normalise(sources[n])))
        for n in sorted(sources))))
    for p in pairs:
        verdict = "identical" if p["ratio"] == 1.0 else (
            "matches" if p["ratio"] >= DIVERGENT else "DIVERGES")
        log("    {:<9} vs {:<9} {:>7.2%}  {}".format(
            p["left"], p["right"], p["ratio"], verdict))
        if p["ratio"] < DIVERGENT:
            show_divergence(p, log=log)
    return {"doi": doi, "sources": list(sources), "pairs": pairs}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-abstract-op",
        description="Compare every copy of a work's abstract against every "
                    "other.")
    ap.add_argument("target", help="a DOI, or an ORCID with --all")
    ap.add_argument("--all", action="store_true",
                    help="check every work on an ORCID record")
    ap.add_argument("--pdf", help="a local PDF to include as a source")
    ap.add_argument("--quiet", action="store_true",
                    help="report only the works that diverge")
    args = ap.parse_args(argv)

    try:
        if args.all:
            orcid = normalise_orcid(args.target)
            if not valid_checksum(orcid):
                raise Problem("{} fails its check digit".format(orcid))
            works = [w for w in from_orcid(orcid) if w["doi"]]
            print("  checking {} works\n".format(len(works)), file=sys.stderr)
            diverged = 0
            for w in works:
                result = check(w["doi"], log=print, quiet=args.quiet)
                if result and any(p["ratio"] < DIVERGENT
                                  for p in result["pairs"]):
                    diverged += 1
            print("")
            print("  {} of {} works have copies that diverge".format(
                diverged, len(works)))
            return 1 if diverged else 0

        result = check(args.target, pdf=args.pdf, log=print)
        if not result:
            return 2
        return 1 if any(p["ratio"] < DIVERGENT for p in result["pairs"]) else 0
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
