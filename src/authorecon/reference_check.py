#!/usr/bin/env python3
"""
============================================================
authorecon.reference_check — are these references real?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

A reference list is the one part of a manuscript that claims,
line by line, that something else exists. Until recently that
claim was safe to assume. It is now the cheapest thing in a
document to manufacture, and the most expensive to check by
hand.

  authorecon-reference-check bibliography.txt
  authorecon-reference-check refs.txt --json out.json

WHAT IT SEPARATES

  confirmed         the identifier resolves and the record
                    matches what the reference says
  located           no identifier was given; here is the
                    record that matches it
  review            a record was found and agrees only in part
  divergent         the identifier is real and belongs to a
                    different work
  unlocatable       no record matching this reference exists
                    in any index consulted
  retracted         the work exists and has been retracted
  unchecked         a source could not be reached, so nothing
                    is claimed

WHY IT VERIFIES RATHER THAN SEARCHES

A bibliographic search returns its best guess for anything,
including a reference to a paper that was never written. The
score it returns ranks relevance and says nothing about
whether the work is the one meant, so every candidate is
checked against the words of the reference before it is
accepted.

Three findings shaped that check, all of them from running it
against references built to defeat it:

  Counting a title's matching words fails, because a
  fabricated journal name can supply them. A title has to
  appear as a contiguous run.

  Measuring that run against the whole record title then fails
  correct citations, because citers drop subtitles.

  A matching title is still not a matching work. Duplicate
  records carrying a famous title and a different year
  circulate through the indexes.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse

from .discover import CONTACT, Problem, fetch

CROSSREF = "https://api.crossref.org/works"
DATACITE = "https://api.datacite.org/dois/"
OPENALEX = "https://api.openalex.org/works/doi:"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OPENLIB = "https://openlibrary.org/isbn/{}.json"
PUBMED = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"

CONFIRMED = "confirmed"
LOCATED = "located"
REVIEW = "review"
DIVERGENT = "divergent"
UNLOCATABLE = "unlocatable"
RETRACTED = "retracted"
UNCHECKED = "unchecked"

#: A title present as one run is a citation. Words gathered from an author
#: list and a journal name are a coincidence. Half is where one becomes the
#: other.
AGREES = 0.70
DIFFERS = 0.50


# ── splitting a pasted bibliography ──────────────────────────

def split_refs(text):
    """
    A reference list arrives in one of three shapes, and the shape has to be
    detected rather than assumed: blocks separated by a blank line, entries
    opened by a number, or one entry per line with continuations indented.
    """
    raw = (text or "").replace("\r", "")
    if not raw.strip():
        return []

    blocks = [re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n\s*\n", raw)]
    blocks = [b for b in blocks if len(b) > 24]
    if len(blocks) > 1:
        return blocks

    numbered = re.split(r"\n(?=\s*[\[(]?\d{1,3}[\].)]\s)", raw)
    if len(numbered) > 1:
        out = [re.sub(r"\s+", " ", b).strip() for b in numbered]
        return [b for b in out if len(b) > 24]

    lines = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        if re.match(r"^(\s{2,}|\t)", line) and lines:
            lines[-1] += " " + line.strip()
        else:
            lines.append(line.strip())
    return [re.sub(r"\s+", " ", b).strip() for b in lines if len(b) > 24]


# ── what a reference already tells us ────────────────────────

def find_doi(ref):
    m = re.search(r"\b(10\.\d{4,9}/[^\s\"'<>,]+)", ref or "", re.I)
    if not m:
        return None
    # Trailing sentence punctuation belongs to the prose, not the DOI.
    return m.group(1).rstrip(".,;)]").lower()


def find_isbn(ref):
    # The hyphen goes first in the class. Written as [\d- ] it reads as a
    # range from a digit to a space, which Python rejects and JavaScript
    # quietly accepts - the same pattern, two engines, one of them wrong.
    m = re.search(r"\bISBN[:\s]*((?:97[89][- ]?)?\d[-\d ]{8,}[\dXx])",
                  ref or "")
    return re.sub(r"[- ]", "", m.group(1)) if m else None


def find_year(ref):
    """Preferred from parentheses: that is where a citation puts the year,
    and a page range is full of other four-digit numbers."""
    m = re.search(r"\((\d{4})[a-z]?\)", ref or "")
    if m:
        return int(m.group(1))
    m = re.search(r"\b(1[89]\d{2}|20\d{2})\b", ref or "")
    return int(m.group(1)) if m else None


def year_agrees(a, b):
    """A year apart is ordinary - online first in one year, in an issue the
    next. Two or more apart is a different publication."""
    if not a or not b:
        return True
    return abs(int(a) - int(b)) <= 1


# ── does the record match the reference that named it ────────

def skeleton(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def longest_run(a, b):
    """Longest run of characters the two share."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _ratio(title, ref):
    t, r = skeleton(title), skeleton(ref)
    if not t or not r:
        return 0.0
    # Two or three short words carry too little to judge on a partial run.
    if len(t) < 12:
        return 1.0 if t in r else 0.0
    return longest_run(t, r) / float(len(t))


