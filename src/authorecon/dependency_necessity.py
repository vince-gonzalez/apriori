#!/usr/bin/env python3
"""
============================================================
authorecon.dependency_necessity — which single edge is
                                  holding all of this up?
F-Keys | www.f-keys.com
------------------------------------------------------------
THE QUESTION

Of everything that depends on a thing you would rather not
depend on, how much reaches it through exactly one step, and
which step is it?

That number matters because it is where effort pays. A node
that reaches the target through one of its own references has
a single place to attack: if that reference turns out to be
replaceable, everything routing through it comes free at once.
A node that reaches the target through four independent paths
has to be rewritten.

Generalised from a study of where a formal library spends the
axiom of choice, where the answer was that three lemmas
carried the dependence for 208 of 546 theorems. Nothing in the
method is about proofs - it is a question about any dependency
graph, and build systems and package trees have exactly the
same shape.

  authorecon-dependency-necessity graph.tsv --target ax-ac
  authorecon-dependency-necessity graph.json --target choice --top 20

INPUT

A plain edge list, either

  TSV    one "node<TAB>dependency" per line
  JSON   {"node": ["dependency", ...], ...}

Deliberately not a pickle. The prototype this generalises read
one, and unpickling a file is running whatever is in it - fine
for a file you produced, wrong for a tool other people run on
data they were sent.

WHAT IT REPORTS

  reach     nodes whose dependencies eventually include the target
  direct    nodes naming the target in their own edges
  single    nodes reaching it through exactly one of their
            references - the tractable ones
  carriers  those single references, ranked by how many nodes
            each one is holding up

No dependencies. Standard library only.
============================================================
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys


class Problem(Exception):
    pass


def load_graph(path):
    """node -> list of direct dependencies."""
    if not os.path.exists(path):
        raise Problem("No such file: {}".format(path))
    text = open(path, encoding="utf-8").read()
    if path.lower().endswith(".json"):
        try:
            raw = json.loads(text)
        except ValueError as err:
            raise Problem("That JSON did not parse: {}".format(err))
        if not isinstance(raw, dict):
            raise Problem('Expected {"node": ["dep", ...]}')
        return {k: list(v) for k, v in raw.items()}

    graph = collections.defaultdict(list)
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) < 2:
            raise Problem(
                "Line {} is not an edge: {!r}. Expected "
                "node<TAB>dependency.".format(n, line[:60]))
        graph[parts[0]].append(parts[1])
    return dict(graph)


def reaches(graph, targets):
    """
    Every node whose transitive dependencies include a target.

    Iterative rather than recursive: a real dependency graph is deeper than
    the interpreter's stack, and a tool that dies on a large input is not a
    tool for large inputs.
    """
    targets = set(targets)
    dependents = collections.defaultdict(set)
    for node, deps in graph.items():
        for dep in deps:
            dependents[dep].add(node)

    hit, queue = set(), list(targets)
    while queue:
        current = queue.pop()
        for parent in dependents.get(current, ()):
            if parent not in hit:
                hit.add(parent)
                queue.append(parent)
    return hit


def analyse(graph, targets):
    targets = set(targets)
    known = set(graph) | {d for deps in graph.values() for d in deps}
    missing = targets - known
    if missing:
        raise Problem(
            "The graph never mentions: {}".format(", ".join(sorted(missing))))

    hit = reaches(graph, targets)
    direct = {n for n in hit if targets & set(graph.get(n, ()))}

    single, multi = {}, []
    for node in hit - direct:
        carriers = sorted({d for d in graph.get(node, ())
                           if d in hit or d in targets})
        if len(carriers) == 1:
            single[node] = carriers[0]
        elif len(carriers) > 1:
            multi.append(node)

    load = collections.Counter(single.values())
    return {
        "total": len(graph),
        "reach": hit,
        "direct": direct,
        "single": single,
        "multi": multi,
        "carriers": load,
    }


def report(result, top=12, log=print):
    total, hit = result["total"], result["reach"]
    log("")
    log("  {} of {} nodes reach the target".format(len(hit), total))
    if total:
        log("    that is {:.1%} of the graph".format(len(hit) / total))
    log("    {:>6} name it directly".format(len(result["direct"])))
    log("    {:>6} reach it through exactly one reference".format(
        len(result["single"])))
    log("    {:>6} reach it through several".format(len(result["multi"])))

    if not result["carriers"]:
        log("")
        log("  No single carrier: everything that reaches the target does so")
        log("  directly or by more than one route, so there is no one edge")
        log("  to attack.")
        return

    log("")
    log("  CARRIERS - one reference each, holding up this many nodes")
    covered = 0
    for name, n in result["carriers"].most_common(top):
        covered += n
        log("    {:>6}  {}".format(n, name))
    log("")
    log("  The top {} carry {} of the {} single-route nodes.".format(
        min(top, len(result["carriers"])), covered, len(result["single"])))
    log("  If one of those references can be replaced, everything routing")
    log("  through it stops depending on the target at once.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="authorecon-dependency-necessity",
        description="Find the single references holding a dependency in place.")
    ap.add_argument("graph", help="a TSV or JSON edge list")
    ap.add_argument("--target", action="append", required=True,
                    help="the dependency in question; repeatable")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args(argv)

    try:
        graph = load_graph(args.graph)
        result = analyse(graph, args.target)
    except Problem as err:
        print("  {}".format(err), file=sys.stderr)
        return 2

    report(result, top=args.top, log=print)

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({
                "targets": args.target,
                "total": result["total"],
                "reach": sorted(result["reach"]),
                "direct": sorted(result["direct"]),
                "single": result["single"],
                "multi": sorted(result["multi"]),
                "carriers": result["carriers"].most_common(),
            }, fh, indent=1, ensure_ascii=False)
        print("\n  wrote {}".format(args.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
