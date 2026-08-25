"""Tests for the seven-day new-work snapshot policy."""

from datetime import datetime, timedelta, timezone

from backend.monitoring_policy import evaluate_snapshot_policy


NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def test_first_observation_is_stored_immediately():
    policy = evaluate_snapshot_policy(
        published_at=NOW - timedelta(hours=1),
        last_snapshot_at=None,
        now=NOW,
    )

    assert policy.phase == "first_seen"
    assert policy.due is True
    assert policy.next_due_at == NOW


def test_first_48_hours_use_fixed_four_hour_interval():
    published = NOW - timedelta(hours=20)
    last_snapshot = NOW - timedelta(hours=3, minutes=59)

    not_due = evaluate_snapshot_policy(
        published_at=published,
        last_snapshot_at=last_snapshot,
        now=NOW,
    )
    due = evaluate_snapshot_policy(
        published_at=published,
        last_snapshot_at=last_snapshot,
        now=NOW + timedelta(minutes=1),
    )

    assert not_due.phase == "early_4h"
    assert not_due.due is False
    assert due.due is True


def test_day_three_through_day_seven_use_daily_interval():
    policy = evaluate_snapshot_policy(
        published_at=NOW - timedelta(days=3),
        last_snapshot_at=NOW - timedelta(hours=24),
        now=NOW,
    )

    assert policy.phase == "daily"
    assert policy.due is True


def test_exact_48_hour_boundary_keeps_the_last_early_snapshot():
    policy = evaluate_snapshot_policy(
        published_at=NOW - timedelta(hours=48),
        last_snapshot_at=NOW - timedelta(hours=4),
        now=NOW,
    )

    assert policy.phase == "early_4h"
    assert policy.due is True


def test_monitoring_stops_at_seven_days():
    policy = evaluate_snapshot_policy(
        published_at=NOW - timedelta(days=7),
        last_snapshot_at=NOW - timedelta(days=1),
        now=NOW,
    )

    assert policy.phase == "stopped"
    assert policy.due is False
    assert policy.next_due_at is None
