"""Tests for final-window detection wiring helpers."""

from backend.services.content_detection import configured_metric, configured_metrics


def test_configured_metric_requires_explicit_supported_name():
    assert configured_metric({}) is None
    assert configured_metric({"content_monitoring": {"metric_name": "likes"}}) is None
    assert configured_metric({"content_monitoring": {"metric_name": "like_count"}}) == "like_count"


def test_configured_metrics_defaults_to_supported_public_metrics_when_monitoring_enabled():
    metrics = configured_metrics({"content_monitoring": {}})
    assert metrics == [
        "view_count",
        "like_count",
        "comment_count",
        "favorite_count",
        "share_count",
    ]
