"""
Probabilistic Risk Forecaster.

Elevates the CriticAgent's scalar ``risk_score`` (0-1) into a *calibrated
probability of a negative outcome* (financial loss / compliance breach) with a
confidence band, and decides routing against a *dynamic* threshold that tightens
as the tenant accumulates feedback history.

This is the math layer that makes the safety system predictive rather than a
deterministic pass/fail. It is intentionally pure and deterministic so it can be
unit-tested and so the same inputs always render the same gauge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Logistic steepness for recalibrating raw risk into a probability. >1 pushes
# mid-range scores toward the extremes (sharper opinion).
_CALIBRATION_GAIN = 3.2
# z for ~90% confidence interval.
_Z_90 = 1.645
# Base routing threshold before history-based tightening.
_BASE_THRESHOLD = 0.5
# Floor/ceiling so the threshold never becomes absurd.
_THRESHOLD_FLOOR = 0.25
_THRESHOLD_CEIL = 0.75


@dataclass
class RiskFactor:
    """A single contributor to the forecast, for the gauge breakdown."""

    label: str
    weight: float  # 0-1 relative contribution


@dataclass
class RiskForecast:
    """Calibrated probabilistic forecast for one candidate action."""

    risk_score: float          # raw critic score (0-1)
    probability: float         # calibrated P(negative outcome) (0-1)
    confidence_low: float      # lower bound of the 90% band (0-1)
    confidence_high: float     # upper bound of the 90% band (0-1)
    dynamic_threshold: float   # routing threshold for this tenant (0-1)
    routed_to_human: bool      # True if the action must go to the queue
    autonomy_level: int        # 0-4 (see autonomy_level())
    factors: list[RiskFactor] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "risk_score": round(self.risk_score, 4),
            "probability": round(self.probability, 4),
            "confidence_low": round(self.confidence_low, 4),
            "confidence_high": round(self.confidence_high, 4),
            "dynamic_threshold": round(self.dynamic_threshold, 4),
            "routed_to_human": self.routed_to_human,
            "autonomy_level": self.autonomy_level,
            "factors": [{"label": f.label, "weight": round(f.weight, 3)} for f in self.factors],
        }


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def calibrate_probability(risk_score: float) -> float:
    """Map a raw 0-1 risk score to a calibrated probability via a logistic curve
    centred at 0.5. Monotonic, so a higher score is always a higher probability."""
    score = max(0.0, min(1.0, risk_score))
    return _sigmoid(_CALIBRATION_GAIN * (score - 0.5))


def confidence_band(probability: float, n_history: int) -> tuple[float, float]:
    """Wilson-style 90% interval. More history -> tighter band. With no history
    the band is wide (we are guessing); it narrows as evidence accumulates."""
    n = max(1, n_history)
    half = _Z_90 * math.sqrt(max(probability * (1.0 - probability), 1e-4) / n)
    return max(0.0, probability - half), min(1.0, probability + half)


def dynamic_threshold(n_history: int, miss_rate: float, base: float = _BASE_THRESHOLD) -> float:
    """Routing threshold that tightens (drops) when the tenant has recently had
    actions slip through that humans later corrected (a higher ``miss_rate``),
    and relaxes slightly as a clean track record accumulates.

    base: the tenant's risk-posture centre (conservative lowers it, aggressive
    raises it). miss_rate: fraction of recent decisions that were human-corrected.
    """
    # Each point of miss-rate pulls the bar down (be more cautious).
    caution = 0.5 * max(0.0, min(1.0, miss_rate))
    # A long clean history earns a little more autonomy (raise the bar).
    earned = 0.12 * _sigmoid((n_history - 25) / 12.0)
    thr = base - caution + earned
    return max(_THRESHOLD_FLOOR, min(_THRESHOLD_CEIL, thr))


def autonomy_level(
    probability: float,
    threshold: float,
    n_history: int,
    max_level: int = 4,
) -> int:
    """L0-L4 self-driving-style autonomy for this action.

    L0 manual / L1 assisted / L2 conditional / L3 high / L4 full.
    Driven by how far the action sits below the routing threshold and how much
    calibrated history backs the decision. ``max_level`` caps it to the tenant's
    risk posture (e.g. conservative never exceeds L2).
    """
    if probability >= threshold:
        level = 1 if probability < threshold + 0.15 else 0
        return min(level, max_level)
    margin = threshold - probability       # how safely below the bar
    if n_history < 8:
        level = 2 if margin > 0.2 else 1
    elif margin > 0.35 and n_history >= 30:
        level = 4
    elif margin > 0.22:
        level = 3
    else:
        level = 2
    return min(level, max_level)


# Keyword -> human-readable factor. Derived from the critic's reasons so the
# gauge can show *why* the probability is what it is.
_FACTOR_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("pii", "personal", "email", "ssn", "card"), "PII exposure"),
    (("financial", "amount", "refund", "limit", "$", "payment", "charge"), "Financial limit"),
    (("rbac", "role", "permission", "sign-off", "manager", "approval"), "Authorization"),
    (("staging", "production", "deploy", "rollback"), "Operational blast"),
    (("policy", "compliance", "regulat"), "Policy adherence"),
    (("cross-source", "novel", "confidence", "unverified"), "Evidence quality"),
]


def derive_factors(reasons: list[str] | None, risk_score: float) -> list[RiskFactor]:
    """Turn critic reasons into weighted factors for the gauge breakdown."""
    text = " ".join(reasons or []).lower()
    hits: list[RiskFactor] = []
    for keywords, label in _FACTOR_KEYWORDS:
        if any(k in text for k in keywords):
            hits.append(RiskFactor(label=label, weight=0.0))
    if not hits:
        hits.append(RiskFactor(label="General risk", weight=1.0))
        return hits
    # Distribute the risk score across the matched factors, front-loaded.
    total = sum(1.0 / (i + 1) for i in range(len(hits)))
    for i, f in enumerate(hits):
        f.weight = max(0.05, (1.0 / (i + 1)) / total) * max(0.15, risk_score)
    return hits


def forecast_risk(
    risk_score: float,
    *,
    n_history: int = 0,
    miss_rate: float = 0.0,
    reasons: list[str] | None = None,
    threshold_base: float = _BASE_THRESHOLD,
    max_autonomy: int = 4,
) -> RiskForecast:
    """Build a full probabilistic forecast from the critic's scalar output, the
    tenant's accumulated history, and the tenant's risk posture
    (``threshold_base`` + ``max_autonomy``)."""
    probability = calibrate_probability(risk_score)
    low, high = confidence_band(probability, n_history)
    threshold = dynamic_threshold(n_history, miss_rate, base=threshold_base)
    # Route on the *upper* bound: when we are uncertain, err toward a human.
    routed = high >= threshold
    level = autonomy_level(probability, threshold, n_history, max_level=max_autonomy)
    factors = derive_factors(reasons, risk_score)
    return RiskForecast(
        risk_score=max(0.0, min(1.0, risk_score)),
        probability=probability,
        confidence_low=low,
        confidence_high=high,
        dynamic_threshold=threshold,
        routed_to_human=routed,
        autonomy_level=level,
        factors=factors,
    )


def calibration_curve(
    points: list[tuple[float, bool]],
    bins: int = 5,
) -> list[dict]:
    """Reliability curve: bucket predicted probabilities and report the observed
    rate of negative outcomes in each bucket. A well-calibrated critic has
    observed ≈ predicted (points near the diagonal).

    points: (predicted_probability, was_negative_outcome) pairs.
    """
    buckets: list[dict] = []
    for b in range(bins):
        lo = b / bins
        hi = (b + 1) / bins
        in_bin = [neg for (p, neg) in points if (lo <= p < hi or (b == bins - 1 and p == hi))]
        n = len(in_bin)
        observed = (sum(1 for neg in in_bin if neg) / n) if n else None
        buckets.append(
            {
                "bin_low": round(lo, 3),
                "bin_high": round(hi, 3),
                "predicted_mid": round((lo + hi) / 2, 3),
                "observed": round(observed, 3) if observed is not None else None,
                "count": n,
            }
        )
    return buckets
