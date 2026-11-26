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


def test_configure_masquerade_adds_marked_awg_rule(monkeypatch):
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

    monkeypatch.setattr(route_awg, "run", fake_run)

    route_awg.configure_masquerade("awg1", "0x1")

    expected = (
        "iptables", "-t", "nat", "-A", "POSTROUTING",
        "-o", "awg1", "-m", "mark", "--mark", "0x1",
        "-m", "comment", "--comment", "webproxy-awg-snat",
        "-j", "MASQUERADE",
    )
    assert expected in calls


def test_configure_chain_marks_only_new_connections_and_saves_connection_mark(monkeypatch):
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        returncode = 1 if args[:5] == ("iptables", "-t", "mangle", "-C", "OUTPUT") else 0
        return subprocess.CompletedProcess(args, returncode, stdout="", stderr="")

    monkeypatch.setattr(route_awg, "run", fake_run)

    route_awg.configure_chain(994, "1")

    chain_calls = [call for call in calls if call[:5] == ("iptables", "-t", "mangle", "-A", route_awg.CHAIN)]
    assert chain_calls[0] == (
        "iptables", "-t", "mangle", "-A", route_awg.CHAIN,
        "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED",
        "-j", "CONNMARK", "--restore-mark",
    )
    assert chain_calls[1] == (
        "iptables", "-t", "mangle", "-A", route_awg.CHAIN,
        "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED",
        "-j", "RETURN",
    )
    assert all(
        "--ctstate" in call and call[call.index("--ctstate") + 1] == "NEW"
        for call in chain_calls[2:]
    )
    assert any("-j" in call and call[call.index("-j") + 1] == "CONNMARK" for call in chain_calls)
    assert ("OUTPUT", "-m", "owner", "--uid-owner", "994", "-j", route_awg.CHAIN) in [
        call[4:] for call in calls if call[:4] == ("iptables", "-t", "mangle", "-A")
    ]


def test_status_runs_netfilter_queries_and_uses_requested_table(monkeypatch):
    calls = []

    def fake_run(*args, check=True):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=f"output from {args[0]}\n", stderr="")

    monkeypatch.setattr(route_awg, "run", fake_run)

    output = route_awg.status("200")

    assert set(output) == {"ipsets", "iptables", "nat", "rules", "routes"}
    assert ("ipset", "list") in calls
    assert ("iptables", "-t", "mangle", "-n", "-v", "-L", "WEBPROXY_AWG") in calls
    assert ("iptables", "-t", "nat", "-n", "-v", "-L", "POSTROUTING") in calls
    assert ("ip", "route", "show", "table", "200") in calls
