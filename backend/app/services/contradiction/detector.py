"""
Tier 0 structural detector for the Contradiction Handshake.

The shipped pipeline asked an LLM "does this PR contradict this SOP?" from the
PR title and body alone — it never saw the diff. This module adds a cheap,
deterministic first pass: extract the concrete entities a PR touches (changed
file paths, route paths, and identifiers from the diff) and check whether an
active SOP's text actually references any of them.

It produces a *candidate* signal, never a verdict. Two uses:

1. Gate the expensive LLM: only SOPs with structural overlap are worth an LLM
   adjudication call (most SOPs are unrelated to any given PR).
2. Supply a deterministic, auditable signal an auditor can verify by eye
   ("the PR deleted POST /token; SOP step 2 calls POST /token") — unlike a
   title-only LLM guess.

Pure functions, no I/O. The caller fetches the PR diff (e.g. via the GitHub
``/pulls/{n}/files`` API) and passes the changed paths + patch text in.
"""

from __future__ import annotations

import re

# Entities shorter than this, or in the stoplist, are too generic to be a
# trustworthy structural signal (they would match SOP prose by accident).
_MIN_ENTITY_LEN = 3
_STOPLIST = {
    "the", "and", "for", "get", "set", "put", "var", "let", "def", "new",
    "out", "src", "lib", "app", "api", "url", "key", "val", "tmp", "log",
    "txt", "json", "yaml", "yml", "test", "tests", "index", "main", "init",
}

# Route-like path inside a diff line, e.g. /token, /api/users, /v1/users/{id}
_ROUTE_RE = re.compile(r"/[A-Za-z0-9_][A-Za-z0-9_\-/{}:.]{1,80}")
# Identifier declarations across common languages.
_IDENT_RE = re.compile(
    r"\b(?:def|class|func|function|const|let|var|interface|type|enum)\s+"
    r"([A-Za-z_][A-Za-z0-9_]{2,80})"
)


def _basenames(path: str) -> set[str]:
    """File path → {full path, basename, basename without extension}."""
    norm = path.strip().replace("\\", "/").lstrip("./")
    if not norm:
        return set()
    out = {norm}
    base = norm.rsplit("/", 1)[-1]
    out.add(base)
    if "." in base:
        out.add(base.rsplit(".", 1)[0])
    return out


def extract_changed_entities(
    changed_paths: list[str] | None,
    patch_text: str = "",
) -> set[str]:
    """Concrete entities a PR touches: paths, basenames, routes, identifiers.

    Deterministic and order-independent. Filters out entities too short or too
    generic to be a reliable signal.
    """
    entities: set[str] = set()

    for path in changed_paths or []:
        if isinstance(path, str):
            entities |= _basenames(path)

    text = patch_text or ""
    # Only mine added/removed diff lines — context lines are not "touched".
    diff_lines = [
        ln[1:] for ln in text.splitlines()
        if ln[:1] in ("+", "-") and not ln[:3] in ("+++", "---")
    ]
    diff_body = "\n".join(diff_lines) if diff_lines else text

    for route in _ROUTE_RE.findall(diff_body):
        entities.add(route.rstrip("/.,);:"))
    for ident in _IDENT_RE.findall(diff_body):
        entities.add(ident)

    # Drop noise.
    return {
        e for e in (s.strip() for s in entities)
        if len(e) >= _MIN_ENTITY_LEN and e.lower() not in _STOPLIST
    }


def find_sop_overlap(sop_text: str, entities: set[str]) -> list[str]:
    """Entities the SOP text references, case-insensitive. Sorted, deterministic.

    Routes (containing ``/``) match as substrings. Bare identifiers/basenames
    match on a word-ish boundary so ``token`` does not match ``tokenizer``.
    """
    if not sop_text or not entities:
        return []
    hay = sop_text.lower()
    matched: set[str] = set()
    for entity in entities:
        e = entity.lower()
        if "/" in e:
            if e in hay:
                matched.add(entity)
        else:
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(e)}(?![A-Za-z0-9_])", hay):
                matched.add(entity)
    return sorted(matched)


def detect(
    changed_paths: list[str] | None,
    patch_text: str,
    sop_text: str,
) -> dict:
    """Tier 0 structural check between a PR's changes and one SOP.

    Returns a candidate signal — never a hard verdict. ``confidence`` is a
    deterministic function of match quality: a route-path match is stronger
    evidence of a real contract break than a bare basename match.
    """
    entities = extract_changed_entities(changed_paths, patch_text)
    matched = find_sop_overlap(sop_text, entities)
    has_route_match = any("/" in m for m in matched)
    if not matched:
        confidence = 0.0
    elif has_route_match:
        confidence = 0.8
    else:
        confidence = 0.55
    return {
        "has_structural_overlap": bool(matched),
        "matched_entities": matched,
        "signal": {
            "type": "structural_entity_overlap",
            "source": "structural",
            "confidence": confidence,
            "detail": (
                f"PR touches {', '.join(matched)} which the SOP references"
                if matched else "no overlap between PR changes and SOP"
            ),
        },
    }
