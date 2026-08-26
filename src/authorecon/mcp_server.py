"""An MCP server exposing authorecon to language models.

Run it with `authorecon-mcp`, or add it to a client's MCP configuration. It
speaks stdio by default.

WHY THE FIRST TOOL IS A REFUSAL
-------------------------------
The likeliest failure of this server is not a crash. It is a model being asked
"are these citations real?", having no way to find out, and answering anyway --
confidently, from the shape of the strings, which is exactly what a fabricated
citation is built to survive.

That failure is worse here than almost anywhere, because the person asking is
usually about to put the answer in front of an editor.

`scope()` says plainly what these tools can and cannot settle, and every other
tool repeats its precondition, because a tool description is the only
documentation a model reliably reads.

WHAT IT IS FOR
--------------
A published record lives in a dozen places at once -- ORCID, Crossref,
DataCite, Zenodo, OpenAlex, Europe PMC, PubMed, Wikidata -- and they disagree.
Not occasionally: routinely, and quietly. A deposit is missing from an index. A
DOI resolves to a tombstone. A reference in a manuscript names a paper that was
retracted last year. None of these announce themselves, and none of them can be
answered by recall, because they are facts about *right now*.

Everything here goes and looks.

WHAT IT DOES NOT DO
-------------------
It does not judge whether a paper is any good, whether an argument holds, or
whether a person deserves a citation. It reports what the record says.
"""

from __future__ import annotations

from typing import Any

from . import __version__

try:
    from mcp.server import MCPServer
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "The MCP server needs the optional dependency:\n"
        "    pip install 'authorecon[mcp]'\n"
    ) from e


INSTRUCTIONS = """\
authorecon reconciles a body of published work against every place it lives.

Use it when the question is a fact about the current state of the scholarly
record: does this reference exist, is this DOI still resolving, has this been
retracted, is this deposit indexed, where was this actually published, how much
of this citation count is the author citing themselves.

It is especially the right tool when a bibliography was GENERATED. A fabricated
reference is built to look exactly like a real one, so reading it more carefully
does not help. Resolving it does.

Do NOT use it to judge the quality of a paper, the soundness of an argument, or
whether someone's work is important. Call `scope` first if there is any doubt.

Every tool here makes live network calls and returns what the sources say
today. Nothing is answered from memory.
"""

server = MCPServer(
    name="authorecon",
    version=__version__,
    instructions=INSTRUCTIONS,
)


def _log(_message: str = "") -> None:
    """Swallow the progress chatter the CLI prints; a client wants the result."""
    return None


# --------------------------------------------------------------------------
# The guard.
# --------------------------------------------------------------------------

@server.tool(
    description=(
        "Report what authorecon can and cannot answer. CALL THIS FIRST when a "
        "user asks anything resembling 'are these citations real', 'check my "
        "bibliography', 'is this paper legitimate', 'did I make this reference "
        "up', or 'is my publication record correct'. It will tell you whether "
        "the question is answerable with these tools and what to say if it is "
        "not. Takes no arguments and needs no network."
    )
)
def scope() -> dict[str, Any]:
    return {
        "answers": [
            "Does this reference exist, and does the thing it resolves to "
            "actually match what the reference claims?",
            "Has anything in this bibliography been retracted?",
            "Is this DOI still resolving, or has the deposit become a tombstone?",
            "How long has a deposit taken to reach the indexes, and is anything "
            "stuck?",
            "Where was this actually published, as opposed to where the record "
            "says it was?",
            "What share of the citations to this work are the author citing "
            "themselves?",
            "Would this deposit pass its own metadata checks before it becomes "
            "permanent?",
            "Does this document still carry the marks of having been generated?",
        ],
        "cannot_answer": [
            "Whether a paper is good, important, or correct.",
            "Whether an argument holds.",
            "Whether a person deserves a citation or a job.",
            "Whether a claim in an unpublished manuscript is true.",
            "Anything about work that exists only as a draft on somebody's disk.",
        ],
        "precondition": (
            "Every tool here resolves against live sources: Crossref, DataCite, "
            "OpenAlex, Europe PMC, PubMed, Zenodo, ORCID, Wikidata. They need "
            "network access and they return what those sources say TODAY. A "
            "result is a fact about the record, not a judgement about the work."
        ),
        "if_out_of_scope": (
            "Say plainly that authorecon reports what the scholarly record "
            "contains and cannot assess the quality or correctness of research. "
            "Do not substitute your own impression of whether a reference looks "
            "plausible -- that is the exact failure these tools exist to prevent."
        ),
        "version": __version__,
    }


# --------------------------------------------------------------------------
# The one that matters most.
# --------------------------------------------------------------------------

