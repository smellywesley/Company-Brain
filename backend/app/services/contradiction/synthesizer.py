"""
Contradiction Synthesizer for the Company Brain ingestion layer.

Given a newly merged change (``[NEW REALITY]``) and an active Standard
Operating Procedure (``[STALE ARTIFACT]``), this produces a machine-readable
contradiction report. The report feeds the quarantine lock value and the
Knowledge Reconciliation UI on the approval queue.

Design decisions baked into the prompt:

* The model is a **pure text analyzer** — it never calls or assumes the state
  of any live service. Grounding/verification is a separate step that runs
  before a lock is committed, not a line in a summarization prompt.
* It can return ``no_contradiction=True`` so that semantic-diff noise cannot
  quarantine a healthy SOP. False locks block autonomous action, which is the
  entire value proposition, so the parser also **fails open**: any malformed
  output is treated as "no contradiction" (the normal CriticAgent and human
  approval queue remain in force regardless).
* Output is structured JSON carrying the affected skill id, referenced
  entities, and severity so the Redis lock and the blast-radius view can be
  populated without a second pass.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)

_VALID_SEVERITY = {"low", "medium", "high", "critical"}

_SYSTEM_PROMPT = """\
Identity & Role:
You are the Validation Architect for Company Brain. You analyze a structural
mismatch between a newly merged system modification and an existing Standard
Operating Procedure, and produce a machine-readable contradiction report.
You are a text analyzer only. You do NOT call, verify, or assume the state of
any live service. Reason strictly from the two inputs given.

Inputs:
1. [NEW REALITY]: a unified code diff, an API gateway payload, or a migration
   script.
2. [STALE ARTIFACT]: the active SOP text or JSON skill block, with its skill_id.

Audience: write all prose for an experienced software engineer.

Return ONLY this JSON object, with no markdown fences:
{
  "no_contradiction": true | false,
  "affected_skill_id": "<id from STALE ARTIFACT, or null>",
  "severity": "low" | "medium" | "high" | "critical",
  "confidence": 0.0,
  "conflicts": [
    {
      "summary": "<one precise sentence; start with the action and the exact
                   nature of the break; name the specific variable, endpoint,
                   protocol, or key involved>",
      "sop_step": "<the exact step/line in the STALE ARTIFACT now wrong>",
      "new_reality": "<the specific change in NEW REALITY that breaks it>",
      "referenced_entities": ["<endpoint|var|protocol|key>"]
    }
  ]
}

Rules:
- If the inputs do not genuinely conflict, set no_contradiction=true and return
  an empty conflicts array. Do NOT manufacture a conflict from superficial
  keyword overlap. A false conflict quarantine-locks a healthy SOP.
- One change may break multiple SOP steps: emit one conflict object per break.
- No introductory phrases. Each summary starts with the action.
"""


class ContradictionSynthesizer:
    """Synthesizes a contradiction report between a change and an SOP."""

    def __init__(self, llm: LLMAdapter) -> None:
        self.llm = llm

    async def synthesize(
        self,
        new_reality: str,
        stale_artifact: str,
        skill_id: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Compare ``new_reality`` against ``stale_artifact`` and report conflicts."""
        user_prompt = (
            "[NEW REALITY]\n"
            f"{new_reality}\n\n"
            f"[STALE ARTIFACT] (skill_id={skill_id})\n"
            f"{stale_artifact}"
        )
        try:
            response = await self.llm.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                metadata=(
                    {"tenant_id": tenant_id, "trace_name": "contradiction-synthesis"}
                    if tenant_id
                    else None
                ),
            )
        except Exception as exc:  # network / provider failure — do not lock
            logger.error("Contradiction synthesis LLM call failed: %s", exc)
            return self._no_contradiction(skill_id)

        return self._parse(response.content, skill_id)

    @staticmethod
    def _no_contradiction(skill_id: str) -> dict[str, Any]:
        return {
            "no_contradiction": True,
            "affected_skill_id": skill_id,
            "severity": "low",
            "confidence": 0.0,
            "conflicts": [],
        }

    def _parse(self, content: str, skill_id: str) -> dict[str, Any]:
        raw = (content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            # Fail OPEN: a malformed report must not quarantine a healthy SOP.
            logger.error(
                "ContradictionSynthesizer: unparseable model output: %s",
                (content or "")[:200],
            )
            return self._no_contradiction(skill_id)

        conflicts = parsed.get("conflicts") or []
        if not isinstance(conflicts, list):
            conflicts = []

        # A conflict with no entries is no conflict, regardless of the flag.
        no_contradiction = bool(parsed.get("no_contradiction", not conflicts))
        if not conflicts:
            no_contradiction = True

        severity = parsed.get("severity", "high")
        if severity not in _VALID_SEVERITY:
            severity = "high"

        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        return {
            "no_contradiction": no_contradiction,
            "affected_skill_id": parsed.get("affected_skill_id") or skill_id,
            "severity": severity,
            "confidence": confidence,
            "conflicts": conflicts,
        }
