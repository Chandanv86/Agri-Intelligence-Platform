"""Administrative aggregation rules. §81/§108 of the review doc: never average
child percentages or child yields directly -- aggregate the underlying
numerators/denominators, then recompute the ratio at the parent scale."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChildUnit:
    admin_id: str
    established_area_ha: float
    target_area_ha: float
    yield_kg_ha: float
    area_ha: float


def aggregate_progress(children: list[ChildUnit]) -> float:
    total_established = sum(c.established_area_ha for c in children)
    total_target = sum(c.target_area_ha for c in children)
    if total_target <= 0:
        raise ValueError("aggregate target area must be > 0")
    return round(total_established / total_target * 100, 4)


def aggregate_yield(children: list[ChildUnit]) -> float:
    """Area-weighted mean yield -- NOT mean(child_yields)."""
    total_area = sum(c.area_ha for c in children)
    if total_area <= 0:
        raise ValueError("aggregate area must be > 0")
    weighted = sum(c.yield_kg_ha * c.area_ha for c in children)
    return round(weighted / total_area, 4)


def spatial_spread(values: list[float]) -> dict[str, float]:
    """§20/§82: P90-P10 spread as a heterogeneity signal across child units."""
    if not values:
        raise ValueError("values must be non-empty")
    s = sorted(values)
    n = len(s)

    def pct(p: float) -> float:
        if n == 1:
            return s[0]
        k = (n - 1) * p
        f, c = int(k), min(int(k) + 1, n - 1)
        if f == c:
            return s[f]
        return s[f] + (s[c] - s[f]) * (k - f)

    p10, p90 = pct(0.10), pct(0.90)
    return {"p10": round(p10, 4), "p90": round(p90, 4), "spread": round(p90 - p10, 4)}


def area_share_by_status(children: list[ChildUnit], status_of) -> dict[str, float]:
    """§19: 'on schedule / delayed / ahead' should be weighted by AREA share,
    not by count of administrative units. status_of(child) -> status label."""
    total_area = sum(c.area_ha for c in children)
    if total_area <= 0:
        raise ValueError("aggregate area must be > 0")
    shares: dict[str, float] = {}
    for c in children:
        label = status_of(c)
        shares[label] = shares.get(label, 0.0) + c.area_ha
    return {k: round(v / total_area * 100, 2) for k, v in shares.items()}
