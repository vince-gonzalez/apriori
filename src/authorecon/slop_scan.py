#!/usr/bin/env python3
r"""Find the structural habits that make prose read as machine-written.

    slop-scan paper.md
    slop-scan --profile doc README.md
    slop-scan --profile message comment.txt
    slop-scan --only contrastive,announced draft.md
    slop-scan --json paper.md
    slop-scan --list-rules

Exit code 1 if anything in the profile's blocking classes is found, so it can
gate a deposit or a send.

WHAT IT IS AND IS NOT
    It does not detect AI. Nothing does. It is a lint for a specific, short list
    of habits, and anything written deliberately walks straight past it. A
    seatbelt, not a polygraph.

    The usual advice is to grep for a word list -- `delve`, `tapestry`,
    `leverage`. That catches the vocabulary and misses the writing. What reads
    as generated is structural: the contrastive pair that asserts a thing by
    denying its opposite, the announced candour that tells the reader a sentence
    is honest instead of being honest, the triad padded from two real items to
    three, the paragraph that ends by restating itself. None of those contain a
    flagged word. So this looks for shapes.

USE AND MENTION
    A document that names a habit is not committing it. A README listing
    `delve` as an example of what the tool catches was flagged by an earlier
    version, and the workaround was to wrap every example in backticks. Words
    inside quotation marks or backticks are now read as mentioned rather than
    used, and skipped -- which is what the distinction is for.

PROFILES
    paper    everything, everything blocking. The default.
    doc      README and package prose. Lexical hits are advisory, because
             documentation names things for a living.
    message  a PR comment, a mailing-list post, an email. First person and
             contractions are normal; only the structural tics block.
    all      every rule, every class blocking, nothing suppressed.

SUPPRESSION
    A line carrying `slop-scan: ignore` is skipped. A file carrying
    `slop-scan: ignore-file` anywhere is skipped entirely. Use it for a
    deliberate contrast, and expect to justify it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- structures

# The contrastive pair. "It is X, not Y" / "not X, but Y" asserts a thing by
# denying its opposite, which doubles the length and adds nothing. Occasionally
# a real contrast; usually a tic.
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

GROUPS = {"contrastive": CONTRAST, "announced": ANNOUNCED, "triad": TRIAD,
          "lexical": LEXICAL, "restatement": RESTATE}

# Classes that have never once been right in this author's drafts.
ALWAYS_BLOCK = {
    "announced plainness (BANNED)", "announced honesty (BANNED)",
    "self-correction verb (BANNED)", "announced candour", "announced truth",
    "announced importance", "pivot filler", "restatement opener",
}
LEXICAL_BLOCK = {
    "delve", "leverage", "brochure adjective", "brochure noun", "brochure verb",
    "inflated adjective", "essay opener", "navigate the X", "plays a role",
}

PROFILES = {
    # everything, everything blocking
    "paper": dict(groups=set(GROUPS) | {"density"},
                  blocking=ALWAYS_BLOCK | LEXICAL_BLOCK),
    # documentation names things for a living, so vocabulary is advisory
    "doc": dict(groups=set(GROUPS) | {"density"}, blocking=ALWAYS_BLOCK),
    # a comment or a post: first person and contractions are normal
    "message": dict(groups={"contrastive", "announced", "restatement"},
                    blocking=ALWAYS_BLOCK),
    "all": dict(groups=set(GROUPS) | {"density"},
                blocking=ALWAYS_BLOCK | LEXICAL_BLOCK | {
                    "\"X, not Y\" contrastive pair",
                    "\"not just X, but Y\" escalation",
                    "antithesis across two sentences", "\"isn't X, it's Y\"",
                    "possible padded triad"}),
}

IGNORE_LINE = re.compile(r"slop-scan:\s*ignore\b(?!-file)")
IGNORE_FILE = re.compile(r"slop-scan:\s*ignore-file\b")
# a run inside quotes or backticks is being named, not used
MENTIONED = re.compile(r"`[^`]*`|\"[^\"]{1,80}\"|'[^']{1,80}'|“[^”]{1,80}”")


def strip_code(text: str) -> list[tuple[int, str]]:
    """Prose lines only, with mentioned runs blanked.

    Fenced blocks, tables and indented code are not prose. Inline code spans and
    quoted runs are blanked rather than removed, so a match cannot straddle the
    hole and offsets stay put.
    """
    out, fence = [], False
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence or s.startswith("|") or s.startswith("    ") or line.startswith("\t"):
            continue
        if IGNORE_LINE.search(line):
            continue
        out.append((i, MENTIONED.sub(lambda m: " " * (m.end() - m.start()), line)))
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
            flush()
            para, start = [], None
        else:
            if start is None:
                start = i
            para.append(l)
    flush()
    return hits


def scan(path: Path, groups: set[str]):
    text = path.read_text(encoding="utf-8", errors="replace")
    if IGNORE_FILE.search(text):
        return None
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
            paras.append(cur)
            cur = []
    if cur:
        paras.append(cur)

    for group, rules in GROUPS.items():
        if group not in groups:
            continue
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
                    found.append((ln, group, why,
                                  re.sub(r"\s+", " ", m.group(0))[:72]))
    if "density" in groups:
        for i, why in em_dash_report(lines):
            found.append((i, "density", why, ""))
    found.sort()
    return found


def list_rules() -> None:
    for group, rules in GROUPS.items():
        print(f"{group}")
        for _pat, why in rules:
            mark = "block" if why in (ALWAYS_BLOCK | LEXICAL_BLOCK) else "look "
            print(f"   {mark}  {why}")
    print("density\n   look   em dashes per paragraph")
    print("\nprofiles")
    for name, cfg in PROFILES.items():
        print(f"   {name:<8} groups: {','.join(sorted(cfg['groups']))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="paper",
                    help="rule set for the kind of document (default: paper)")
    ap.add_argument("--only", metavar="GROUPS",
                    help="comma-separated groups to run, overriding the profile")
    ap.add_argument("--ignore", metavar="GROUPS",
                    help="comma-separated groups to drop from the profile")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on any hit, not only blocking ones")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--list-rules", action="store_true",
                    help="print every rule and profile, then exit")
    a = ap.parse_args()

    if a.list_rules:
        list_rules()
        return
    if not a.files:
        ap.error("give at least one file, or --list-rules")

    cfg = PROFILES[a.profile]
    groups = set(cfg["groups"])
    if a.only:
        groups = {g.strip() for g in a.only.split(",") if g.strip()}
    if a.ignore:
        groups -= {g.strip() for g in a.ignore.split(",") if g.strip()}
    unknown = groups - (set(GROUPS) | {"density"})
    if unknown:
        ap.error(f"unknown group(s): {', '.join(sorted(unknown))}")
    blocking = cfg["blocking"]

    report, total, blocked = [], 0, 0
    for f in a.files:
        p = Path(f)
        hits = scan(p, groups)
        if hits is None:
            if not a.json:
                print(f"== {p.name}: skipped (slop-scan: ignore-file)\n")
            continue
        rows = [dict(file=str(p), line=ln, group=g, rule=why,
                     blocking=why in blocking, text=snip)
                for ln, g, why, snip in hits]
        report += rows
        total += len(rows)
        blocked += sum(1 for r in rows if r["blocking"])
        if a.json:
            continue
        print(f"== {p.name}: {len(rows)} flagged  [{a.profile}]")
        for r in rows:
            print(f"   {'BLOCK' if r['blocking'] else 'look '} {r['line']:>4}  "
                  f"{r['group']:<12} {r['rule']}")
            if r["text"]:
                print(f"              {r['text']}")
        print()

    if a.json:
        print(json.dumps(dict(profile=a.profile, groups=sorted(groups),
                              total=total, blocking=blocked, findings=report),
                         indent=1))
    else:
        print(f"{total} flagged, {blocked} blocking  [{a.profile}]")
    if blocked or (a.strict and total):
        sys.exit(1)


if __name__ == "__main__":
    main()
