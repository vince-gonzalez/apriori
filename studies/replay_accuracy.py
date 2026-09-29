#!/usr/bin/env python3
"""
============================================================
Replay a saved accuracy run against the current code
F-Keys | www.f-keys.com
------------------------------------------------------------
reference_accuracy.py draws a fresh sample from Crossref each
time, so two runs on different days measure two different sets
of references. That cannot say whether a change to the matcher
helped. This takes the exact pairs a saved run used and checks
them again with the code as it is now, then prints both tallies
side by side and every reference whose verdict changed.

The saved run is re-scored with the current scoring rules
before it is compared, so a change in how outcomes are counted
is not mistaken for a change in how references are matched.

  python studies/replay_accuracy.py studies/reference_accuracy_run2.json \
      --json studies/replay_<date>.json

Run from the repository root, so the code under src/ is what is
tested. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, "src")

import reference_accuracy as study                     # noqa: E402
from authorecon import reference_check as rc           # noqa: E402

JUDGED_ELSEWHERE = (rc.UNCHECKED, rc.UNTITLED, rc.OTHER_SCRIPT)
ORDER = ("correct", "alias", "wrong", "missed",
         rc.UNTITLED, rc.UNCHECKED, rc.OTHER_SCRIPT)


def rescore(row):
    """The verdict the current rules give a saved row."""
    if row["state"] in JUDGED_ELSEWHERE:
        return row["state"]
    if row["state"] == rc.UNLOCATABLE:
        return "missed"
    if row.get("found") == row["truth"]:
        return "correct"
    return row.get("verdict") if row.get("verdict") in ("alias", "wrong") \
        else "wrong"


def tally(rows, key):
    out = {}
    for r in rows:
        out[key(r)] = out.get(key(r), 0) + 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("saved")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    saved = json.load(open(args.saved, encoding="utf-8"))["rows"]
    pairs = [{"ref": r["ref"], "truth": r["truth"],
              "cited_by": r.get("cited_by")} for r in saved]
    log = lambda m: print(m, flush=True)             # noqa: E731
    log("replaying {} references from {}".format(len(pairs), args.saved))
    now = study.run(pairs, log)

    before = tally(saved, rescore)
    after = tally(now, lambda r: r["verdict"])
    n = len(pairs)
    log("")
    log("  {:<14}{:>8}{:>8}{:>8}".format("verdict", "before", "after", "change"))
    for k in ORDER:
        b, a = before.get(k, 0), after.get(k, 0)
        if b or a:
            log("  {:<14}{:>8}{:>8}{:>+8}".format(k, b, a, a - b))
    log("  {:<14}{:>7.1f}%{:>7.1f}%".format(
        "found right", 100.0 * (before.get("correct", 0) + before.get("alias", 0)) / n,
        100.0 * (after.get("correct", 0) + after.get("alias", 0)) / n))

    changed = [(s, t) for s, t in zip(saved, now) if rescore(s) != t["verdict"]]
    log("")
    log("  {} reference(s) changed verdict".format(len(changed)))
    for s, t in changed:
        log("    {} -> {}   {}".format(rescore(s), t["verdict"], s["ref"][:90]))
        log("         truth {}  was {}  now {}".format(
            s["truth"], s.get("found") or "-", t.get("found") or "-"))

    if args.json:
        json.dump({"replayed": args.saved, "before": before, "after": after,
                   "rows": now}, open(args.json, "w", encoding="utf-8"),
                  indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
