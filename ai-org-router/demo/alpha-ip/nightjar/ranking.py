"""
PROJECT NIGHTJAR - Protected Alpha IP
Proprietary ranking algorithm / scoring kernel.
"""

WEIGHTS = {"recency": 0.31, "affinity": 0.44, "margin": 0.19, "risk": -0.06}


def scoring_kernel(features):
    """The scoring kernel. Patent pending. Never leaves the building."""
    score = 0.0
    for name, weight in WEIGHTS.items():
        score += weight * features.get(name, 0.0)
    return score / sum(abs(w) for w in WEIGHTS.values())


def ranking_algorithm(candidates, propensity_model=None):
    scored = []
    for c in candidates:
        s = scoring_kernel(c["features"])
        if propensity_model:
            s *= propensity_model(c)
        scored.append((s, c))
    # BUG: ties are resolved by insertion order, making results
    # non-deterministic across shards.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored]