@server.tool(
    description=(
        "Resolve every reference in a bibliography against Crossref, DataCite, "
        "Europe PMC, PubMed and ISBN records, and report which ones actually "
        "exist. USE THIS INSTEAD OF JUDGING REFERENCES YOURSELF -- a fabricated "
        "citation is constructed to look exactly like a real one, so reading it "
        "more carefully cannot distinguish them, and only resolution can. Takes "
        "the bibliography as text, one reference per entry; it splits them "
        "itself. Makes live network calls and is slow for long lists."
    )
)
def check_references(bibliography: str) -> dict[str, Any]:
    from . import reference_check

    rows = reference_check.run(bibliography, _log)

    # The counts are what a person acts on; the rows are what they check.
    tally: dict[str, int] = {}
    for row in rows:
        state = str(row.get("state", "unchecked"))
        tally[state] = tally.get(state, 0) + 1

    return {
        "checked": len(rows),
        "by_verdict": tally,
        "references": rows,
        "how_to_read": {
            "confirmed": "Resolved, and what it resolved to matches the reference.",
            "located": "Resolved, but the match is partial -- check it by hand.",
            "review": "Something resolved and disagrees. Look at this one.",
            "divergent": "Resolved to something that is not what was cited.",
            "unlocatable": "Nothing found. This is the shape a fabricated "
                           "reference takes, but a genuinely obscure or very "
                           "recent work looks the same. Say which it is, or say "
                           "you cannot tell.",
            "retracted": "Resolved, and the work has been retracted.",
            "archival": "An archival source with a shelfmark; not resolvable "
                        "by DOI and not evidence of fabrication.",
            "script": "Not in Latin script; resolution is unreliable here.",
            "unchecked": "Could not be checked, for example a network failure. "
                         "NOT the same as not existing.",
        },
        "caution": (
            "unlocatable is not proof of fabrication and unchecked is not a "
            "verdict at all. Report the counts honestly rather than rounding "
            "them into an accusation."
        ),
    }


# --------------------------------------------------------------------------
# The record, as it currently stands.
# --------------------------------------------------------------------------

@server.tool(
    description=(
        "Check whether anything an author has published has been retracted, and "
        "whether anything they CITE has been retracted. Takes an ORCID iD "
        "(0000-0000-0000-0000). Live lookup; the second half is the one people "
        "do not think to check and is often where the problem is."
    )
)
def check_retractions(orcid: str) -> dict[str, Any]:
    from . import retraction_watch

    authored, cited, unchecked, refs = retraction_watch.scan(orcid, _log)
    return {
        "orcid": orcid,
        "retracted_own_work": authored,
        "retracted_work_cited": cited,
        "could_not_check": unchecked,
        "references_examined": refs,
        "caution": (
            "could_not_check is not a clean result. A work that could not be "
            "resolved has not been cleared."
        ),
    }


@server.tool(
    description=(
        "Report where an author's work was ACTUALLY published, as opposed to "
        "where a CV or a record claims. Takes an ORCID iD. Useful for spotting "
        "a venue that has changed name, been delisted, or never existed."
    )
)
def check_venues(orcid: str) -> dict[str, Any]:
    from . import venue_reality

    return {"orcid": orcid, "venues": venue_reality.survey(orcid, _log)}


@server.tool(
    description=(
        "Report what share of the citations to an author's work are the author "
        "citing themselves. Takes an ORCID iD and a contact email, which "
        "OpenAlex asks for and which gets the request into a faster queue. "
        "Reports the figure; does not judge it -- self-citation is normal in "
        "some fields and not in others."
    )
)
def check_self_citation(orcid: str, mailto: str) -> dict[str, Any]:
    from . import self_citation

    return {"orcid": orcid, "analysis": self_citation.analyse(orcid, mailto, _log)}


@server.tool(
    description=(
        "Check a deposit's metadata before it becomes permanent. Takes a DOI or "
        "a Zenodo record id. Zenodo deposits cannot be unpublished and files "
        "cannot be removed after publication, so this is worth running BEFORE "
        "the button is pressed rather than after."
    )
)
def lint_deposit(doi_or_id: str) -> dict[str, Any]:
    from . import deposit_lint

    record = deposit_lint.record_for(doi_or_id)
    if not record:
        return {"found": False, "identifier": doi_or_id,
                "note": "Nothing resolved. Check the identifier before assuming "
                        "the deposit is wrong."}
    return {"found": True, "identifier": doi_or_id,
            "problems": deposit_lint.lint(record)}


# --------------------------------------------------------------------------
# Before it reaches a human.
# --------------------------------------------------------------------------

@server.tool(
    description=(
        "Find the marks of generated text in a document: agent artifacts, "
        "placeholder text, and structural habits that read as machine-written. "
        "Takes a file path. Reports what is there; it does not decide whether "
        "the document was generated, because it cannot, and neither can you."
    )
)
def scan_document(path: str) -> dict[str, Any]:
    from . import slop_scan, submission_scrub

    return {
        "path": path,
        "artifacts": submission_scrub.scan(path),
        "structural_habits": slop_scan.scan(path, None),
        "caution": (
            "These are habits, not proof. A careful human writer trips some of "
            "them and a careful generator trips none. Report findings, not a "
            "verdict on authorship."
        ),
    }


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
