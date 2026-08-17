#!/usr/bin/env python3
"""Where does set.mm actually spend the axiom of choice?

    python tools/setmm_necessity.py [path/to/closure.pkl]

The dominator question, asked of Metamath instead of Lean: of the theorems
whose proofs reach the axiom of choice, how many reach it through a single
step, and which step is it?

A theorem that reaches choice through exactly one of its direct references has
one place to attack. If that reference turns out to be provable without choice,
or replaceable by a choice-free variant already in the library, every theorem
routing through it comes free. Those are the necessity candidates -- not proof
that choice is unnecessary, but the shortlist worth checking by hand.

Unlike the Lean side, there is no gap between the object analysed and the
object submitted: a Metamath proof is the artifact.
"""
from __future__ import annotations

import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT = Path(r"C:\Users\Admin\OneDrive\Desktop\universal-cover\axioms\closure.pkl")
path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
d = pickle.loads(path.read_bytes())
clos, refs, kind = d["clos"], d["refs"], d["kind"]
full = set(d["full"])

# Which labels are the choice axioms? Not "in every full closure" -- set.mm has
# two of them (ax-ac and ax-ac2) and no theorem needs both. The test that works
# is the converse: an axiom whose users are all inside `full` and nowhere else.
users = defaultdict(set)
for t, c in clos.items():
    for ax in c:
        users[ax].add(t)
choice_axioms = sorted(ax for ax, who in users.items()
                       if who and who <= full and ax.startswith("ax-"))
print(f"choice axioms identified from the data: {choice_axioms}")
print(f"theorems reaching choice: {len(full):,} of {len(clos):,} "
      f"({len(full) / len(clos):.2%})")

# Direct spenders: reference a choice axiom in their own proof step list.
spenders = sorted(t for t in full
                  if any(r in choice_axioms for r in refs.get(t, [])))
print(f"direct spenders (cite a choice axiom themselves): {len(spenders)}")
print(f"   {', '.join(spenders[:14])}{' …' if len(spenders) > 14 else ''}")

# For everyone else, which of their direct references carry the dependence?
single, multi = {}, 0
for t in full:
    if t in spenders:
        continue
    carriers = [r for r in refs.get(t, []) if r in full or r in choice_axioms]
    carriers = sorted(set(carriers))
    if len(carriers) == 1:
        single[t] = carriers[0]
    elif len(carriers) > 1:
        multi += 1

print()
print(f"reach choice through EXACTLY ONE step : {len(single):,}")
print(f"reach it through several              : {multi:,}")

gate = Counter(single.values())
print()
print("gateways, by how many theorems route through them alone:")
print(f"  {'gateway':<16}{'kind':<8}{'sole route for':>15}   what it is")
for lab, n in gate.most_common(15):
    k = {"a": "axiom", "p": "theorem", "f": "float", "e": "essential"}.get(
        kind.get(lab, "?"), kind.get(lab, "?"))
    print(f"  {lab:<16}{k:<8}{n:>15}")

print()
print("The shortlist: gateways that are themselves single-gateway, i.e. the")
print("dependence enters the library at one point and fans out from there.")
chain = [(lab, n) for lab, n in gate.most_common() if lab in single]
for lab, n in chain[:12]:
    print(f"  {lab:<16} routes {n:>4} theorems, and itself reaches choice "
          f"only via {single[lab]}")
if not chain:
    print("  (none — every gateway is either a direct spender or "
          "multiply-routed)")

covered = sum(gate.values())
print()
print(f"{covered:,} of the {len(full):,} choice-reaching theorems hang off a "
      f"single step.")
print(f"The top {min(5, len(gate))} gateways account for "
      f"{sum(n for _, n in gate.most_common(5)):,} of them.")
