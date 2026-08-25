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
        finalized=True,
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
        finalized=True,
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
        finalized=True,
    )

    assert decision.status == "very_hot"
    assert decision.very_hot_multiple == VERY_HOT_MULTIPLE == 5.0
    assert decision.enters_analysis is True
    assert decision.priority_analysis is True


def test_missing_metric_in_latest_twenty_is_not_replaced_by_older_work():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=2_000,
        baseline_values=[None, *([1_000] * 19), 1_000_000],
        finalized=True,
    )

    assert decision.baseline_size == 20
    assert decision.baseline_missing_count == 1
    assert decision.baseline_value is None
    assert decision.status == "insufficient_data"


def test_fewer_than_twenty_valid_works_is_insufficient():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=10_000,
        baseline_values=[1_000] * 19,
        finalized=True,
    )

    assert decision.status == "insufficient_data"
    assert decision.baseline_size == 19
    assert decision.baseline_missing_count == 0
    assert decision.enters_analysis is False


def test_missing_metric_or_zero_baseline_is_insufficient():
    missing = evaluate_public_metric(
        metric_name="like_count",
        current_value=None,
        baseline_values=BASELINE,
        finalized=True,
    )
    zero = evaluate_public_metric(
        metric_name="like_count",
        current_value=10,
        baseline_values=[0] * BASELINE_WINDOW,
        finalized=True,
    )

    assert missing.status == "insufficient_data"
    assert zero.status == "insufficient_data"
    assert zero.relative_multiple is None


def test_non_final_work_never_enters_analysis_queue():
    decision = evaluate_public_metric(
        metric_name="like_count",
        current_value=10_000,
        baseline_values=BASELINE,
        finalized=False,
    )

    assert decision.status == "pending_final_window"
    assert decision.enters_analysis is False
    assert decision.priority_analysis is False
