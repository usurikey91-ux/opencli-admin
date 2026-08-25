"""Tests for final-window detection wiring helpers."""

from backend.services.content_detection import configured_metric


def test_configured_metric_requires_explicit_supported_name():
    assert configured_metric({}) is None
    assert configured_metric({"content_monitoring": {"metric_name": "likes"}}) is None
    assert configured_metric({"content_monitoring": {"metric_name": "like_count"}}) == "like_count"
