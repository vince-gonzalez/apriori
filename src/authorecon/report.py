#!/usr/bin/env python3
"""
============================================================
authorecon.report — one pass, one document
F-Keys | www.f-keys.com
------------------------------------------------------------
WHY THIS EXISTS

Nineteen checks is a toolkit. Somebody deciding whether an
unfamiliar body of work is what it claims has one question and
no appetite for nineteen commands.

So this runs the checks that take nothing but an ORCID and
writes one document: what the record is, where it lives, what
disagrees, and what could not be established.

  authorecon-report 0000-0002-1825-0097
  authorecon-report 0000-0002-1825-0097 --json out.json

WHAT IT DOES NOT INCLUDE

The checks that need something other than an ORCID - a local
PDF, a dependency graph, a repository to walk - are not run
here and are named at the end rather than silently omitted.

HOW TO READ IT

Every section reports what it found and what it could not
reach. A check that could not run says so; it never reports
success by default. Nothing here is scored, ranked or graded:
the sections state facts and the reader draws the conclusion,
because the same fact means different things for a graduate
student and a professor of thirty years.

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import (abstract_op, name_privacy, citation_resolve, deposit_lint, discover,
               index_lag, orcid_collision, pdf_conform, qikstgen,
               retraction_watch, self_citation, venue_reality, wd_sweeper)
from .discover import Problem, normalise_orcid, valid_checksum

RULE = "  " + "-" * 66


class Section(object):
    """One check's outcome, including the outcome of not running."""

    def __init__(self, title, lines=None, error=None, data=None):
        self.title = title
        self.lines = lines or []
        self.error = error
        self.data = data


def run_one(title, fn, log):
    """Run a check and keep going if it fails. One dead API is not a report."""
    log("  running {}...".format(title.lower()))
    collected = []
    started = time.time()
    try:
        data = fn(collected.append)
        return Section(title, collected, data=data)
    except Problem as err:
        return Section(title, error=str(err))
    except Exception as err:                     # noqa: BLE001 - report, do not die
        return Section(title, error="{}: {}".format(type(err).__name__, err))
    finally:
        log("    {:.0f}s".format(time.time() - started))


