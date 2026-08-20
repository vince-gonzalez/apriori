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

TITLES ARE NOT ENOUGH
    A second failure, the same day the first was fixed. A repository was deposited
    as software on the argument that four papers "rest on computation nobody can
    inspect". Three of those four papers ship a source archive as an attached
    file. The title check reported clear, correctly and uselessly: nothing shared
    the title, and the content was already published three times over.

    A title check answers "has this name been used". It cannot answer "has this
    content been deposited", and the second question is the one that matters for
    software. --software answers it: for every related record, list the attached
    files, look inside any archive among them, and compare that against what the
    candidate repository actually tracks.
"""
from __future__ import annotations

import argparse
import difflib
import io
import subprocess
import zipfile
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://zenodo.org/api"
MAX_ARCHIVE = 64 * 1024 * 1024   # do not pull a dataset to read its file list


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


def record_files(rid: str):
    """Attached files of a published record, archives expanded one level.

    An archive attached to a paper is the usual way source is published
    alongside it, so its contents are what a candidate deposit has to be
    compared against -- not the archive's name.
    """
    rid = str(rid).rsplit(".", 1)[-1]
    d = get(f"/records/{rid}")
    if not isinstance(d, dict) or "files" not in d:
        return None, []
    title = d.get("metadata", {}).get("title", "")
    out = []
    for f in d["files"]:
        key = f["key"]
        out.append(key)
        if key.lower().endswith((".zip",)) and f.get("size", 0) <= MAX_ARCHIVE:
            try:
                raw = urllib.request.urlopen(f["links"]["self"], timeout=120).read()
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    out += [f"{key}::{n}" for n in z.namelist() if not n.endswith("/")]
            except Exception as e:
                out.append(f"{key}::<unreadable: {e}>")
    return title, out


def repo_files(root: Path):
    """What the candidate actually tracks, or every file if it is not a repo."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        pass
    return [str(p.relative_to(root)).replace("\\", "/")
            for p in root.rglob("*") if p.is_file()]


def basenames(paths):
    return {Path(p.split("::")[-1]).name for p in paths if p and not p.endswith("/")}


def software_check(repo: Path, related, threshold: float):
    mine = basenames(repo_files(repo))
    mine = {n for n in mine if n.lower().endswith((".py", ".lean", ".mm", ".java", ".c", ".rs"))}
    print(f"candidate {repo.name or repo.resolve().name}: "
          f"{len(mine)} source files tracked\n")
    # The union across every related record is the number that matters. Scoring
    # against the worst single record is what let a duplicate through: the
    # candidate's source was spread over three papers at 22%, 7% and 7%, none of
    # them alarming alone, and together most of what was being deposited again.
    already = set()
    for doi in related:
        title, files = record_files(doi)
        if title is None:
            print(f"  ?       {doi} — could not read")
            continue
        theirs = basenames(files)
        theirs = {n for n in theirs if n.lower().endswith((".py", ".lean", ".mm", ".java", ".c", ".rs"))}
        shared = mine & theirs
        already |= shared
        cover = len(shared) / len(mine) if mine else 0.0
        mark = "OVERLAP" if cover >= threshold else "ok     "
        print(f"  {mark} {doi}")
        print(f"          {title[:70]}")
        print(f"          attached: {len([f for f in files if '::' not in f])} file(s), "
              f"{len(theirs)} source file(s) inside")
        if shared:
            sample = sorted(shared)[:6]
            print(f"          {len(shared)} of your {len(mine)} already published here "
                  f"({cover:.0%}): {', '.join(sample)}"
                  + (f" +{len(shared)-6} more" if len(shared) > 6 else ""))

    union = len(already) / len(mine) if mine else 0.0
    print(f"\n  UNION across all related records: {len(already)} of {len(mine)} "
          f"source files already published ({union:.0%})")
    if already:
        fresh = sorted(mine - already)
        print(f"  genuinely new here: {len(fresh)}"
              + (f" — {', '.join(fresh[:8])}" + (" …" if len(fresh) > 8 else "")
                 if fresh else " — nothing"))
    return union


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
    ap.add_argument("--software", metavar="REPO",
                    help="a repository about to be deposited as software; its "
                         "tracked source files are compared against the files "
                         "already attached to every --related record")
    ap.add_argument("--related", nargs="*", default=[], metavar="DOI",
                    help="records this deposit would claim to supplement")
    ap.add_argument("--overlap", type=float, default=0.30,
                    help="fraction of the candidate's source already published "
                         "elsewhere that counts as a duplicate (default 0.30)")
    a = ap.parse_args()

    if a.software:
        repo = Path(a.software)
        if not repo.exists():
            ap.error(f"{repo} does not exist")
        related = list(a.related)
        if not related:
            zj = repo / ".zenodo.json"
            if zj.exists():
                meta = json.loads(zj.read_text(encoding="utf-8"))
                related = [r["identifier"] for r in meta.get("related_identifiers", [])
                           if r.get("scheme") == "doi"]
                print(f"(took {len(related)} related DOIs from {zj.name})\n")
        if not related:
            ap.error("--software needs --related, or a .zenodo.json naming related DOIs")
        union = software_check(repo, related, a.overlap)
        print()
        if union >= a.overlap:
            print(f"{union:.0%} of this repository's source is already published "
                  f"across the related records — DO NOT DEPOSIT")
            sys.exit(1)
        print(f"{union:.0%} already published — clear to deposit")
        return

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
