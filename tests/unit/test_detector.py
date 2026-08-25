"""Tests for the deterministic content detector."""

from backend.detector import (
    BASELINE_WINDOW,
    HOT_MULTIPLE,
    VERY_HOT_MULTIPLE,
    evaluate_public_metric,
)


BASELINE = [1_000] * BASELINE_WINDOW


def test_below_two_times_account_median_stays_observing():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=1_999,
        baseline_values=BASELINE,
    )

    assert decision.status == "observing"
    assert decision.baseline_value == 1_000
    assert decision.relative_multiple == 1.999
    assert decision.enters_analysis is False


def test_two_times_account_median_enters_normal_analysis_queue():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=2_000,
        baseline_values=BASELINE,
    )

    assert decision.status == "hot"
    assert decision.hot_multiple == HOT_MULTIPLE == 2.0
    assert decision.enters_analysis is True
    assert decision.priority_analysis is False


def test_five_times_account_median_enters_priority_analysis_queue():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=5_000,
        baseline_values=BASELINE,
    )

    assert decision.status == "very_hot"
    assert decision.very_hot_multiple == VERY_HOT_MULTIPLE == 5.0
    assert decision.enters_analysis is True
    assert decision.priority_analysis is True


def test_detector_uses_only_latest_twenty_valid_values():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=2_000,
        baseline_values=[None, -1, *BASELINE, 1_000_000],
    )

    assert decision.baseline_size == 20
    assert decision.baseline_value == 1_000
    assert decision.status == "hot"


def test_fewer_than_twenty_valid_works_is_insufficient():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=10_000,
        baseline_values=[1_000] * 19,
    )

    assert decision.status == "insufficient_data"
    assert decision.baseline_size == 19
    assert decision.enters_analysis is False


def test_missing_metric_or_zero_baseline_is_insufficient():
    missing = evaluate_public_metric(
        metric_name="like_count",
        current_value=None,
        baseline_values=BASELINE,
    )
    zero = evaluate_public_metric(
        metric_name="like_count",
        current_value=10,
        baseline_values=[0] * BASELINE_WINDOW,
    )

    assert missing.status == "insufficient_data"
    assert zero.status == "insufficient_data"
    assert zero.relative_multiple is None