def agreement(title, ref):
    """Read against the main title as well as the whole one, because a
    correct reference to a work should not be called wrong for omitting the
    eight words after its colon."""
    best = _ratio(title, ref)
    main = re.split(r"[:;]|\s[-–—]\s", title or "")[0].strip()
    if main and main != title and len(skeleton(main)) >= 12:
        best = max(best, _ratio(main, ref))
    return best


def verdict(score):
    if score >= AGREES:
        return "agrees"
    if score < DIFFERS:
        return "differs"
    return "partial"


# ── each source, read into one shape ─────────────────────────

def _record(doi, title, authors, year, venue, source, kind=""):
    return {"doi": (doi or "").lower() or None, "title": title or "",
            "authors": [a for a in (authors or []) if a], "year": year,
            "venue": venue or "", "type": kind, "source": source}


def from_crossref(m):
    parts = ((m.get("issued") or {}).get("date-parts") or [[]])[0]
    return _record(
        m.get("DOI"), (m.get("title") or [""])[0],
        [a.get("family") or a.get("name") for a in (m.get("author") or [])],
        parts[0] if parts else None,
        (m.get("container-title") or [""])[0] or m.get("publisher", ""),
        "Crossref", m.get("type", ""))


def from_datacite(d):
    a = d.get("attributes") or {}
    return _record(
        a.get("doi"), ((a.get("titles") or [{}])[0]).get("title"),
        [c.get("familyName") or c.get("name") for c in (a.get("creators") or [])],
        a.get("publicationYear"), a.get("publisher"), "DataCite",
        (a.get("types") or {}).get("resourceTypeGeneral", ""))


def from_europepmc(r):
    return _record(r.get("doi"), r.get("title"),
                   [x.strip() for x in (r.get("authorString") or "").split(",")],
                   r.get("pubYear"), r.get("journalTitle"), "Europe PMC",
                   "journal-article")


# ── the lookups ──────────────────────────────────────────────

def _q(params):
    params["mailto"] = CONTACT
    return urllib.parse.urlencode(params)


def by_doi(doi):
    try:
        return from_crossref(fetch(CROSSREF + "/" +
                                   urllib.parse.quote(doi, safe="/"))["message"])
    except Problem:
        pass
    try:
        return from_datacite(fetch(DATACITE +
                                   urllib.parse.quote(doi, safe=""))["data"])
    except Problem:
        return None


def search_crossref(ref):
    url = CROSSREF + "?" + _q({
        "rows": "3", "query.bibliographic": ref[:400],
        "select": "DOI,title,author,issued,container-title,publisher,type"})
    try:
        return [from_crossref(i)
                for i in (fetch(url).get("message") or {}).get("items") or []]
    except Problem:
        return []


