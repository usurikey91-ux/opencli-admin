"""Tests for the deterministic content detector."""

from backend.detector import evaluate_public_metric


def test_candidate_requires_absolute_and_relative_gates():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=5_000,
        baseline_values=[900, 1_000, 1_100, 1_200, 800],
        absolute_threshold=3_000,
        relative_threshold=2.0,
    )

    assert decision.status == "candidate"
    assert decision.absolute_pass is True
    assert decision.relative_pass is True
    assert decision.relative_multiple == 5.0


def test_relative_outlier_below_absolute_floor_stays_observing():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=500,
        baseline_values=[80, 90, 100, 110, 120],
        absolute_threshold=3_000,
        relative_threshold=2.0,
    )

    assert decision.status == "observing"
    assert decision.absolute_pass is False
    assert decision.relative_pass is True


def test_absolute_hit_without_relative_lift_stays_observing():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=5_000,
        baseline_values=[4_000, 4_500, 5_000, 5_500, 6_000],
        absolute_threshold=3_000,
        relative_threshold=2.0,
    )

    assert decision.status == "observing"
    assert decision.absolute_pass is True
    assert decision.relative_pass is False


def test_missing_or_zero_baseline_is_insufficient():
    too_small = evaluate_public_metric(
        metric_name="view_count",
        current_value=10_000,
        baseline_values=[1_000, 2_000],
        absolute_threshold=5_000,
        relative_threshold=2.0,
    )
    zero = evaluate_public_metric(
        metric_name="view_count",
        current_value=10_000,
        baseline_values=[0, 0, 0, 0, 0],
        absolute_threshold=5_000,
        relative_threshold=2.0,
    )

    assert too_small.status == "insufficient_data"
    assert zero.status == "insufficient_data"
    assert zero.relative_multiple is None
