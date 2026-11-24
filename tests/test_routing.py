import subprocess
from urllib.error import URLError

import pytest

from scripts import route_awg


def test_fetch_networks_retries_temporary_dns_failure(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"77.88.8.0/24\n"

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise URLError("temporary failure in name resolution")
        return Response()

    monkeypatch.setattr(route_awg.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(route_awg.time, "sleep", lambda _: None)

    assert route_awg.fetch_networks("https://example.test/ru.zone") == ["77.88.8.0/24"]
    assert len(calls) == 2
    assert calls[0][1] == route_awg.RU_FETCH_TIMEOUT


def test_refresh_remote_set_keeps_existing_set_after_retries_fail(monkeypatch, capsys):
    def fail_fetch(url):
        raise RuntimeError(f"Could not load list from {url}")

    monkeypatch.setattr(route_awg, "fetch_networks", fail_fetch)
    monkeypatch.setattr(
        route_awg,
        "atomic_replace",
        lambda *_: pytest.fail("The existing set must not be replaced on fetch failure"),
    )

    assert not route_awg.refresh_remote_set("ru-direct", "https://example.test/ru.zone")
    assert "Keeping the existing ru-direct ipset" in capsys.readouterr().err


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


def test_status_runs_netfilter_queries_and_uses_requested_table(monkeypatch):
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=f"output from {args[0]}\n", stderr="")

    monkeypatch.setattr(route_awg, "run", fake_run)

    output = route_awg.status("200")

    assert set(output) == {"ipsets", "iptables", "rules", "routes"}
    assert ("ipset", "list") in calls
    assert ("iptables", "-t", "mangle", "-n", "-v", "-L", "WEBPROXY_AWG") in calls
    assert ("ip", "route", "show", "table", "200") in calls
