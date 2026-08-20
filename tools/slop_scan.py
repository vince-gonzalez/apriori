#!/usr/bin/env python3
r"""Find the structural habits that make prose read as machine-written.

    python tools/slop_scan.py paper.md [more...]
    python tools/slop_scan.py --strict paper.md      # exit 1 on any hit

Exit code 1 if anything in the BLOCKING classes is found, so it can gate a
deposit or a send.

WHY THIS EXISTS
    The usual advice is to grep for a word list -- "delve", "tapestry",
    "leverage". That catches the vocabulary and misses the writing. What
    actually reads as generated is structural: the contrastive pair that
    asserts by denying its opposite, the announced honesty that tells the reader
    a sentence is candid instead of being candid, the triad that pads two real
    items to three, the paragraph that ends by restating itself.

    None of those contain a flagged word. All of them survive a word-list scan.
    So this looks for shapes.

Every hit is a location and a reason, never an automatic edit. Some are correct
in context -- a genuine contrast is a genuine contrast -- so the output is a
reading list, and the BLOCKING classes are the ones that have never once been
right in this author's drafts.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- structures

# The contrastive pair. "It is X, not Y" / "not X, but Y" / "X rather than Y"
# asserts a thing by denying its opposite, which doubles the length and adds
# nothing. Occasionally a real contrast; usually a tic.
CONTRAST = [
    (r"\b(?:is|was|are|were|be)\s+(?!not\b)[^.;:]{3,60}?,\s+not\s+[a-z]", "\"X, not Y\" contrastive pair"),
    (r"\bnot\s+(?:just|merely|simply|only)\s+[^.;:]{3,60}?,?\s+but\b", "\"not just X, but Y\" escalation"),
    (r"\bThis (?:is|was)\s+not\s+[^.]{3,70}\.\s+(?:It|This)\s+(?:is|was)\b", "antithesis across two sentences"),
    (r"\bisn't\s+(?:about\s+)?[^.;:]{3,50}?[,.]\s*(?:it'?s|its)\b", "\"isn't X, it's Y\""),
]

# Telling the reader that a sentence is honest, plain, or important, instead of
# writing it that way.
ANNOUNCED = [
    (r"\bworth (?:stating|noting|saying) plainly\b", "announced plainness (BANNED)"),
    (r"\bhonest caveat\b", "announced honesty (BANNED)"),
    (r"\bsupersedes\b", "self-correction verb (BANNED)"),
    (r"\b(?:to be (?:clear|honest|fair)|let me be clear|candidly|frankly speaking)\b", "announced candour"),
    (r"\b(?:the (?:simple|honest|plain|hard) truth is|truth be told)\b", "announced truth"),
    (r"\bit(?:'s| is) (?:important|crucial|worth) (?:to note|noting|remembering)\b", "announced importance"),
    (r"\bthat said\b|\bthat being said\b", "pivot filler"),
]

# Padding two real items to three for cadence.
TRIAD = [
    (r"\b\w+,\s+\w+,?\s+and\s+\w+\b(?=[^.]*\.)", "possible padded triad"),
]

# Vocabulary. Kept because it is cheap, not because it is the point.
LEXICAL = [
    (r"\b(?:delve|delves|delving)\b", "delve"),
    (r"\b(?:leverage[sd]?|leveraging)\b", "leverage"),
    (r"\b(?:robust|comprehensive|holistic|seamless|nuanced|myriad)\b", "brochure adjective"),
    (r"\b(?:landscape|realm|tapestry|testament|cornerstone|beacon)\b", "brochure noun"),
    (r"\b(?:underscore[sd]?|showcase[sd]?|highlight the importance)\b", "brochure verb"),
    (r"\b(?:pivotal|paramount|indispensable)\b", "inflated adjective"),
    (r"\bin (?:today'?s|the modern) [a-z ]{3,24}\b", "essay opener"),
    (r"\b(?:navigate|navigating) the\b", "navigate the X"),
    (r"\bplays? a (?:key|vital|crucial|significant) role\b", "plays a role"),
]

# Closing a paragraph by saying it again.
RESTATE = [
    (r"(?m)^\s*(?:In (?:short|summary|essence|conclusion)|Put (?:simply|differently|another way)|"
     r"To (?:sum up|summarise|summarize)|The (?:point|upshot|takeaway) (?:is|here is))\b", "restatement opener"),
]

BLOCKING = {"announced plainness (BANNED)", "announced honesty (BANNED)",
            "self-correction verb (BANNED)", "announced candour",
            "announced truth", "announced importance", "restatement opener",
            "delve", "leverage", "brochure adjective", "brochure noun",
            "brochure verb", "inflated adjective", "essay opener",
            "navigate the X", "plays a role", "pivot filler"}

GROUPS = [("contrastive", CONTRAST), ("announced", ANNOUNCED),
          ("triad", TRIAD), ("lexical", LEXICAL), ("restatement", RESTATE)]


def strip_code(text: str) -> list[tuple[int, str]]:
    """Prose lines only. Fenced blocks, tables and indented code are not prose."""
    out, fence = [], False
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence or s.startswith("|") or s.startswith("    ") or line.startswith("\t"):
            continue
        # inline code spans carry identifiers, not prose
        out.append((i, re.sub(r"`[^`]*`", "", line)))
    return out


def em_dash_report(lines):
    """Density, not presence. One is punctuation; four in a paragraph is a tic."""
    hits, para, start = [], [], None
    def flush():
        if not para:
            return
        n = sum(l.count("—") for l in para)
        words = sum(len(l.split()) for l in para)
        if n >= 3 and words and n / max(words, 1) * 100 > 1.2:
            hits.append((start, f"{n} em dashes in one paragraph ({words} words)"))
    for i, l in lines:
        if not l.strip():
            flush(); para, start = [], None
        else:
            if start is None:
                start = i
            para.append(l)
    flush()
    return hits


def scan(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = strip_code(text)
    found = []
    # Prose is hard-wrapped, so a two-clause tic is usually split across lines.
    # Scanning line by line finds none of them. Paragraphs are joined first and
    # each match is charged back to the line its match started on.
    paras, cur = [], []
    for i, line in lines:
        if line.strip():
            cur.append((i, line))
        elif cur:
            paras.append(cur); cur = []
    if cur:
        paras.append(cur)

    for group, rules in GROUPS:
        for pat, why in rules:
            rx = re.compile(pat, re.I)
            for para in paras:
                joined, offs = "", []
                for i, line in para:
                    offs.append((len(joined), i))
                    joined += line.strip() + " "
                for m in rx.finditer(joined):
                    ln = next((i for off, i in reversed(offs) if off <= m.start()),
                              para[0][0])
                    found.append((ln, group, why, re.sub(r"\s+", " ", m.group(0))[:72]))
    for i, why in em_dash_report(lines):
        found.append((i, "density", why, ""))
    found.sort()
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any hit, not only blocking ones")
    a = ap.parse_args()

    total, blocking = 0, 0
    for f in a.files:
        p = Path(f)
        hits = scan(p)
        print(f"== {p.name}: {len(hits)} flagged")
        for line, group, why, snip in hits:
            mark = "BLOCK" if why in BLOCKING else "look "
            if why in BLOCKING:
                blocking += 1
            print(f"   {mark} {line:>4}  {group:<12} {why}")
            if snip:
                print(f"              {snip}")
        total += len(hits)
        print()
    print(f"{total} flagged, {blocking} blocking")
    if blocking or (a.strict and total):
        sys.exit(1)


if __name__ == "__main__":
    main()
