#!/usr/bin/env python3
"""
============================================================
authorecon.index_lag — how long does a deposit take to reach
                       the index, and what is lost on the way
F-Keys | www.f-keys.com
------------------------------------------------------------
WHAT IT MEASURES

Two things, both from records that already exist:

  LAG          days between the Zenodo publication date and the
               date OpenAlex created its record for that work
  ATTRIBUTION  whether the ORCID present on the Zenodo record
               survived into the OpenAlex record

Neither number is anywhere. Repositories report deposits and
indexes report holdings; nobody reports the gap between them,
and the gap is where an author's attribution quietly goes.

  authorecon-index-lag 0000-0002-1825-0097
  authorecon-index-lag --file orcids.txt --csv out.csv

METHOD, STATED BECAUSE THE NUMBER IS ONLY WORTH WHAT THE
METHOD IS

A work that has not been indexed yet has no lag - it has a
lower bound. Dropping those from the average is the obvious
mistake and it biases the result downward, because the slowest
works are exactly the ones still missing. They are reported
separately as censored observations, with the age each has
reached, so a reader can see what the average excludes and
how much it could move.

Attribution is only counted where Zenodo carries an ORCID. A
work whose deposit never had one cannot have lost it, and
counting it as a loss would blame the index for the author's
own metadata.

Both are per-work facts, so the CSV is the actual evidence and
the summary is only a convenience over it.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import sys
import time

from .discover import (Problem, fetch, from_orcid, normalise_orcid,
                       valid_checksum)
from .qikstgen import ZENODO_RECORD

OPENALEX_WORK = "https://api.openalex.org/works/doi:{}"


def as_date(value):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return datetime.date(*[int(x) for x in m.groups()])
    except ValueError:
        return None


def zenodo_facts(doi):
    m = re.search(r"zenodo\.(\d+)$", doi or "", re.I)
    if not m:
        return None
    try:
        rec = fetch(ZENODO_RECORD.format(m.group(1)))
    except Problem:
        return None
    md = rec.get("metadata") or {}
    creators = md.get("creators") or []
    rt = md.get("resource_type") or {}
    return {
        "deposited": as_date(md.get("publication_date")),
        "has_orcid": any(c.get("orcid") for c in creators),
        "type": (rt.get("subtype") or rt.get("type")
                 or md.get("upload_type") or "").lower(),
        "title": md.get("title") or "",
    }


def openalex_facts(doi):
    try:
        w = fetch(OPENALEX_WORK.format(doi))
    except Problem:
        return None
    orcids = [(a.get("author") or {}).get("orcid")
              for a in (w.get("authorships") or [])]
    return {
        "created": as_date(w.get("created_date")),
        "has_orcid": any(orcids),
        "id": w.get("id"),
    }


def measure(orcid, log=print, today=None):
    today = today or datetime.date.today()
    works = from_orcid(orcid)
    log("  {}  {} works".format(orcid, len(works)))
    rows = []
    for w in works:
        doi = w["doi"]
        if not doi:
            continue
        zen = zenodo_facts(doi)
        if not zen or not zen["deposited"]:
            # Dropping this silently was a real defect. A work on the record
            # whose deposit will not load is not absent from the sample - it
            # is the most interesting row in it. One deposit on the record
            # this was written against returns 410 Gone: withdrawn from the
            # repository and still listed on the ORCID profile. Skipping it
            # shrank the denominator without saying so, and the summary then
            # counted "not indexed" out of a total it no longer had.
            rows.append({
                "orcid": orcid,
                "doi": doi,
                "title": (w.get("title") or "")[:90],
                "type": "",
                "deposited": "",
                "indexed_on": "",
                "lag_days": "",
                "age_days": "",
                "censored": "yes",
                "class": "no_deposit",
                "zenodo_orcid": "",
                "openalex_orcid": "",
            })
            time.sleep(0.12)
            continue
        alex = openalex_facts(doi)
        indexed = bool(alex and alex["created"])
        lag = (alex["created"] - zen["deposited"]).days if indexed else None
        rows.append({
            "orcid": orcid,
            "doi": doi,
            "title": zen["title"][:90],
            "type": zen["type"],
            "deposited": zen["deposited"].isoformat(),
            "indexed_on": alex["created"].isoformat() if indexed else "",
            "lag_days": "" if lag is None else lag,
            "age_days": (today - zen["deposited"]).days,
            "censored": "" if indexed else "yes",
            "class": ("not_indexed" if not indexed
                      else ("prematched" if lag < 0 else "ingested")),
            "zenodo_orcid": "yes" if zen["has_orcid"] else "no",
            "openalex_orcid": ("yes" if (alex and alex["has_orcid"])
                               else ("no" if indexed else "")),
        })
        time.sleep(0.12)
    return rows


def summarise(rows, log=print):
    indexed = [r for r in rows if r["censored"] != "yes"]
    gone = [r for r in rows if r["class"] == "no_deposit"]
    censored = [r for r in rows
                if r["censored"] == "yes" and r["class"] != "no_deposit"]

    # A record OpenAlex created BEFORE the deposit date was not ingested late
    # or early - it was matched to a work OpenAlex already held, which for
    # Zenodo means an earlier version of the same deposit. The difference
    # between those two dates is not a lag and averaging it in destroys the
    # statistic: one such work at -308 days pulled a median of 1 day to a mean
    # of -6.7. They are counted and named, not silently dropped and not
    # clamped to zero.
    prematched = [r for r in indexed if int(r["lag_days"]) < 0]
    fresh = [r for r in indexed if int(r["lag_days"]) >= 0]
    lags = sorted(int(r["lag_days"]) for r in fresh)

    log("")
    log("  SAMPLE")
    log("    {} deposits with a resolvable Zenodo record".format(len(rows)))
    log("    {} indexed by OpenAlex".format(len(indexed)))
    log("      of those, {} ingested after deposit (measurable)".format(len(fresh)))
    log("      and {} matched to a record OpenAlex already held".format(
        len(prematched)))
    log("    {} not indexed yet (censored)".format(len(censored)))
    if gone:
        log("    {} on the record whose deposit will not load".format(
            len(gone)))
        for r in gone:
            log("      {}  {}".format(r["doi"], r["title"][:52]))
        log("      A DOI on a public profile that resolves to nothing is")
        log("      worth fixing before anyone follows it.")

    if lags:
        mid = lags[len(lags) // 2] if len(lags) % 2 else (
            (lags[len(lags) // 2 - 1] + lags[len(lags) // 2]) / 2)
        log("")
        log("  LAG, for the {} ingested after their deposit".format(len(lags)))
        log("    median   {} days".format(mid))
        log("    mean     {:.1f} days".format(sum(lags) / len(lags)))
        log("    range    {} to {} days".format(lags[0], lags[-1]))
        # A negative lag means OpenAlex created its record before the stated
        # publication date, which happens and is worth seeing rather than
        # clamping to zero.
    if prematched:
        log("")
        log("  MATCHED TO AN EXISTING RECORD - not an ingestion lag")
        for r in sorted(prematched, key=lambda x: int(x["lag_days"]))[:6]:
            log("    {}  deposited {}, record created {}  ({} days)".format(
                r["doi"], r["deposited"], r["indexed_on"], r["lag_days"]))
        log("    These are almost always a later version of a work OpenAlex")
        log("    already indexed, so the two dates describe different things.")

    if censored:
        ages = sorted(int(r["age_days"]) for r in censored)
        log("")
        log("  NOT INDEXED - these have no lag, only a lower bound")
        log("    oldest still missing: {} days".format(ages[-1]))
        log("    median age          : {} days".format(ages[len(ages) // 2]))
        log("    the true median lag is at least the figure above and cannot")
        log("    be computed until these arrive or are declared lost")

    eligible = [r for r in indexed if r["zenodo_orcid"] == "yes"]
    kept = [r for r in eligible if r["openalex_orcid"] == "yes"]
    if eligible:
        log("")
        log("  ATTRIBUTION, for indexed works whose deposit carried an ORCID")
        log("    {} of {} kept it  ({:.0f}%)".format(
            len(kept), len(eligible), 100.0 * len(kept) / len(eligible)))
        lost = [r for r in eligible if r["openalex_orcid"] == "no"]
        if lost:
            log("    {} lost it in transit:".format(len(lost)))
            for r in lost[:8]:
                log("      {}  {}".format(r["doi"], r["title"][:46]))
            if len(lost) > 8:
                log("      ... and {} more".format(len(lost) - 8))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-index-lag",
        description="Measure how long deposits take to reach OpenAlex, and "
                    "how often ORCID attribution survives the trip.")
    ap.add_argument("orcid", nargs="*", help="one or more ORCIDs")
    ap.add_argument("--file", help="a file of ORCIDs, one per line")
    ap.add_argument("--csv", help="write the per-work evidence here")
    ap.add_argument("--json", help="write the per-work evidence as JSON")
    args = ap.parse_args(argv)

    targets = list(args.orcid)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            targets += [ln.strip() for ln in fh
                        if ln.strip() and not ln.startswith("#")]
    if not targets:
        ap.error("give at least one ORCID, or --file")

    rows = []
    for raw in targets:
        try:
            orcid = normalise_orcid(raw)
            if not valid_checksum(orcid):
                raise Problem("{} fails its check digit".format(orcid))
            rows += measure(orcid, log=lambda m: print(m, file=sys.stderr))
        except Problem as err:
            print("  skipped {}: {}".format(raw, err), file=sys.stderr)

    if not rows:
        print("  nothing measurable", file=sys.stderr)
        return 2

    summarise(rows, log=print)

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print("\n  wrote {} ({} rows)".format(args.csv, len(rows)))
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(rows, fh, indent=1, ensure_ascii=False)
        print("  wrote {}".format(args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
