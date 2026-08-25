"""Tests for the deterministic content detector."""

import pytest

from backend.detector import evaluate_public_metric


def test_below_hot_threshold_stays_observing():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=2_999,
        hot_threshold=3_000,
        very_hot_threshold=10_000,
    )

    assert decision.status == "observing"
    assert decision.enters_analysis is False
    assert decision.priority_analysis is False


def test_hot_work_enters_normal_analysis_queue():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=5_000,
        hot_threshold=3_000,
        very_hot_threshold=10_000,
    )

    assert decision.status == "hot"
    assert decision.enters_analysis is True
    assert decision.priority_analysis is False


def test_very_hot_work_enters_priority_analysis_queue():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=10_000,
        hot_threshold=3_000,
        very_hot_threshold=10_000,
    )

    assert decision.status == "very_hot"
    assert decision.enters_analysis is True
    assert decision.priority_analysis is True


def test_missing_metric_is_insufficient_without_account_baseline():
    decision = evaluate_public_metric(
        metric_name="view_count",
        current_value=None,
        hot_threshold=5_000,
        very_hot_threshold=20_000,
    )

    assert decision.status == "insufficient_data"
    assert decision.enters_analysis is False


@pytest.mark.parametrize(
    ("hot_threshold", "very_hot_threshold"),
    [(-1, 10), (10, 10), (10, 9)],
)
def test_thresholds_must_be_explicit_and_ordered(hot_threshold, very_hot_threshold):
    with pytest.raises(ValueError):
        evaluate_public_metric(
            metric_name="like_count",
            current_value=20,
            hot_threshold=hot_threshold,
            very_hot_threshold=very_hot_threshold,
        )