def search_europepmc(ref):
    url = EUROPEPMC + "?" + urllib.parse.urlencode(
        {"format": "json", "pageSize": "3", "query": ref[:300]})
    try:
        got = fetch(url).get("resultList") or {}
        return [from_europepmc(r) for r in got.get("result") or []]
    except Problem:
        return []


def search_pubmed(ref):
    """
    PubMed refuses requests from a web page, which is why the browser
    version of this check cannot ask it and this one can.
    """
    url = PUBMED + "?" + urllib.parse.urlencode(
        {"db": "pubmed", "retmode": "json", "retmax": "3",
         "tool": "authorecon", "email": CONTACT, "term": ref[:300]})
    try:
        ids = ((fetch(url).get("esearchresult") or {}).get("idlist")) or []
    except Problem:
        return []
    out = []
    for pmid in ids[:3]:
        found = search_europepmc("EXT_ID:" + pmid)
        out.extend(found)
    return out


def by_isbn(isbn):
    try:
        b = fetch(OPENLIB.format(isbn))
    except Problem:
        return None
    year = re.search(r"\d{4}", str(b.get("publish_date") or ""))
    rec = _record(None, b.get("title"), [], year.group(0) if year else None,
                  (b.get("publishers") or [""])[0], "OpenLibrary", "book")
    rec["isbn"] = isbn
    return rec


def is_retracted(doi):
    if not doi:
        return False
    try:
        return bool(fetch(OPENALEX + urllib.parse.quote(doi, safe="/") + "?" +
                          _q({})).get("is_retracted"))
    except Problem:
        return False


# ── one reference, start to finish ───────────────────────────

def check_one(ref):
    doi, isbn, year = find_doi(ref), find_isbn(ref), find_year(ref)
    out = {"ref": ref, "given": doi or isbn, "found": None, "state": None,
           "says": ""}

    if doi:
        rec = by_doi(doi)
        if not rec:
            out["state"] = UNLOCATABLE
            out["says"] = ("The reference gives a DOI and no index has a "
                           "record under it.")
            return out
        out["found"] = rec
        v = verdict(agreement(rec["title"], ref))
        if v == "agrees" and not year_agrees(year, rec["year"]):
            out["state"] = REVIEW
            out["says"] = ("The DOI resolves to a work of this title published "
                           "in {}, where the reference says {}."
                           .format(rec["year"], year))
        elif v == "agrees":
            out["state"] = CONFIRMED
        elif v == "differs":
            out["state"] = DIVERGENT
            out["says"] = ("The DOI is real and belongs to a different work "
                           "from the one this reference describes.")
        else:
            out["state"] = REVIEW
            out["says"] = ("The DOI resolves, and the record only partly "
                           "matches the reference as written.")

    elif isbn:
        rec = by_isbn(isbn)
        if not rec:
            out["state"] = UNLOCATABLE
            out["says"] = "No book is catalogued under that ISBN."
            return out
        out["found"] = rec
        out["state"] = (DIVERGENT if verdict(agreement(rec["title"], ref))
                        == "differs" else CONFIRMED)
        if out["state"] == DIVERGENT:
            out["says"] = ("The ISBN is catalogued, under a different title "
                           "from the one written here.")

    else:
        # Crossref first, then the indexes that hold what Crossref does not.
        candidates = search_crossref(ref)
        candidates += search_europepmc(ref)
        candidates += search_pubmed(ref)

        scored = sorted(
            ({"rec": c, "score": agreement(c["title"], ref),
              "solid": verdict(agreement(c["title"], ref)) == "agrees"
                       and year_agrees(year, c["year"])}
             for c in candidates),
            key=lambda x: (not x["solid"], -x["score"]))

        best = scored[0] if scored else None
        if best and verdict(best["score"]) == "agrees":
            out["found"] = best["rec"]
            if year_agrees(year, best["rec"]["year"]):
                out["state"] = LOCATED
                out["says"] = ("No identifier was given in the reference. "
                               "This is the record that matches it.")
            else:
                out["state"] = REVIEW
                out["says"] = ("A record with this title exists, published in "
                               "{} where the reference says {}. Duplicate "
                               "records of the same title do circulate."
                               .format(best["rec"]["year"], year))
        elif best and verdict(best["score"]) == "partial":
            out["found"] = best["rec"]
            out["state"] = REVIEW
            out["says"] = ("The closest record found agrees with part of this "
                           "reference.")
        else:
            out["state"] = UNLOCATABLE
            out["says"] = ("No record matching this reference was found in any "
                           "of the indexes consulted.")

    found = (out["found"] or {}).get("doi")
    if found and out["state"] != UNLOCATABLE and is_retracted(found):
        out["state"] = RETRACTED
        out["says"] = ("The work exists and has been retracted. A retracted "
                       "work can be cited deliberately; it needs to be cited "
                       "knowingly.")
    return out


