#!/usr/bin/env python3
r"""Inventory research software across repositories: what exists, what it does,
and whether it is in a state that can be cited.

    python tools/software_inventory.py ROOT [ROOT...] --json out.json
    python tools/software_inventory.py ROOT --markdown

For each tree it reports the repository's identity (remote, branch, licence,
citation metadata) and then every Python module in it with its first docstring
line, its size, and whether it is a runnable entry point or a library.

WHY THIS EXISTS
    Software written during research accumulates faster than anyone records it,
    and the difference between a script and something citable is packaging, not
    quality. A tree with no licence cannot be reused by anyone who reads the
    paper it belongs to; a module with no docstring cannot be understood without
    reading it; a repository with no CITATION.cff has to be cited by URL, which
    rots.

    This reports those three properties per tree and per file, so the gaps are
    a list rather than an impression.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import warnings
import sys
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             "dist", "build", ".mypy_cache", ".pytest_cache", ".lake"}
CITATION = ["CITATION.cff", ".zenodo.json", "codemeta.json"]
LICENCES = ["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING"]


def git(root: Path, *args):
    try:
        out = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True, timeout=20)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def licence_of(root: Path):
    for name in LICENCES:
        p = root / name
        if p.exists():
            head = p.read_text(encoding="utf-8", errors="replace")[:400]
            for spdx, pat in (("MIT", r"\bMIT License\b"),
                              ("Apache-2.0", r"\bApache License\b"),
                              ("BSD-3-Clause", r"\bBSD 3-Clause\b"),
                              ("GPL-3.0", r"\bGNU GENERAL PUBLIC LICENSE\b"),
                              ("CC0-1.0", r"\bCC0\b")):
                if re.search(pat, head, re.I):
                    return spdx
            return "present, unrecognised"
    return None


def describe(path: Path):
    """First docstring line, entry-point flag, and definition counts.

    Parsing is done with warnings suppressed. `ast.parse` reports things like an
    invalid escape sequence from the file being read, and those belong to the
    code under inspection rather than to this tool -- printing them makes every
    run of an inventory look like the inventory is broken.
    """
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(src)
    except Exception:
        return dict(doc="(unparsed)", entry=False, funcs=0, classes=0,
                    lines=0, argparse=False)
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    return dict(
        doc=doc[0].strip() if doc else "",
        entry='__main__' in src,
        argparse="argparse" in src or "ArgumentParser" in src,
        funcs=sum(isinstance(n, ast.FunctionDef) for n in tree.body),
        classes=sum(isinstance(n, ast.ClassDef) for n in tree.body),
        lines=len(src.splitlines()),
    )


def walk(root: Path):
    files = []
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        info = describe(p)
        info["path"] = str(p.relative_to(root)).replace("\\", "/")
        files.append(info)
    return files


def inventory(root: Path):
    root = root.resolve()
    files = walk(root)
    other = {}
    for ext in ("lean", "mm", "tex", "json", "md"):
        n = sum(1 for p in root.rglob(f"*.{ext}")
                if not any(part in SKIP_DIRS for part in p.parts))
        if n:
            other[ext] = n
    return dict(
        name=root.name,
        path=str(root),
        remote=git(root, "remote", "get-url", "origin"),
        branch=git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        head=git(root, "rev-parse", "--short", "HEAD"),
        dirty=len((git(root, "status", "--porcelain") or "").splitlines()),
        licence=licence_of(root),
        citation=[c for c in CITATION if (root / c).exists()],
        py_files=len(files),
        py_lines=sum(f["lines"] for f in files),
        entry_points=sum(1 for f in files if f["entry"]),
        undocumented=[f["path"] for f in files if not f["doc"]],
        other=other,
        files=files,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()

    invs = [inventory(Path(r)) for r in a.roots if Path(r).exists()]

    for inv in invs:
        print(f"== {inv['name']}  {inv['py_files']} modules, {inv['py_lines']:,} lines")
        print(f"   remote   {inv['remote'] or '(none)'}")
        print(f"   licence  {inv['licence'] or 'NONE'}"
              f"    citation {', '.join(inv['citation']) or 'NONE'}")
        print(f"   entry    {inv['entry_points']} runnable, "
              f"{len(inv['undocumented'])} undocumented")
        if inv["other"]:
            print("   other    " + ", ".join(f"{v} .{k}" for k, v in inv["other"].items()))
        print()

    gaps = [i for i in invs if not i["licence"] or not i["citation"]]
    if gaps:
        print("-- citable-state gaps --")
        for i in gaps:
            miss = []
            if not i["licence"]:
                miss.append("no licence")
            if not i["citation"]:
                miss.append("no citation metadata")
            print(f"   {i['name']:<22} {', '.join(miss)}")

    if a.json:
        Path(a.json).write_text(json.dumps(invs, indent=1), encoding="utf-8")
        print(f"\nfull inventory -> {a.json}")

    if a.markdown:
        for inv in invs:
            print(f"\n### {inv['name']}\n")
            print("| module | lines | does |")
            print("|---|---:|---|")
            for f in sorted(inv["files"], key=lambda x: -x["lines"]):
                print(f"| `{f['path']}` | {f['lines']} | {f['doc'][:88]} |")


if __name__ == "__main__":
    main()
