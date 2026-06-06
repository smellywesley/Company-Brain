"""
Blast Radius Simulation.

Before an action executes, compute the set of downstream systems it would touch
by traversing the relationship graph from the action's target entity. In
production this traverses Neo4j; when Neo4j is unavailable (lean demo stack) it
falls back to a deterministic topology derived from the action type and the
tenant's connected systems, so the simulation always renders.

The output is a small directed graph (source -> affected nodes) annotated with
the kind of effect (write / read / notify) and a severity, plus a summary the UI
turns into the "this action will alter N systems" headline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Effect kinds, ordered by how dangerous they are.
_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass
class BlastNode:
    id: str
    label: str
    system: str
    effect: str           # write | read | notify
    severity: str         # low | medium | high
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "system": self.system,
            "effect": self.effect,
            "severity": self.severity,
            "detail": self.detail,
        }


@dataclass
class BlastEdge:
    source: str
    target: str
    label: str

    def as_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "label": self.label}


@dataclass
class BlastRadius:
    origin: BlastNode
    nodes: list[BlastNode] = field(default_factory=list)
    edges: list[BlastEdge] = field(default_factory=list)
    simulated: bool = True   # True when derived from topology (no live Neo4j)

    def summary(self) -> dict:
        writes = sum(1 for n in self.nodes if n.effect == "write")
        reads = sum(1 for n in self.nodes if n.effect == "read")
        notifies = sum(1 for n in self.nodes if n.effect == "notify")
        highest = "low"
        for n in self.nodes:
            if _SEVERITY_RANK[n.severity] > _SEVERITY_RANK[highest]:
                highest = n.severity
        return {
            "systems_touched": len(self.nodes),
            "writes": writes,
            "reads": reads,
            "notifies": notifies,
            "highest_severity": highest,
        }

    def as_dict(self) -> dict:
        return {
            "origin": self.origin.as_dict(),
            "nodes": [n.as_dict() for n in self.nodes],
            "edges": [e.as_dict() for e in self.edges],
            "summary": self.summary(),
            "simulated": self.simulated,
        }


# Deterministic topology by workflow family. Each entry: origin system + the
# downstream systems it fans out to with effect + severity.
_TOPOLOGY: dict[str, dict[str, Any]] = {
    "refund": {
        "origin": ("stripe", "Stripe charge", "Payment processor"),
        "fan": [
            ("salesforce", "Salesforce opportunity", "CRM", "write", "medium", "Adjusts closed-won amount"),
            ("ledger", "Revenue ledger", "QuickBooks", "write", "high", "Posts a reversing entry"),
            ("customer", "Customer profile", "Postgres", "write", "medium", "Updates lifetime value"),
            ("jira", "Support ticket", "Jira", "write", "low", "Marks refund resolved"),
            ("slack", "#finance", "Slack", "notify", "low", "Posts refund notice"),
        ],
    },
    "deploy": {
        "origin": ("github", "Release branch", "GitHub"),
        "fan": [
            ("k8s", "prod-us-east cluster", "Kubernetes", "write", "high", "Rolls out new pods"),
            ("datadog", "Service monitors", "Datadog", "read", "low", "Baselines metrics"),
            ("pagerduty", "On-call rotation", "PagerDuty", "notify", "medium", "Arms deploy alert"),
            ("slack", "#engineering", "Slack", "notify", "low", "Announces deploy"),
        ],
    },
    "lead": {
        "origin": ("salesforce", "Lead record", "Salesforce"),
        "fan": [
            ("hubspot", "Marketing contact", "HubSpot", "write", "low", "Syncs lead score"),
            ("email", "Nurture sequence", "Customer.io", "write", "medium", "Enrolls in sequence"),
            ("slack", "#sales", "Slack", "notify", "low", "Notifies AE"),
        ],
    },
    "ticket": {
        "origin": ("jira", "Support ticket", "Jira"),
        "fan": [
            ("customer", "Customer profile", "Postgres", "read", "low", "Reads account tier"),
            ("pagerduty", "On-call rotation", "PagerDuty", "notify", "high", "Escalates to manager"),
            ("slack", "#support", "Slack", "notify", "low", "Posts escalation"),
        ],
    },
    "retention": {
        "origin": ("salesforce", "Account record", "Salesforce"),
        "fan": [
            ("stripe", "Subscription discount", "Stripe", "write", "high", "Applies discount coupon"),
            ("customer", "Customer profile", "Postgres", "write", "medium", "Flags retention offer"),
            ("email", "Win-back email", "Customer.io", "write", "low", "Sends retention offer"),
            ("slack", "#customer-success", "Slack", "notify", "low", "Notifies CSM"),
        ],
    },
}


def _family(workflow_name: str) -> str:
    name = (workflow_name or "").lower()
    for key in _TOPOLOGY:
        if key in name:
            return key
    return "generic"


def compute_blast_radius(
    workflow_name: str,
    *,
    trigger_data: dict | None = None,
    final_action: dict | None = None,
    neo4j_session: Any = None,
) -> BlastRadius:
    """Compute the blast radius for an action.

    If a Neo4j session is supplied the real graph is traversed (left as an
    integration point); otherwise the deterministic topology is used so the
    simulation renders on the lean stack.
    """
    if neo4j_session is not None:
        traversed = _traverse_neo4j(workflow_name, neo4j_session)
        if traversed is not None:
            return traversed

    family = _family(workflow_name)
    spec = _TOPOLOGY.get(family)

    if spec is None:
        origin = BlastNode(
            id="origin",
            label=workflow_name.replace("_", " ") or "Action target",
            system="Company Brain",
            effect="write",
            severity="medium",
            detail="Primary target of the action",
        )
        downstream = BlastNode(
            id="customer",
            label="Customer profile",
            system="Postgres",
            effect="write",
            severity="medium",
            detail="Updated by the action",
        )
        return BlastRadius(
            origin=origin,
            nodes=[downstream],
            edges=[BlastEdge("origin", "customer", "updates")],
            simulated=True,
        )

    o_id, o_label, o_system = spec["origin"]
    origin = BlastNode(
        id=o_id,
        label=o_label,
        system=o_system,
        effect="write",
        severity="high",
        detail="Primary target of the action",
    )
    nodes: list[BlastNode] = []
    edges: list[BlastEdge] = []
    for node_id, label, system, effect, severity, detail in spec["fan"]:
        nodes.append(
            BlastNode(
                id=node_id,
                label=label,
                system=system,
                effect=effect,
                severity=severity,
                detail=detail,
            )
        )
        edges.append(BlastEdge(origin.id, node_id, effect))
    return BlastRadius(origin=origin, nodes=nodes, edges=edges, simulated=True)


def _traverse_neo4j(workflow_name: str, session: Any) -> BlastRadius | None:
    """Integration point for a live Neo4j traversal. Returns None on any failure
    so the caller falls back to the deterministic topology."""
    try:  # pragma: no cover - exercised only with a live graph
        # Example shape; real Cypher would match the tenant's entity graph.
        # result = session.run("MATCH (a {name:$n})-[r]->(b) RETURN ...", n=workflow_name)
        return None
    except Exception:  # noqa: BLE001
        return None