def run(text, log=print):
    refs = split_refs(text)
    log("  {} reference(s)".format(len(refs)))
    rows = []
    for n, ref in enumerate(refs, 1):
        try:
            row = check_one(ref)
        except Problem as err:
            row = {"ref": ref, "found": None, "state": UNCHECKED,
                   "says": str(err)}
        except Exception as err:                 # noqa: BLE001 - report, do not die
            row = {"ref": ref, "found": None, "state": UNCHECKED,
                   "says": "{}: {}".format(type(err).__name__, err)}
        rows.append(row)
        log("    {:>3}  {:<12} {}".format(n, row["state"], ref[:58]))
        time.sleep(0.1)
    return rows


ORDER = [CONFIRMED, LOCATED, REVIEW, DIVERGENT, UNLOCATABLE, RETRACTED,
         UNCHECKED]


def report(rows, log=print):
    counts = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    log("")
    log("  {} reference(s) read".format(len(rows)))
    for state in ORDER:
        if counts.get(state):
            log("    {:<14} {}".format(state, counts[state]))

    unchecked = [r for r in rows if r["state"] == UNCHECKED]
    if unchecked:
        # Six references this could not read once printed "every reference
        # resolved" and exited 0. Nothing examined is not everything fine.
        log("")
        log("  {} reference(s) could not be checked, so nothing is claimed "
            "about them:".format(len(unchecked)))
        for r in unchecked[:5]:
            log("    {}".format(r["ref"][:76]))
            if r["says"]:
                log("        {}".format(r["says"][:76]))

    attention = [r for r in rows
                 if r["state"] in (DIVERGENT, UNLOCATABLE, RETRACTED)]
    if not attention:
        log("")
        if unchecked:
            log("  Of the {} that were checked, each resolved to a record "
                "that matches it.".format(len(rows) - len(unchecked)))
        else:
            log("  Every reference resolved to a record that matches it.")
        return

    log("")
    log("  WORTH OPENING")
    for r in attention:
        log("")
        log("    [{}] {}".format(r["state"], r["ref"][:90]))
        if r["found"]:
            log("        the identifier points at: {}"
                .format(r["found"]["title"][:74]))
        if r["says"]:
            log("        {}".format(r["says"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-reference-check",
        description="Resolve every reference in a bibliography.")
    ap.add_argument("file", help="a file of references, or - for standard input")
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args(argv)

    if args.file == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.file, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as err:
            print("  {}".format(err), file=sys.stderr)
            return 2

    rows = run(text, log=lambda m: print(m, file=sys.stderr))
    if not rows:
        print("  Nothing in that file reads as a reference.", file=sys.stderr)
        return 2

    report(rows, log=print)

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"references": rows}, fh, indent=1, ensure_ascii=False)
        print("\n  wrote {}".format(args.json))

    bad = sum(1 for r in rows
              if r["state"] in (DIVERGENT, UNLOCATABLE, RETRACTED))
    stuck = sum(1 for r in rows if r["state"] == UNCHECKED)
    if stuck:
        return 2          # could not establish, which is not the same as clean
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
