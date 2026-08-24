def confidence_score(
    *,
    temporal_density: float,
    sensor_agreement: float,
    classifier_prob: float,
    spatial_support: float,
    historical_consistency: float,
    model_uncertainty: float,
    field_level_source_agreement: float | None = None,
) -> float:
    """Versioned confidence model (v2). Adds an optional field_level_source_agreement
    component -- populated when a field-level source such as AMED (India only)
    independently corroborates the coarser pixel-based classification. When the
    component is absent (non-India countries, or India before AMED is wired in),
    its weight is redistributed proportionally rather than silently dropped,
    so the same six components keep summing to a comparable [0,1] score."""
    base_weights = {
        "temporal_density": 0.20,
        "sensor_agreement": 0.20,
        "classifier_prob": 0.20,
        "spatial_support": 0.15,
        "historical_consistency": 0.15,
        "model_uncertainty": 0.10,  # applied as (1 - model_uncertainty)
    }
    values = {
        "temporal_density": temporal_density,
        "sensor_agreement": sensor_agreement,
        "classifier_prob": classifier_prob,
        "spatial_support": spatial_support,
        "historical_consistency": historical_consistency,
        "model_uncertainty": 1 - model_uncertainty,
    }

    if field_level_source_agreement is not None:
        field_weight = 0.15
        scale = 1 - field_weight
        weights = {k: w * scale for k, w in base_weights.items()}
        score = sum(weights[k] * values[k] for k in weights) + field_weight * field_level_source_agreement
    else:
        score = sum(base_weights[k] * values[k] for k in base_weights)

    return max(0.0, min(1.0, score))


def confidence_label(score: float) -> str:
    return "high" if score >= 0.8 else "medium" if score >= 0.6 else "low"


def penalize_for_staleness(score: float, observation_gap_days: float | None) -> float:
    """§110 of the review doc: confidence must fall when the latest direct
    observation is old, even if the metric is still available via model
    propagation/interpolation."""
    if observation_gap_days is None:
        return score
    if observation_gap_days <= 5:
        penalty = 0.0
    elif observation_gap_days <= 10:
        penalty = 0.05
    elif observation_gap_days <= 20:
        penalty = 0.15
    else:
        penalty = 0.30
    return max(0.0, round(score - penalty, 4))
