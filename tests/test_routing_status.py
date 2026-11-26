import json
import subprocess

import pytest

from app.core.config import settings
from app.services import routing


def test_status_calls_privileged_read_only_helper(monkeypatch):
    expected = {"ipsets": "sets", "iptables": "chain", "nat": "nat", "rules": "rules", "routes": "routes"}
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(expected), stderr="")

    monkeypatch.setattr(routing.subprocess, "run", fake_run)
    monkeypatch.setattr(settings, "routing_script", "/usr/local/sbin/webproxy-routing")
    monkeypatch.setattr(settings, "routing_table", "200")

    assert routing.status() == expected
    assert calls[0][0] == [
        "sudo", "-n", "/usr/local/sbin/webproxy-routing", "--status", "--table", "200"
    ]
    assert calls[0][1]["timeout"] == 10


def test_status_surfaces_sudo_failure(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="sudo: a password is required")

    monkeypatch.setattr(routing.subprocess, "run", fake_run)

    with pytest.raises(routing.RoutingError, match="password is required"):
        routing.status()


def test_status_rejects_invalid_helper_output(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="not json", stderr="")

    monkeypatch.setattr(routing.subprocess, "run", fake_run)

    with pytest.raises(routing.RoutingError, match="invalid JSON"):
        routing.status()
