"""
============================================================
authorecon — reconcile a published record against the
             systems that hold it
F-Keys | www.f-keys.com
------------------------------------------------------------
Twenty checks over ORCID, OpenAlex, Crossref, DataCite,
Zenodo, Europe PMC, PubMed, OpenLibrary and Wikidata. One
command runs the ones that need nothing but an identifier and
writes a single document:

    authorecon-report 0000-0002-1825-0097
    authorecon-reference-check bibliography.txt

Nothing here is scored, ranked or graded. Each check states
what it found and what it could not reach, because the same
fact means different things for a first-year student and a
professor of thirty years.

No dependencies. Standard library only.
============================================================
"""

#: Kept in step with pyproject.toml. The two drift silently otherwise: the
#: wheel filename and its metadata both come from pyproject, so they agree
#: with each other while the code inside reports something else, and the
#: mismatch is invisible from outside the wheel.
__version__ = "1.0.0"
