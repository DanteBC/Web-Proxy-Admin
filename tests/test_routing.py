import subprocess

import pytest

from scripts import route_awg


def test_policy_route_adds_rule_and_default_route(monkeypatch):
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        stdout = "" if args[:3] != ("ip", "rule", "show") else "0: from all lookup local\n"
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(route_awg, "run", fake_run)

    route_awg.configure_policy_route("awg1", "100", "1", "100")

    assert ("ip", "route", "replace", "default", "dev", "awg1", "table", "100") in calls
    assert ("ip", "rule", "add", "priority", "100", "fwmark", "1", "lookup", "100") in calls


def test_policy_route_does_not_duplicate_existing_hex_mark(monkeypatch):
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        stdout = "100: from all fwmark 0x1 lookup 100\n" if args[:3] == ("ip", "rule", "show") else ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(route_awg, "run", fake_run)

    route_awg.configure_policy_route("awg1", "100", "1", "100")

    assert any(call[:3] == ("ip", "route", "replace") for call in calls)
    assert not any(call[:3] == ("ip", "rule", "add") for call in calls)


def test_policy_route_refuses_priority_conflict_before_route_change(monkeypatch):
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        stdout = "100: from all fwmark 0x2 lookup 100\n" if args[:3] == ("ip", "rule", "show") else ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(route_awg, "run", fake_run)

    with pytest.raises(RuntimeError, match="conflicts"):
        route_awg.configure_policy_route("awg1", "100", "1", "100")

    assert not any(call[:3] == ("ip", "route", "replace") for call in calls)
