"""§68-69 of the review doc. Deliberately minimal, dependency-free implementation
of global Moran's I so the platform doesn't need a full geospatial-stats stack
just to answer 'is delayed sowing spatially clustered'. This is a Tier-3/advanced
card (§4) -- start simple, validate before adding LISA/Getis-Ord/significance
testing machinery, per the review doc's own guidance not to over-build v1."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MoranResult:
    i: float
    n: int
    interpretation: str


def morans_i(values: list[float], weights: list[list[float]]) -> MoranResult:
    """values: one value per spatial unit (e.g. sowing deviation per district).
    weights: n x n spatial weights matrix (e.g. binary contiguity, row-standardized
    outside this function). Caller is responsible for building `weights` from real
    adjacency -- this function only does the statistic itself."""
    n = len(values)
    if n < 3:
        raise ValueError("Moran's I needs at least 3 spatial units")
    if len(weights) != n or any(len(row) != n for row in weights):
        raise ValueError("weights must be an n x n matrix matching len(values)")

    mean = sum(values) / n
    dev = [v - mean for v in values]
    denom = sum(d * d for d in dev)
    if denom == 0:
        raise ValueError("zero variance -- Moran's I undefined")

    w_sum = sum(sum(row) for row in weights)
    if w_sum == 0:
        raise ValueError("spatial weights matrix has zero total weight")

    numer = sum(
        weights[i][j] * dev[i] * dev[j]
        for i in range(n)
        for j in range(n)
        if i != j
    )
    i_stat = (n / w_sum) * (numer / denom)

    if i_stat > 0.15:
        interp = "positive -- similar values cluster spatially"
    elif i_stat < -0.15:
        interp = "negative -- similar values repel / checkerboard pattern"
    else:
        interp = "near zero -- weak spatial autocorrelation"

    return MoranResult(i=round(i_stat, 4), n=n, interpretation=interp)


def row_standardize(binary_adjacency: list[list[int]]) -> list[list[float]]:
    out = []
    for row in binary_adjacency:
        s = sum(row)
        out.append([v / s if s > 0 else 0.0 for v in row])
    return out
