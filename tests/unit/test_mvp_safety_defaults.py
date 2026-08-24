"""Regression tests for the local-only MVP deployment boundary."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_compose_publishes_services_on_loopback_only():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"${API_PORT:-8031}:8000"' not in compose
    assert '"${FRONTEND_PORT:-8030}:80"' not in compose
    assert '"${AGENT1_PORT:-19823}:19823"' not in compose
    assert '"127.0.0.1:${API_PORT:-8031}:8000"' in compose
    assert '"127.0.0.1:${FRONTEND_PORT:-8030}:80"' in compose
    assert '"127.0.0.1:${AGENT1_PORT:-19823}:19823"' in compose


def test_compose_does_not_mount_docker_control_socket():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "/var/run/docker.sock" not in compose
    assert "user: root" not in compose


def test_agent_and_api_images_pin_the_same_opencli_version():
    api_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    agent_dockerfile = (ROOT / "agent" / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG OPENCLI_VERSION=1.7.4" in api_dockerfile
    assert "ARG OPENCLI_VERSION=1.7.4" in agent_dockerfile
