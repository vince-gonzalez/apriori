#!/usr/bin/env python3
"""Refuse to let a file reach a human with agent artifacts still in it.

    python tools/submission_scrub.py paper.tex [more files...]
    python tools/submission_scrub.py --dir submission/

Exit code 1 if anything is found, so it can gate a build or a send.

WHY THIS EXISTS
    A .tex formatted with AI assistance was submitted to the Journal of Integer
    Sequences with the assistant's own instructions still in the source. The
    editor issued a one-year ban -- from submitting and from asking. The file
    read fine; nobody scrolled the comments.

    Reading a file over is not a check. This is a check.

It looks in the places prose review does not: LaTeX % comments, HTML/markdown
comments, code comments, and instruction-shaped sentences addressed to the
author rather than the reader.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Comment syntaxes, by extension. Everything inside these is read separately,
# because this is where the damage hides.
# Manuscript formats. A comment in one of these has no reader and no reason to
# exist, so every comment is reported regardless of content.
MANUSCRIPT = {
    ".tex": [r"(?<!\\)%(.*)$"],
    ".sty": [r"(?<!\\)%(.*)$"],
    ".bib": [r"(?<!\\)%(.*)$"],
    ".md": [r"<!--(.*?)-->"],
    ".html": [r"<!--(.*?)-->"],
    ".txt": [],
}
# Code deposited alongside a paper. Comments here are wanted -- a documented
# gate is the point -- so only the artifact phrases are flagged, never the mere
# presence of a comment.
CODE = {".py", ".js", ".lean", ".c", ".cpp", ".java", ".r", ".m", ".sh"}
COMMENTS = MANUSCRIPT

# Phrases that have no business in something a stranger will read. Matched
# case-insensitively anywhere in the file, comment or body.
ARTIFACTS = [
    r"\bas an ai\b", r"\bas a language model\b", r"\bI (?:can|cannot|can't) ",
    r"\bhere'?s (?:the|a|your) \b", r"\blet me know\b", r"\bfeel free to\b",
    r"\bI'?ve (?:added|updated|created|written|included|left)\b",
    r"\bnote:? you (?:should|can|may|need|must)\b",
    r"\byou (?:should|can|may|need to|must|will want to) (?:replace|delete|remove|update|fill|adjust|change|insert)\b",
    r"\breplace (?:this|the following|with your)\b",
    r"\bfill in (?:your|the)\b", r"\binsert (?:your|the) \b",
    r"\b(?:TODO|FIXME|XXX|PLACEHOLDER)\b",
    r"\[(?:INSERT|YOUR|TODO|PLACEHOLDER)[^\]]*\]",
    r"\bLorem ipsum\b",
    r"\bchatgpt\b", r"\bclaude\b", r"\bcopilot\b", r"\bgpt-?[0-9]\b",
    r"\bprompt\b\s*:", r"\bassistant\b\s*:",
    r"\bmake sure to\b", r"\bdon'?t forget to\b", r"\bremember to\b",
    r"\bif you want\b.*\bI (?:can|could)\b",
]
ARTIFACT_RE = [re.compile(p, re.I) for p in ARTIFACTS]


def scan(path: Path):
    """Return [(line_no, where, text)] for everything suspicious."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [(0, "unreadable", str(e))]
    lines = text.splitlines()
    hits = []

    # 1. every comment, reported in full -- a comment in a submission is
    #    suspicious even when it says nothing incriminating
    for pat in COMMENTS.get(path.suffix.lower(), []):
        flags = re.S if "*?" in pat else 0
        for m in re.finditer(pat, text, re.M | flags):
            body = (m.group(1) or "").strip()
            if not body or len(body) < 12:
                continue
            ln = text[:m.start()].count("\n") + 1
            hits.append((ln, "comment", body[:110]))

    # 2. instruction-shaped text anywhere at all
    for i, line in enumerate(lines, 1):
        for rx in ARTIFACT_RE:
            if rx.search(line):
                hits.append((i, f"phrase /{rx.pattern[:26]}/", line.strip()[:110]))
                break
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir")
    ap.add_argument("--code", action="store_true",
                    help="also scan source files for artifact phrases")
    a = ap.parse_args()

    paths = [Path(f) for f in a.files]
    if a.dir:
        want = set(MANUSCRIPT) | (CODE if a.code else set())
        paths += [p for p in Path(a.dir).rglob("*")
                  if p.is_file() and p.suffix.lower() in want]
    if not paths:
        sys.exit("nothing to scan")

    total = 0
    for p in paths:
        hits = scan(p)
        if not hits:
            print(f"  clean   {p}")
            continue
        total += len(hits)
        print(f"  FLAGGED {p}  ({len(hits)})")
        for ln, where, txt in hits[:24]:
            print(f"     line {ln:>4}  {where:<30} {txt}")
        if len(hits) > 24:
            print(f"     ... {len(hits) - 24} more")

    print()
    if total:
        print(f"{total} finding(s). Nothing here goes to an editor until this "
              f"reads clean.")
        print("Comments are flagged even when harmless: a submission has no "
              "reason to carry any.")
        sys.exit(1)
    print("clean — no agent artifacts, no stray comments.")


if __name__ == "__main__":
    main()
