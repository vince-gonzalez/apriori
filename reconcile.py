#!/usr/bin/env python3
"""authorecon -- reconcile a body of published work against every place it lives.

    ZENODO_TOKEN=... python authorecon.py

Answers the questions that get harder every time you publish:

  COVERAGE   every deposit has a Wikidata item, or a stated reason it does not
  INTEGRITY  every item still resolves, carries the right DOI, and is attributed
  INDEXING   every work is in OpenAlex, and who has cited it since last run
  OEIS       every sequence links the paper it came from
  GRAPH      how much of the citation list is expressible on Wikidata

Exit code is non-zero when something is wrong and unexplained, so this can run
on a schedule and stay quiet until it has news.

State lives in state.json: only citation counts, so a new citation is reported
once rather than every run.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "authorecon/0.1 (mailto:vincegonzalez@me.com)"}
WD = "https://www.wikidata.org/w/api.php"
OA = "https://api.openalex.org/works/doi:"

works_doc = json.loads((HERE / "works.json").read_text(encoding="utf-8"))
AUTHOR = works_doc["author"]
WORKS = works_doc["works"]
STATE = HERE / "state.json"
state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

s = requests.Session()
problems, news = [], []


def head(t):
    print()
    print(t)
    print("-" * len(t))


# ---------------------------------------------------------------- COVERAGE
head("COVERAGE")
missing = [w for w in WORKS if not w["wikidata"]]
for w in missing:
    if w.get("exclude_reason"):
        print(f"  skipped  {w['zenodo']}  {w['title'][:52]}")
        print(f"           reason: {w['exclude_reason'][:78]}")
    else:
        problems.append(f"no Wikidata item: {w['zenodo']} {w['title'][:50]}")
        print(f"  MISSING  {w['zenodo']}  {w['title'][:52]}")
print(f"  {sum(1 for w in WORKS if w['wikidata'])}/{len(WORKS)} works carry an item")

# --------------------------------------------------------------- INTEGRITY
head("INTEGRITY")
qids = [w["wikidata"] for w in WORKS if w["wikidata"]]
ent = {}
for i in range(0, len(qids), 50):
    r = s.get(WD, params={"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
                          "props": "claims", "format": "json"}, headers=UA, timeout=90)
    ent.update(r.json().get("entities", {}))
bad = 0
for w in WORKS:
    q = w["wikidata"]
    if not q:
        continue
    e = ent.get(q)
    if not e or "missing" in e:
        problems.append(f"{q} does not resolve ({w['zenodo']})")
        print(f"  GONE     {q}  {w['title'][:48]}")
        bad += 1
        continue
    cl = e.get("claims", {})
    doi = [c["mainsnak"]["datavalue"]["value"].upper() for c in cl.get("P356", [])]
    auth = [c["mainsnak"]["datavalue"]["value"]["id"] for c in cl.get("P50", [])]
    want = (w["concept_doi"] or "").upper()
    if want and want not in doi:
        problems.append(f"{q} P356 {doi} != concept {want}")
        print(f"  DOI      {q}  carries {doi} expected {want}")
        bad += 1
    if AUTHOR["wikidata"] not in auth:
        problems.append(f"{q} is not attributed to {AUTHOR['wikidata']}")
        print(f"  AUTHOR   {q}  P50={auth}")
        bad += 1
print(f"  {len(qids) - bad}/{len(qids)} items correct")

# ---------------------------------------------------------------- INDEXING
head("INDEXING")
counts, indexed = {}, 0
for w in WORKS:
    d = w["concept_doi"] or w["doi"]
    if not d:
        continue
    r = s.get(OA + d, headers=UA, timeout=45)
    if r.status_code != 200:
        print(f"  absent   {d}  {w['title'][:44]}")
        continue
    indexed += 1
    n = r.json().get("cited_by_count", 0)
    counts[d] = n
    was = state.get("cited", {}).get(d)
    if was is not None and n > was:
        news.append(f"{w['title'][:56]} cited {n - was} more time(s) (now {n})")
        print(f"  NEW      {d}  {was} -> {n} citations")
    time.sleep(0.2)
total = sum(counts.values())
print(f"  {indexed}/{len(WORKS)} indexed in OpenAlex  |  {total} citation(s) total")

# -------------------------------------------------------------------- OEIS
head("OEIS")
oeis_works = [w for w in WORKS if w.get("oeis")]
if not oeis_works:
    print("  no sequences recorded")
for w in oeis_works:
    for a in w["oeis"]:
        r = s.get("https://oeis.org/search", params={"q": a, "fmt": "json"},
                  headers=UA, timeout=45)
        try:
            seq = r.json()
            seq = seq[0] if isinstance(seq, list) else seq
        except Exception:
            print(f"  {a}: could not read")
            continue
        links = " ".join(seq.get("link") or [])
        key = (w["concept_doi"] or "").split("/")[-1]
        if key and key in links:
            print(f"  ok       {a} links {w['concept_doi']}")
        else:
            problems.append(f"{a} does not link its paper {w['concept_doi']}")
            print(f"  NO LINK  {a}  should link {w['concept_doi']}")
        time.sleep(0.3)

# ------------------------------------------------------------------- GRAPH
head("GRAPH")
cited = sorted({c for w in WORKS for c in w["cites"]})
own = {(w["concept_doi"] or "").upper(): w["wikidata"] for w in WORKS}
own.update({(w["doi"] or "").upper(): w["wikidata"] for w in WORKS})
resolvable = sum(1 for c in cited if own.get(c.upper()))
print(f"  {len(cited)} distinct cited works, {resolvable} are your own")
print(f"  {sum(len(w['cites']) for w in WORKS)} citation edges recorded in Zenodo")

# ------------------------------------------------------------------ REPORT
STATE.write_text(json.dumps({"cited": counts,
                             "checked": time.strftime("%Y-%m-%d")}, indent=1),
                 encoding="utf-8")
head("SUMMARY")
for n in news:
    print(f"  NEWS     {n}")
for p in problems:
    print(f"  PROBLEM  {p}")
if not problems and not news:
    print("  nothing to report")
sys.exit(1 if problems else 0)