def build(orcid, log=print):
    sections = []
    quiet = lambda *_: None                      # noqa: E731

    def identity(emit):
        name = orcid_collision.author_name(orcid) or ""
        total, results = orcid_collision.candidates(name)
        rows = orcid_collision.classify(results, orcid)
        mine = [r for r in rows if r["kind"] == orcid_collision.SAME]
        anon = [r for r in rows if r["kind"] == orcid_collision.NO_ORCID]
        other = [r for r in rows if r["kind"] == orcid_collision.DIFFERENT]
        emit("{} author record(s) in OpenAlex share this name".format(total))
        if len(mine) > 1:
            emit("This ORCID is split across {} author records: {}".format(
                len(mine), ", ".join(
                    "{} ({} works)".format(r["id"], r["works"]) for r in mine)))
        emit("{} share the name with no identifier at all, {} works between "
             "them".format(len(anon), sum(r["works"] for r in anon)))
        emit("{} are different identified people".format(len(other)))
        split = name_privacy.fragmentation(rows, name)
        if split:
            emit(split)
        # These rows leave this process as JSON. Names do not leave with them.
        return {"total": total, "rows": name_privacy.redact(rows)}

    def record(emit):
        doc = discover.discover(orcid, with_wikidata=False, log=quiet)
        works = doc["works"]
        unclaimed = [w for w in works if w.get("unclaimed")]
        on_record = [w for w in works if not w.get("unclaimed")]
        # "of them" means the works ON THE RECORD, so it has to be counted
        # from those. It was counted from every work discovered, unclaimed
        # ones included, which produced "6 works on the ORCID record" and
        # "1600 of them are indexed" one line apart. A report that
        # contradicts itself in two adjacent sentences is not read further,
        # and this one is paid for.
        indexed = [w for w in on_record if w.get("in_openalex")]
        emit("{} works on the ORCID record".format(len(on_record)))
        # Two different questions, and conflating them made three sections of
        # this report disagree. "Attributed" asks OpenAlex what it files under
        # this ORCID. "Indexed" asks whether the work is there at all. The
        # difference is attribution the index lost, and it belongs here rather
        # than four sections later.
        emit("{} of them are indexed by OpenAlex AND attributed to this ORCID"
             .format(len(indexed)))
        emit("{} indexed works are absent from the ORCID record".format(
            len(unclaimed)))
        emit("OpenAlex holds {} works for this ORCID: {} with a DOI, {} "
             "without".format(doc["openalex_total"], doc["openalex_with_doi"],
                              doc["openalex_without_doi"]))
        return doc

    def venues(emit):
        rows = venue_reality.survey(orcid, log=quiet)
        present = sum(1 for r in rows if r["kind"] != "not indexed")
        emit("{} of {} works are in OpenAlex when looked up by DOI directly, "
             "whatever it attributes them to".format(present, len(rows)))
        kinds = {}
        for r in rows:
            kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
        for kind, n in sorted(kinds.items(), key=lambda x: -x[1]):
            emit("{:<14} {}".format(kind, n))
        if kinds.get("repository") and not kinds.get("journal"):
            emit("Every work is a repository deposit. None went through peer "
                 "review at a venue.")
        return rows

    def citations(emit):
        rows, external, mine = self_citation.analyse(orcid, log=quiet)
        total = external + mine
        emit("{} citation(s) recorded".format(total))
        if total:
            emit("{} external, {} from the author's own work".format(
                external, mine))
            emit("External citations are the evidence somebody else read it.")
        # This is a floor, not a count. It is bounded by what the indexes have
        # ingested, and the next section of this same report measures how far
        # behind that ingestion runs. A report that reconciles other people's
        # records against each other has no business quoting one of its own
        # numbers as settled when it can see the lag itself.
        emit("A floor, not a total: only citations the indexes have already "
             "ingested can be counted, and recent work is undercounted by "
             "however far behind they are running.")
        return {"external": external, "self": mine}

    def timing(emit):
        rows = index_lag.measure(orcid, log=quiet)
        ingested = [r for r in rows if r["class"] == "ingested"]
        censored = [r for r in rows if r["class"] == "not_indexed"]
        gone = [r for r in rows if r["class"] == "no_deposit"]
        lags = sorted(int(r["lag_days"]) for r in ingested)
        if lags:
            mid = lags[len(lags) // 2]
            emit("Median {} day(s) from deposit to index, over {} works"
                 .format(mid, len(lags)))
        emit("{} work(s) have not been indexed at all".format(len(censored)))
        for r in gone:
            emit("{} is on the record but the deposit will not load"
                 .format(r["doi"]))
        eligible = [r for r in rows
                    if r["zenodo_orcid"] == "yes" and r["class"] == "ingested"]
        lost = [r for r in eligible if r["openalex_orcid"] == "no"]
        if eligible:
            emit("{} of {} indexed works kept the ORCID their deposit carried"
                 .format(len(eligible) - len(lost), len(eligible)))
        return rows

    def graph(emit):
        result = wd_sweeper.sweep(orcid, log=quiet)
        emit("{} work(s) have a Wikidata item that names the author".format(
            len(result["matched"])))
        emit("{} have an item that does not name them".format(
            len(result["unattributed"])))
        emit("{} have no item".format(len(result["no_item"])))
        emit("{} item(s) are attributed to the author but absent from the "
             "record".format(len(result["stray"])))
        return {k: len(v) for k, v in result.items() if isinstance(v, list)}

    def integrity(emit):
        works = [w for w in discover.from_orcid(orcid) if w["doi"]]
        fails = warns = clean = unreadable = 0
        for w in works:
            try:
                findings = deposit_lint.lint(deposit_lint.record_for(w["doi"]))
            except Problem:
                # Counting this as a metadata failure was wrong. A record
                # that will not load has no metadata to fail: the single
                # "correction needed" this reported was a deposit returning
                # 410, which is a worse problem of an entirely different
                # kind, already named under REACHING THE INDEX.
                unreadable += 1
                continue
            f = sum(1 for x in findings if x.level == deposit_lint.FAIL)
            n = sum(1 for x in findings if x.level == deposit_lint.WARN)
            fails += bool(f)
            warns += bool(n and not f)
            clean += not (f or n)
            time.sleep(0.05)
        emit("{} deposit(s) pass every metadata check".format(clean))
        emit("{} carry a warning".format(warns))
        emit("{} have something that will cause a correction".format(fails))
        if unreadable:
            emit("{} record(s) could not be read at all, so nothing is "
                 "claimed about them".format(unreadable))
        return {"clean": clean, "warn": warns, "fail": fails,
                "unreadable": unreadable}

    def abstracts(emit):
        works = [w for w in discover.from_orcid(orcid) if w["doi"]]
        diverged = checked = 0
        for w in works:
            try:
                r = abstract_op.check(w["doi"], log=quiet, quiet=True)
            except Problem:
                continue
            if not r or not r["pairs"]:
                continue
            checked += 1
            if any(p["ratio"] < abstract_op.DIVERGENT for p in r["pairs"]):
                diverged += 1
        emit("{} work(s) have the abstract in more than one place".format(
            checked))
        emit("{} of those have copies that disagree".format(diverged))
        return {"checked": checked, "diverged": diverged}

    def links(emit):
        rows = citation_resolve.run(orcid, log=quiet)
        counts = {}
        for r in rows:
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        emit("{} outbound identifier(s) checked".format(len(rows)))
        for state in ("ok", "blocked", "redirected", "dead", "unreachable"):
            if counts.get(state):
                emit("{:<11} {}".format(state, counts[state]))
        if counts.get("dead"):
            for r in rows:
                if r["state"] == "dead":
                    emit("dead: {} (cited by {})".format(
                        r["points_at"], r["from_doi"]))
        return counts

    def retractions(emit):
        authored, cited, unchecked, refs = retraction_watch.scan(
            orcid, log=quiet)
        emit("{} cited identifier(s) checked".format(refs))
        emit("{} retracted work(s) on the record".format(len(authored)))
        emit("{} retracted work(s) cited by it".format(len(cited)))
        if unchecked:
            emit("{} identifier(s) could not be checked".format(
                len({u[0] for u in unchecked})))
        return {"authored": len(authored), "cited": len(cited)}


    def documents(emit):
        """Does the deposited file agree with the record describing it?

        Everything above reads metadata. This opens the document itself
        and compares what it says with what its record claims -- the
        title, the authors, the version, and whether the file states its
        own DOI. A record can be immaculate while the PDF under it is a
        different draft.

        Capped, and the cap is stated rather than hidden: each document
        is fetched and read, which costs seconds, and a long record would
        otherwise turn a report into a timeout.
        """
        doc = discover.discover(orcid, with_wikidata=False, log=quiet)
        dois = [w.get("doi") for w in doc["works"]
                if w.get("doi") and not w.get("unclaimed")]
        if not dois:
            emit("No work on the record carries a DOI, so there is no "
                 "document to open.")
            return {"checked": 0}

        cap = 15
        looked = dois[:cap]
        disagreed = []
        unreadable = 0
        for d in looked:
            try:
                out = pdf_conform.check(d, log=quiet, quiet=True)
            except Exception:                        # noqa: BLE001
                unreadable += 1
                continue
            # check() returns None for a record with no readable file rather
            # than raising, so the guard above does not catch it. Reading
            # .get on that None took down the whole section on the first
            # real record it met -- a check that cannot run must degrade to
            # "not checked", never to a dead section.
            if not out:
                unreadable += 1
                continue
            bad = [f for f in (out.get("findings") or [])
                   if len(f) > 1 and f[1] != "match"]
            if bad:
                disagreed.append((d, bad))

        emit("{} document(s) opened and compared with their record"
             .format(len(looked) - unreadable))
        if len(dois) > cap:
            emit("{} of {} checked; the rest were not opened"
                 .format(cap, len(dois)))
        if unreadable:
            emit("{} could not be opened, so nothing is claimed about them"
                 .format(unreadable))
        # Only claimable if something was actually opened. The first version
        # said "every document opened agrees" after opening none, which is
        # success reported by default -- the one thing the rule at the top of
        # this file forbids, written by the person who wrote the rule.
        opened = len(looked) - unreadable
        if not disagreed and opened:
            emit("Every document opened agrees with the record describing it.")
        elif not opened:
            emit("Nothing could be opened, so nothing is claimed either way.")
        for d, bad in disagreed:
            emit("{}".format(d))
            for f in bad:
                emit("   {} {}: {}".format(f[1], f[0], f[2] if len(f) > 2 else ""))
        return {"checked": len(looked), "disagreed": len(disagreed)}

    def wikidata_actions(emit):
        """Works with no Wikidata item, and the statements that would create one.

        The knowledge graph section says what is missing. This says what
        to do about it, which is a different and more useful thing to be
        handed.
        """
        batch, skipped, existing = qikstgen.generate(orcid, log=quiet, limit=25)
        emit("{} work(s) already have a Wikidata item".format(existing))
        emit("{} could have one created from what is already published"
             .format(len(batch)))
        if skipped:
            emit("{} cannot, for the reasons below".format(len(skipped)))
            for title, why in skipped[:8]:
                emit("   {}  <- {}".format((title or "?")[:44], why))
        if batch:
            emit("")
            emit("QuickStatements for the first of them, ready to paste at "
                 "quickstatements.toolforge.org:")
            for line in (batch[0][2] or [])[:12]:
                emit("   " + str(line))
        return {"existing": existing, "creatable": len(batch),
                "skipped": len(skipped)}

    checks = [
        ("IDENTITY", identity),
        ("THE RECORD", record),
        ("WHERE IT WAS PUBLISHED", venues),
        ("CITATIONS", citations),
        ("REACHING THE INDEX", timing),
        ("THE KNOWLEDGE GRAPH", graph),
        ("DEPOSIT INTEGRITY", integrity),
        ("ABSTRACTS", abstracts),
        ("OUTBOUND LINKS", links),
        ("RETRACTIONS", retractions),
        ("THE DOCUMENTS THEMSELVES", documents),
        ("WIKIDATA: WHAT COULD BE CREATED", wikidata_actions),
    ]
    for title, fn in checks:
        sections.append(run_one(title, fn, log))
    return sections


def render(orcid, sections, log=print):
    log("")
    log("  AUTHORECON REPORT")
    log("  {}".format(orcid))
    log("  generated {}".format(time.strftime("%Y-%m-%d %H:%M UTC",
                                              time.gmtime())))
    for s in sections:
        log("")
        log(RULE)
        log("  {}".format(s.title))
        log(RULE)
        if s.error:
            log("    could not run: {}".format(s.error))
            continue
        for line in s.lines:
            log("    {}".format(line))

    log("")
    log(RULE)
    log("  NOT COVERED HERE")
    log(RULE)
    log("    These need something other than an ORCID and were not run:")
    log("      pdf-conform            needs the deposited documents")
    log("      dependency-necessity   needs a dependency graph")
    log("      submission-scrub, slop-scan, software-inventory")
    log("                             need a local repository")
    log("")
    log("    Nothing above is scored or graded. Each section states what was")
    log("    found and what could not be reached; the reader draws the")
    log("    conclusion.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-report",
        description="Run every ORCID-only check and write one document.")
    ap.add_argument("orcid")
    ap.add_argument("--json", help="write the structured result here")
    args = ap.parse_args(argv)

    try:
        orcid = normalise_orcid(args.orcid)
        if not valid_checksum(orcid):
            raise Problem("{} fails its check digit".format(orcid))
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    sections = build(orcid, log=lambda m: print(m, file=sys.stderr))
    render(orcid, sections, log=print)

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({
                "orcid": orcid,
                "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sections": [{"title": s.title, "lines": s.lines,
                              "error": s.error} for s in sections],
            }, fh, indent=1, ensure_ascii=False)
        print("\n  wrote {}".format(args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
