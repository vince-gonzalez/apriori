#!/usr/bin/env python3
r"""Refuse to deposit something that is already on Zenodo.

    python tools/zenodo_precheck.py "Which Axiom Seams Yield"
    python tools/zenodo_precheck.py --file papers/DRAFT.md
    python tools/zenodo_precheck.py --all-drafts papers/

Exit code 1 if a likely match exists, so it can gate a deposit script.

WHY THIS EXISTS
    On 2026-08-20 two papers were about to be deposited a second time. Both were
    already published -- 10.5281/zenodo.21883964 and 10.5281/zenodo.21951050 --
    and both were recorded locally as "written, not deposited". The local record
    was the only thing consulted, and the local record was wrong. Editing the
    source of a live deposit was one step away.

    A note in a file is not a check. The API is the check.

Two searches, because they fail differently. The account's own depositions catch
the case above, including unpublished drafts that no public search can see. The
public record search catches someone else having deposited the same title, which
matters before claiming novelty.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://zenodo.org/api"


def norm(s: str) -> str:
    """Compare on words, so punctuation and case do not hide a match."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split())


def similarity(a: str, b: str) -> float:
    """Sequence ratio, floored by containment.

    A draft is routinely titled with the short name while the deposit carries a
    long subtitle -- "Where Formal Libraries Spend Their Axioms" against
    "Where Formal Libraries Spend Their Axioms: A Cross-Foundation Measurement,
    and an Avoidable Classical Dependency in Lean's omega". Sequence ratio reads
    those as 0.55 and the duplicate goes through. Whenever one title opens the
    other, that is a match regardless of how much subtitle follows.
    """
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if a and b:
        short, long = sorted((a, b), key=len)
        if long.startswith(short) or short in long:
            # a contained title is at least as strong as the threshold allows
            ratio = max(ratio, 0.95 if long.startswith(short) else 0.85)
    return ratio


def get(path: str, **params):
    tok = os.environ.get("ZENODO_TOKEN")
    if tok:
        params["access_token"] = tok
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"   ! HTTP {e.code} on {path}", file=sys.stderr)
        return []


def own_depositions():
    if not os.environ.get("ZENODO_TOKEN"):
        return None
    out, page = [], 1
    while page <= 8:
        d = get("/deposit/depositions", size=50, page=page, sort="mostrecent")
        if not isinstance(d, list) or not d:
            break
        out += d
        if len(d) < 50:
            break
        page += 1
    return out


def title_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def check(title: str, mine, threshold: float):
    t = norm(title)
    hits = []

    if mine is None:
        print("   ! ZENODO_TOKEN not set — own drafts and unpublished records "
              "cannot be seen; this check is incomplete")
    else:
        for r in mine:
            other = norm((r.get("metadata") or {}).get("title", ""))
            if not other:
                continue
            ratio = similarity(t, other)
            if ratio >= threshold:
                hits.append(("yours", ratio, r["id"], r.get("state"),
                             (r.get("metadata") or {}).get("doi") or
                             r.get("doi") or "(unpublished)",
                             (r.get("metadata") or {}).get("title", "")))

    pub = get("/records", q=f'title:"{title}"', size=5)
    for r in (pub.get("hits", {}).get("hits", []) if isinstance(pub, dict) else []):
        other = norm(r.get("metadata", {}).get("title", ""))
        ratio = similarity(t, other)
        if ratio >= threshold and not any(h[2] == r["id"] for h in hits):
            hits.append(("public", ratio, r["id"], "published",
                         r.get("doi", ""), r["metadata"].get("title", "")))
    hits.sort(key=lambda h: -h[1])
    return hits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("titles", nargs="*")
    ap.add_argument("--file", action="append", default=[],
                    help="read the title from a markdown file's first heading")
    ap.add_argument("--all-drafts", help="every .md in this directory")
    ap.add_argument("--threshold", type=float, default=0.72)
    a = ap.parse_args()

    titles = list(a.titles)
    for f in a.file:
        titles.append(title_of(Path(f)))
    if a.all_drafts:
        for p in sorted(Path(a.all_drafts).glob("*.md")):
            titles.append(title_of(p))
    if not titles:
        ap.error("give a title, --file, or --all-drafts")

    mine = own_depositions()
    if mine is not None:
        print(f"checking against {len(mine)} of your depositions "
              f"(drafts included) and the public record\n")

    blocked = 0
    for title in titles:
        hits = check(title, mine, a.threshold)
        if not hits:
            print(f"  clear   {title[:66]}")
            continue
        blocked += 1
        print(f"  MATCH   {title[:66]}")
        for where, ratio, rid, state, doi, other in hits[:4]:
            print(f"          {ratio:.0%} {where:<7} id={rid} {state:<12} {doi}")
            print(f"               {other[:72]}")
    print()
    if blocked:
        print(f"{blocked} of {len(titles)} already exist on Zenodo — do not deposit these")
        sys.exit(1)
    print(f"all {len(titles)} clear")


if __name__ == "__main__":
    main()
