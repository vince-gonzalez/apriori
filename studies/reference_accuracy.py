#!/usr/bin/env python3
"""
============================================================
How often is a real reference called unfindable?
F-Keys | www.f-keys.com
------------------------------------------------------------
THE QUESTION

A reference check is useful to an editor only if a genuine
reference is almost never reported as missing. Six references
written to defeat the tool showed it works in principle. This
asks the number that decides whether it can be used: given a
reference that certainly exists, how often does the check fail
to find it, and how often does it find the wrong thing?

WHERE THE ANSWER COMES FROM

Crossref stores many references twice: as the raw citation
string a publisher deposited, and as the DOI Crossref resolved
that string to. That pairing is a labelled set of real
references, thousands of them, free, and not assembled by the
person being tested.

Any DOI is stripped from the string before it is checked, so
what is measured is the search path rather than the trivial
case of reading an identifier that was handed over.

WHAT IS BEING COUNTED

  correct     a record was found and it is the right one
  wrong       a record was found and it is a different work
  missed      no record found, for a reference that exists
  unchecked   a source could not be reached

"Missed" is the number that matters. Every one is a real
reference an editor would have been told to doubt.

HONEST LIMIT OF THE GROUND TRUTH

Crossref's own reference-to-DOI matches are made by machine
and are not perfect. A disagreement is therefore not
automatically this tool's error, and a sample of the
disagreements is printed so they can be read rather than
assumed.

  python studies/reference_accuracy.py --refs 1000
  python studies/reference_accuracy.py --refs 200 --json out.json

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.parse

sys.path.insert(0, "src")

from authorecon import reference_check as rc          # noqa: E402
from authorecon.discover import CONTACT, Problem, fetch  # noqa: E402

SAMPLE = "https://api.crossref.org/works"


def safe_print(line):
    """
    Print a line that may be in any writing system.

    Redirecting output on Windows hands Python a cp1252 stream, which cannot
    encode most of the world's scripts and raises rather than degrading. A
    study of references from every language will meet one within a thousand
    rows, and it did, twice. Reconfiguring the stream is attempted first
    because it keeps the characters; encoding by hand is the fallback that
    cannot fail.
    """
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(encoding, "replace").decode(encoding, "replace"))


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def sample_works(n, log):
    """
    Random works that carry references.

    Crossref's sample parameter returns a genuinely random draw rather than
    the head of a relevance ranking, which matters: the most cited papers in
    the index are not representative of what turns up in a bibliography.
    """
    out = []
    while len(out) < n:
        want = min(100, n - len(out))
        url = SAMPLE + "?" + urllib.parse.urlencode({
            "sample": str(want),
            "filter": "has-references:true,from-pub-date:2000-01-01",
            "select": "DOI,reference,title",
            "mailto": CONTACT})
        try:
            items = (fetch(url).get("message") or {}).get("items") or []
        except Problem as err:
            log("  sampling failed: {}".format(err))
            break
        if not items:
            break
        out.extend(items)
        log("  sampled {} works".format(len(out)))
        time.sleep(0.3)
    return out


def labelled(works, cap, log):
    """(reference string, the DOI Crossref matched it to) pairs."""
    pairs = []
    for w in works:
        for ref in (w.get("reference") or []):
            text = (ref.get("unstructured") or "").strip()
            doi = (ref.get("DOI") or "").strip().lower()
            # Both halves are needed: the text to feed in, the DOI to judge.
            if not text or not doi or len(text) < 40:
                continue
            # Strip the identifier so the search path is what gets measured.
            clean = re.sub(r"(https?://\S*)?\b10\.\d{4,9}/\S+", "", text)
            clean = re.sub(r"\s+", " ", clean).strip(" .,;")
            if len(clean) < 40:
                continue
            pairs.append({"ref": clean, "truth": doi,
                          "cited_by": w.get("DOI", "")})
            if len(pairs) >= cap:
                log("  {} labelled references".format(len(pairs)))
                return pairs
    log("  {} labelled references".format(len(pairs)))
    return pairs


def same_work(truth_doi, found_title):
    """Do these two identifiers name the same article?"""
    if not found_title:
        return False
    try:
        m = fetch("https://api.crossref.org/works/" +
                  urllib.parse.quote(truth_doi, safe="/") +
                  "?mailto=" + CONTACT)["message"]
    except Problem:
        return False
    truth_title = (m.get("title") or [""])[0]
    if not truth_title:
        return False
    return rc.verdict(rc.agreement(truth_title, found_title)) == "agrees"


def run(pairs, log):
    # Retraction status has no bearing on whether the right record was found,
    # and asking about it would double the requests. The rest of the path is
    # exactly what ships.
    rc.is_retracted = lambda doi: False

    rows = []
    for n, item in enumerate(pairs, 1):
        try:
            got = rc.check_one(item["ref"])
        except Exception as err:                     # noqa: BLE001
            got = {"state": rc.UNCHECKED, "found": None, "says": str(err)}

        found = (got.get("found") or {}).get("doi") or ""
        title = (got.get("found") or {}).get("title") or ""
        # States where the check declined to judge are their own answer.
        # Scored as failures by an earlier version of this study, they turned
        # 21 wrong matches into 87 and read as a fourfold regression that had
        # not happened. A measuring instrument that does not know every
        # outcome reports the ones it does not know as the worst one.
        if got["state"] in (rc.UNCHECKED, rc.UNTITLED, rc.OTHER_SCRIPT):
            verdict = got["state"]
        elif got["state"] == rc.UNLOCATABLE:
            verdict = "missed"
        elif found == item["truth"]:
            verdict = "correct"
        else:
            # Comparing identifiers where the question is about works. A
            # single article often carries several registered DOIs - the
            # publisher's and an archive's, or two SICI forms differing in
            # one digit - and calling those a wrong answer would have
            # reported a quarter of correct matches as errors.
            verdict = "alias" if same_work(item["truth"], title) else "wrong"

        rows.append({**item, "state": got["state"], "found": found,
                     "found_title": (got.get("found") or {}).get("title", ""),
                     "verdict": verdict})

        if n % 25 == 0 or n == len(pairs):
            tally = {}
            for r in rows:
                tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
            log("  {:>5}/{}  {}".format(n, len(pairs), tally))
        time.sleep(0.05)
    return rows


def report(rows, log=print):
    total = len(rows)
    tally = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1

    log("")
    log("  {} real references checked".format(total))
    log("")
    for key in ("correct", "alias", "wrong", "missed", "untitled",
                "other script", "unchecked"):
        n = tally.get(key, 0)
        log("    {:<11} {:>5}   {:>5.1f}%".format(
            key, n, 100.0 * n / total if total else 0))

    # A reference the check declined to judge does not belong in a rate
    # about how often it judges correctly.
    declined = sum(tally.get(k, 0)
                   for k in ("unchecked", "untitled", "other script"))
    judged = total - declined
    if judged:
        log("")
        log("  Of the {} it could reach:".format(judged))
        right = tally.get("correct", 0) + tally.get("alias", 0)
        log("    {:.1f}% found the right work".format(100.0 * right / judged))
        log("       of which {} under a different registered identifier for "
            "the same article".format(tally.get("alias", 0)))
        log("    {:.2f}% reported a real reference as unfindable".format(
            100.0 * tally.get("missed", 0) / judged))
        log("    {:.2f}% pointed at a different work".format(
            100.0 * tally.get("wrong", 0) / judged))

    log("")
    log("  A reader has to see the disagreements to know what they are.")
    for key in ("missed", "wrong"):
        examples = [r for r in rows if r["verdict"] == key]
        if not examples:
            continue
        log("")
        log("  {} - {} of them, {} shown".format(
            key.upper(), len(examples), min(4, len(examples))))
        for r in random.sample(examples, min(4, len(examples))):
            log("")
            log("    {}".format(r["ref"][:104]))
            log("      crossref says : {}".format(r["truth"]))
            if key == "wrong":
                log("      this found    : {}".format(r["found"]))
                log("                      {}".format(r["found_title"][:76]))
            log("      state         : {}".format(r["state"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="reference_accuracy",
        description="Measure how often a genuine reference is missed.")
    ap.add_argument("--refs", type=int, default=1000)
    ap.add_argument("--works", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260821)
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    random.seed(args.seed)
    log = lambda m: print(m, file=sys.stderr, flush=True)   # noqa: E731

    log("  drawing works from Crossref...")
    works = sample_works(args.works, log)
    if not works:
        log("  nothing sampled")
        return 2

    pairs = labelled(works, args.refs, log)
    if not pairs:
        log("  no labelled references in that sample")
        return 2

    log("  checking...")
    rows = run(pairs, log)

    # Written before anything is displayed. A completed run of a thousand
    # references was lost twice to a console that could not encode a Turkish
    # dotless i, because the presentation ran before the record was kept.
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"checked": len(rows), "rows": rows}, fh, indent=1,
                      ensure_ascii=False)
        log("  wrote {}".format(args.json))

    report(rows, log=safe_print)
    return 0


if __name__ == "__main__":
    sys.exit(main())
