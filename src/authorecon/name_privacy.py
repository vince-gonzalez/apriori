#!/usr/bin/env python3
"""
============================================================
authorecon.name_privacy — the rule about names a person has
                          left behind
F-Keys | www.f-keys.com
------------------------------------------------------------
THE RULE

  A name a person no longer uses is counted, never printed.

Everything below is how that is enforced and why it is worth
enforcing at the cost of a true finding.

WHY THIS MODULE EXISTS

Reconciling a published record means gathering every form of a
name that any index has ever filed the work under. Doing that
well surfaces names people have deliberately left behind: a
name changed on transition, on marriage or divorce, on
religious conversion, on emigration, on leaving an abusive
household, or on any of the ordinary reasons a person stops
being called what they used to be called.

Scholarly publishers spent years building processes to change
a name on published work quietly and without a correction
notice, precisely so that a bibliography cannot out its
author. A tool that reconciles the record and reports "three
works under a former surname" undoes that work automatically,
at scale, and delivers the result to the person deciding
whether to publish them.

That is the single finding this package could produce that is
capable of harming somebody. It is worth giving up.

WHAT IS LOST, AND WHY IT IS AFFORDABLE

The finding an editor legitimately needs is that the record is
FRAGMENTED - that a count of this author's work is a count of
one piece of it. That finding survives intact as a number:

  "3 works are filed under a different form of this author's
   name, so any per-author total is short by that many."

The number is what makes it actionable. The name adds nothing
an editor can act on and everything a person can be hurt by.

WHAT COUNTS AS A VARIANT

A differing surname. "J. Smith" and "John Smith" are one name
written two ways, and abbreviating a given name is not a
disclosure. A different family name is the sensitive case and
the only one this treats as one.

THE ONE WAY A NAME MAY BE SHOWN

To the person whose name it is, after they have proved it is
theirs by signing in with the identifier the record hangs on.
Nothing in this package can do that today, so nothing in this
package prints one.

  from .name_privacy import redact, fragmentation

  rows = redact(rows)                # before anything leaves
  line = fragmentation(rows, name)   # the finding that stays

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import re
import unicodedata

#: Written on any row whose name has been withheld, so that a reader of the
#: data sees a decision rather than a gap.
WITHHELD = "[name withheld: see name_privacy]"

#: Particles that belong to a surname rather than ending it, so that
#: "van der Waals" is compared as a surname and not as "waals".
PARTICLES = {"van", "von", "de", "del", "della", "di", "da", "dos", "du",
             "la", "le", "el", "al", "bin", "ibn", "ben", "mac", "mc",
             "st", "saint", "ter", "ten", "op"}


#: Letters that are routinely written two ways in the same person's name.
#: A German passport spells it Müller and an American index spells it
#: Mueller, and reporting those as two people would be the rule accusing
#: somebody of a name change they never made.
EXPANSIONS = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "æ": "ae", "ø": "oe", "œ": "oe", "å": "aa",
}


def fold(text):
    """
    Compare names without case, accents, punctuation or writing system
    standing in for a difference.

    Written as [^a-z\\s] this returned an empty string for every name in
    Cyrillic, Chinese or Arabic, so the rule about former names never fired
    for any of them - the people it protects least being the ones an index
    is most likely to have filed twice.
    """
    if not text:
        return ""
    flat = str(text).lower()
    for char, spelled in EXPANSIONS.items():
        flat = flat.replace(char, spelled)
    flat = unicodedata.normalize("NFKD", flat)
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    kept = "".join(c if (c.isalpha() or c.isspace()) else " " for c in flat)
    return re.sub(r"\s+", " ", kept).strip()


def surname(name):
    """
    The family name, as well as it can be told from a display string.

    Indexes store "Family, Given" and "Given Family" and both appear in the
    same result set, so both are read rather than one being assumed.
    """
    flat = fold(name)
    if not flat:
        return ""
    if "," in str(name):
        return re.sub(r"\s+", " ", fold(str(name).split(",")[0])).strip()

    # Chinese, Japanese and Korean names written in their own characters put
    # the family name first and use no spaces, so neither the last token nor
    # the whole string is the surname.
    if any("㐀" <= c <= "鿿" for c in flat):
        return flat.replace(" ", "")[:1]

    parts = [p for p in flat.split() if p]
    if not parts:
        return ""

    # Initials are not part of the name being compared. Dropping them first
    # is what makes "Каминский Ю.В." and "Каминский Ю." one person: Russian
    # writes the surname first, so taking the last token took an initial.
    named = [p for p in parts if len(p) > 1]
    if len(named) == 1:
        return named[0]
    if named:
        parts = named

    # Walk back over any particles so a compound surname stays whole.
    i = len(parts) - 1
    while i > 0 and parts[i - 1] in PARTICLES:
        i -= 1
    return " ".join(parts[i:])


def is_variant(candidate, current):
    """
    Is this a different name, rather than the same one written differently?

    Only a differing family name counts. Initialising a given name is a
    house style, not a disclosure, and treating it as one would withhold
    almost every record for no benefit.
    """
    a, b = surname(candidate), surname(current)
    if not a or not b:
        return False
    return a != b


def redact(rows, key="name"):
    """
    Remove every name from rows on their way out of the process.

    Applied to anything written to a file, returned over a network or shown
    to somebody who is not the subject. The rows keep their shape so that
    callers do not have to know this happened.
    """
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or key not in row:
            out.append(row)
            continue
        copy = dict(row)
        copy[key] = WITHHELD
        out.append(copy)
    return out


def count_variants(rows, current, key="name", works_key="works"):
    """(records, works) filed under some other form of this author's name."""
    hits = [r for r in (rows or [])
            if isinstance(r, dict) and is_variant(r.get(key), current)]
    return len(hits), sum(int(r.get(works_key) or 0) for r in hits)


def fragmentation(rows, current, key="name", works_key="works"):
    """
    The finding that survives the rule: the record is in pieces, and by how
    much. Returns None when there is nothing to say.
    """
    records, works = count_variants(rows, current, key, works_key)
    if not records:
        return None
    return ("{} index record(s) file this author's work under a different "
            "form of their name, covering {} work(s). Any per-author total "
            "is short by that much. The other form is not shown."
            .format(records, works))
