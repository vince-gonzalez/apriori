#!/usr/bin/env python3
"""
============================================================
authorecon.citation_resolve — does everything a record points
                              at still exist?
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

A deposit is permanent. What it points at is not.

Every record carries outbound identifiers: the code it
supplements, the data it documents, the earlier version it
replaces, the page that describes it. Those are ordinary URLs
and DOIs on somebody's server, and they break the way all URLs
break - a repository is renamed, an organisation migrates, a
site restructures, a host lapses.

Nothing tells you. The DOI still resolves, the record still
displays, and the link inside it quietly 404s. A reader
following your citation is the one who finds out.

  authorecon-citation-resolve 0000-0002-1825-0097
  authorecon-citation-resolve --doi 10.5281/zenodo.21769846

WHAT IT CHECKS

Everything the record points outward at, whether that is a DOI
or a bare URL. Both rot; only one of them is usually checked.

WHAT A RESULT MEANS

  ok          resolved, and the destination is the one named
  redirected  resolved somewhere else. Not broken, but the
              record now names a location that forwards, which
              is the state directly before broken
  dead        4xx or 5xx. A reader following this gets nothing
  unreachable could not be established either way. Reported as
              its own category rather than counted as dead,
              because a timeout is not evidence of absence

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.error
import urllib.request

from .discover import Problem, from_orcid, fetch, normalise_orcid, valid_checksum
from .qikstgen import ZENODO_RECORD

UA = "authorecon/0.7 (+https://f-keys.com; link check)"
TIMEOUT = 25

OK, REDIRECT, DEAD, UNREACHABLE = "ok", "redirected", "dead", "unreachable"


def as_url(identifier, scheme=""):
    """A checkable URL for whatever form the identifier is in."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    low = ident.lower()
    if low.startswith(("http://", "https://")):
        return ident
    if low.startswith("10.") or scheme.lower() == "doi":
        return "https://doi.org/" + ident
    if low.startswith("swh:"):
        return "https://archive.softwareheritage.org/" + ident
    if low.startswith("arxiv:"):
        return "https://arxiv.org/abs/" + ident.split(":", 1)[1]
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow nothing, so a redirect is visible rather than absorbed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise _Redirected(code, newurl)


class _Redirected(Exception):
    def __init__(self, code, url):
        self.code, self.url = code, url


def check(url, is_doi=False):
    """
    (state, detail). A HEAD first, falling back to GET for hosts that refuse
    HEAD - several do, and treating that as dead would be wrong.

    A DOI is followed rather than reported as moved. Redirection is what a DOI
    is FOR: doi.org resolves to wherever the publisher currently keeps the
    work, and that indirection is the entire point of the identifier. The
    first version of this flagged 103 of them as "redirected" and buried the
    one genuinely dead link in the noise. For a plain URL a redirect still
    matters, because there the record names a location that has moved.
    """
    if is_doi:
        req = urllib.request.Request(url, method="GET",
                                     headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return OK, str(r.status)
        except urllib.error.HTTPError as err:
            return DEAD, str(err.code)
        except Exception as err:
            return UNREACHABLE, type(err).__name__

    opener = urllib.request.build_opener(_NoRedirect)
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method,
                                     headers={"User-Agent": UA})
        try:
            with opener.open(req, timeout=TIMEOUT) as r:
                return OK, str(r.status)
        except _Redirected as r:
            return REDIRECT, "{} -> {}".format(r.code, r.url[:70])
        except urllib.error.HTTPError as err:
            if err.code in (403, 405, 501) and method == "HEAD":
                continue          # try GET before believing it
            return DEAD, str(err.code)
        except Exception as err:
            if method == "HEAD":
                continue
            return UNREACHABLE, type(err).__name__
    return UNREACHABLE, "no method succeeded"


def references_of(doi):
    """Every outbound identifier a Zenodo record carries."""
    m = re.search(r"zenodo\.(\d+)$", doi or "", re.I)
    if not m:
        return []
    try:
        rec = fetch(ZENODO_RECORD.format(m.group(1)))
    except Problem:
        return []
    out = []
    for rel in (rec.get("metadata") or {}).get("related_identifiers") or []:
        url = as_url(rel.get("identifier"), rel.get("scheme") or "")
        if url:
            out.append({"relation": rel.get("relation") or "",
                        "identifier": rel.get("identifier"),
                        "url": url})
    return out


def run(orcid, log=print, only_doi=None):
    if only_doi:
        works = [{"doi": only_doi, "title": only_doi}]
    else:
        works = [w for w in from_orcid(orcid) if w["doi"]]
        log("  {} works with a DOI".format(len(works)))

    rows, seen = [], {}
    for w in works:
        refs = references_of(w["doi"])
        for ref in refs:
            url = ref["url"]
            if url in seen:
                state, detail = seen[url]
            else:
                is_doi = url.startswith("https://doi.org/")
                state, detail = check(url, is_doi=is_doi)
                seen[url] = (state, detail)
                time.sleep(0.25)
            rows.append({
                "from_doi": w["doi"],
                "from_title": (w.get("title") or "")[:70],
                "relation": ref["relation"],
                "points_at": ref["identifier"],
                "state": state,
                "detail": detail,
            })
            if state in (DEAD, UNREACHABLE):
                log("    {:<11} {:<16} {}".format(state, ref["relation"],
                                                  ref["identifier"][:62]))
    return rows


def summarise(rows, log=print):
    counts = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    log("")
    log("  {} outbound identifiers across {} records".format(
        len(rows), len({r["from_doi"] for r in rows})))
    for state in (OK, REDIRECT, DEAD, UNREACHABLE):
        if counts.get(state):
            log("    {:<11} {}".format(state, counts[state]))

    dead = [r for r in rows if r["state"] == DEAD]
    if dead:
        log("")
        log("  DEAD - a reader following these gets nothing")
        for r in dead:
            log("    {}  {}".format(r["points_at"][:64], r["detail"]))
            log("      cited by {}".format(r["from_doi"]))

    moved = [r for r in rows if r["state"] == REDIRECT]
    if moved:
        log("")
        log("  REDIRECTED - resolves, but not to what the record names")
        for r in moved[:10]:
            log("    {}".format(r["points_at"][:64]))
            log("      {}".format(r["detail"]))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-citation-resolve",
        description="Check that everything a record points at still exists.")
    ap.add_argument("orcid", nargs="?")
    ap.add_argument("--doi", help="check one record instead of a whole ORCID")
    ap.add_argument("--csv", help="write the per-link evidence here")
    args = ap.parse_args(argv)

    if not args.orcid and not args.doi:
        ap.error("give an ORCID or --doi")

    try:
        orcid = None
        if args.orcid:
            orcid = normalise_orcid(args.orcid)
            if not valid_checksum(orcid):
                raise Problem("{} fails its check digit".format(orcid))
        rows = run(orcid, log=lambda m: print(m, file=sys.stderr),
                   only_doi=args.doi)
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    if not rows:
        print("  no outbound identifiers found", file=sys.stderr)
        return 0

    summarise(rows, log=print)

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print("\n  wrote {} ({} rows)".format(args.csv, len(rows)))

    return 1 if any(r["state"] == DEAD for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
