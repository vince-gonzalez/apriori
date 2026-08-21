#!/usr/bin/env python3
"""
============================================================
authorecon.discover — build a works record for any ORCID
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

authorecon could only ever reconcile one person's work: its
input came from Zenodo's deposit endpoint, which requires a
private token and returns only the token holder's records. A
tool that answers "does every place your work lives still agree
with the others" was structurally incapable of being pointed at
anybody else.

Nothing about the question is personal. So discovery is public
now: an ORCID goes in, and the works come from APIs that need
no key and no account.

  ORCID public API   what the author says they published
  OpenAlex           what the literature says, and who cited it
  Wikidata           whether an item exists for each DOI

The output is the same works document build_works.py writes, so
everything downstream is unchanged. The private path still
exists and still sees more - drafts, unpublished deposits, the
things only a token can reach. This sees what the world sees,
which is the more useful answer for everyone who is not you.

  python -m authorecon.discover 0000-0002-1825-0097
  authorecon-discover 0000-0002-1825-0097 --out works.json

No dependencies. Standard library only, like the rest of this
package, so it cannot fail on someone else's environment.
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "authorecon/0.2 (+https://f-keys.com; mailto:vincegonzalez@me.com)"
ORCID_API = "https://pub.orcid.org/v3.0/{}/works"
ORCID_REC = "https://pub.orcid.org/v3.0/{}/person"
OPENALEX = "https://api.openalex.org/works"
WIKIDATA = "https://www.wikidata.org/w/api.php"


class Problem(Exception):
    """Something the caller can fix, reported without a traceback."""


# ── the identifier ───────────────────────────────────────────

def normalise_orcid(value):
    """
    Accept the forms people actually paste - bare, hyphenated, or a full
    https://orcid.org/ URL - and return the canonical hyphenated form.
    """
    text = str(value).strip()
    for prefix in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    text = text.replace("-", "").replace(" ", "").upper()
    if len(text) != 16:
        raise Problem("An ORCID has 16 characters; this has {}.".format(len(text)))
    if not text[:15].isdigit() or text[15] not in "0123456789X":
        raise Problem("An ORCID is 15 digits and a final digit or X.")
    return "-".join(text[i:i + 4] for i in range(0, 16, 4))


def valid_checksum(orcid):
    """
    ORCID carries an ISO 7064 MOD 11-2 check digit. Verifying it locally means
    a mistyped identifier is rejected in front of the user rather than turning
    into an empty result set that looks like "this person published nothing".
    """
    digits = orcid.replace("-", "")
    total = 0
    for ch in digits[:15]:
        total = (total + int(ch)) * 2
    remainder = total % 11
    expected = (12 - remainder) % 11
    return digits[15] == ("X" if expected == 10 else str(expected))


# ── the network, kept boring ─────────────────────────────────

def fetch(url, accept="application/json", tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                raise Problem("Not found: {}".format(url))
            if err.code < 500:
                raise Problem("{} from {}".format(err.code, url))
            last = err
        except Exception as err:                     # network, timeout, JSON
            last = err
        time.sleep(1.5 * (attempt + 1))
    raise Problem("Gave up on {} ({})".format(url, last))


# ── the sources ──────────────────────────────────────────────

def author_name(orcid):
    """The name ORCID publishes, or None if the record is private."""
    try:
        person = fetch(ORCID_REC.format(orcid))
    except Problem:
        return None
    name = (person or {}).get("name") or {}
    if not name:
        return None
    given = ((name.get("given-names") or {}) or {}).get("value") or ""
    family = ((name.get("family-name") or {}) or {}).get("value") or ""
    full = (given + " " + family).strip()
    return full or None


def from_orcid(orcid):
    """What the author says they published."""
    doc = fetch(ORCID_API.format(orcid))
    out = []
    for group in doc.get("group", []):
        summaries = group.get("work-summary") or []
        if not summaries:
            continue
        first = summaries[0]
        ids = {}
        for ident in (group.get("external-ids") or {}).get("external-id", []):
            kind = (ident.get("external-id-type") or "").lower()
            ids.setdefault(kind, ident.get("external-id-value"))
        title = (((first.get("title") or {}).get("title") or {}).get("value") or "")
        date = first.get("publication-date") or {}
        year = ((date.get("year") or {}) or {}).get("value")
        out.append({
            "title": title.strip(),
            "doi": (ids.get("doi") or "").lower() or None,
            "date": year,
            "type": (first.get("type") or "").lower().replace("_", "-") or None,
            "put_code": first.get("put-code"),
        })
    return out


#: How many OpenAlex works to page through before giving up. Josiah Carberry,
#: ORCID's own example record, has 1,972 - it is a shared fictional identity -
#: and a real person can legitimately have hundreds. The cap exists so this
#: cannot run forever, and reaching it is reported rather than swallowed.
OPENALEX_MAX = 2000


def from_openalex(orcid, mailto=None, cap=OPENALEX_MAX):
    """
    What the literature says, including who has cited it.

    This pages. The first version read one page of 200 and reported the count
    of what it had seen, which on a record with 1,972 works announced "191
    unclaimed" and looked like a complete answer. A number taken from the
    first page and presented as the total is worse than no number.

    Returns (by_doi, reported_total, complete, no_doi). The last two exist so
    the numbers reconcile out loud: `complete` is false when the cap stopped
    paging early, and `no_doi` accounts for the gap between what OpenAlex
    reports and what lands here, which is works it indexes without a DOI. An
    unexplained difference between two numbers in a report is indistinguishable
    from a bug.
    """
    by_doi = {}
    cursor = "*"
    total = 0
    no_doi = 0
    while cursor and len(by_doi) < cap:
        params = {
            "filter": "author.orcid:" + orcid,
            "per-page": "200",
            "cursor": cursor,
        }
        if mailto:
            params["mailto"] = mailto
        doc = fetch(OPENALEX + "?" + urllib.parse.urlencode(params))
        total = (doc.get("meta") or {}).get("count", total)
        results = doc.get("results") or []
        if not results:
            break
        for work in results:
            doi = (work.get("doi") or "").lower()
            if doi.startswith("https://doi.org/"):
                doi = doi[len("https://doi.org/"):]
            if not doi:
                no_doi += 1
                continue
            by_doi[doi] = {
                "openalex": work.get("id"),
                "cited_by": work.get("cited_by_count", 0),
                "open_access": ((work.get("open_access") or {}).get("is_oa")),
                "type": work.get("type"),
            }
        cursor = (doc.get("meta") or {}).get("next_cursor")
        time.sleep(0.1)
    complete = len(by_doi) < cap or not cursor
    return by_doi, total, complete, no_doi


def wikidata_for(doi):
    """An item whose P356 is this DOI. Wikidata stores them uppercase."""
    params = {
        "action": "query", "list": "search",
        "srsearch": "haswbstatement:P356=" + doi.upper(),
        "srlimit": "1", "format": "json",
    }
    try:
        doc = fetch(WIKIDATA + "?" + urllib.parse.urlencode(params))
    except Problem:
        return None
    hits = (doc.get("query") or {}).get("search") or []
    return hits[0]["title"] if hits else None


# ── putting it together ──────────────────────────────────────

def discover(orcid, with_wikidata=True, mailto=None, log=print):
    orcid = normalise_orcid(orcid)
    if not valid_checksum(orcid):
        raise Problem(
            "{} is not a valid ORCID - the check digit does not match, which "
            "almost always means a typo.".format(orcid))

    log("  orcid    {}".format(orcid))
    name = author_name(orcid)
    log("  name     {}".format(name or "(not public)"))

    orcid_works = from_orcid(orcid)
    log("  orcid    {} works listed".format(len(orcid_works)))

    alex, alex_count, complete, no_doi = from_openalex(orcid, mailto=mailto)
    log("  openalex {} indexed = {} with a DOI + {} without".format(
        alex_count, len(alex), no_doi))
    if not complete:
        log("  NOTE     stopped at {} works; the counts below cover what was "
            "read, not the whole record".format(len(alex)))

    works, seen = [], set()
    for w in orcid_works:
        doi = w["doi"]
        if doi and doi in seen:
            continue
        if doi:
            seen.add(doi)
        extra = alex.get(doi or "", {})
        works.append({
            "title": w["title"],
            "doi": doi,
            "date": w["date"],
            "type": w["type"] or extra.get("type"),
            "openalex": extra.get("openalex"),
            "cited_by": extra.get("cited_by"),
            "open_access": extra.get("open_access"),
            "wikidata": None,
            "in_openalex": bool(extra),
        })

    # Anything OpenAlex knows that the ORCID record does not is worth naming:
    # it is usually a work the author has never claimed.
    unclaimed = [d for d in alex if d not in seen]
    for doi in unclaimed:
        extra = alex[doi]
        works.append({
            "title": None, "doi": doi, "date": None,
            "type": extra.get("type"), "openalex": extra.get("openalex"),
            "cited_by": extra.get("cited_by"),
            "open_access": extra.get("open_access"),
            "wikidata": None, "in_openalex": True, "unclaimed": True,
        })
    if unclaimed:
        log("  unclaimed {} in OpenAlex but not on the ORCID record{}"
            .format(len(unclaimed), "" if complete else " (of those read)"))

    if with_wikidata:
        found = 0
        for w in works:
            if w["doi"]:
                w["wikidata"] = wikidata_for(w["doi"])
                found += bool(w["wikidata"])
                time.sleep(0.2)              # be a good citizen
        log("  wikidata {} of {} have an item".format(found, len(works)))

    works.sort(key=lambda w: (w.get("date") or "", w.get("doi") or ""))
    return {
        "author": {"name": name, "orcid": orcid},
        "source": "public",
        "openalex_total": alex_count,
        "openalex_with_doi": len(alex),
        "openalex_without_doi": no_doi,
        "paged_to_end": complete,
        "works": works,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-discover",
        description="Build a works record for any ORCID, from public sources only.")
    ap.add_argument("orcid", help="an ORCID, bare or as a full orcid.org URL")
    ap.add_argument("--out", help="write JSON here instead of standard output")
    ap.add_argument("--no-wikidata", action="store_true",
                    help="skip the Wikidata lookup, which is the slow part")
    ap.add_argument("--mailto", help="your email, which OpenAlex asks for to "
                                     "give you the faster pool")
    args = ap.parse_args(argv)

    try:
        doc = discover(args.orcid,
                       with_wikidata=not args.no_wikidata,
                       mailto=args.mailto,
                       log=lambda m: print(m, file=sys.stderr))
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("  wrote {}".format(args.out), file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
