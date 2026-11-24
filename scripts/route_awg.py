#!/usr/bin/env python3
import argparse
import fcntl
import ipaddress
import os
import pwd
import subprocess
import urllib.request
from pathlib import Path

TABLE = "100"
MARK = "1"
CHAIN = "WEBPROXY_AWG"
RU_SET = "ru-direct"
FORCE_SET = "awg-force"
LOCK = Path("/run/webproxy-routing.lock")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("This script requires root or CAP_NET_ADMIN")


def ensure_ipset(name: str) -> None:
    names = set(run("ipset", "list", "-name", check=False).stdout.split())
    if name not in names:
        run("ipset", "create", name, "hash:net", "family", "inet", "hashsize", "4096", "maxelem", "1048576")


def parse_networks(raw: bytes) -> list[str]:
    result = []
    for line in raw.decode("utf-8", "replace").splitlines():
        value = line.strip().split(";", 1)[0].split()[0] if line.strip() else ""
        if not value or value.startswith("#"):
            continue
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            continue
        if network.version == 4:
            result.append(str(network))
    if not result:
        raise ValueError("The loaded IPv4 list is empty")
    return result


def atomic_replace(name: str, networks: list[str]) -> None:
    temp = f"{name}-tmp"
    run("ipset", "destroy", temp, check=False)
    run("ipset", "create", temp, "hash:net", "family", "inet", "hashsize", "4096", "maxelem", "1048576")
    for network in networks:
        run("ipset", "add", temp, network)
    run("ipset", "swap", temp, name)
    run("ipset", "destroy", temp, check=False)


def ensure_jump(table: str, hook: str, spec: list[str]) -> None:
    if run("iptables", "-t", table, "-C", *spec, check=False).returncode != 0:
        run("iptables", "-t", table, "-A", *spec)


def configure_chain(proxy_uid: int | None, mark: str = MARK) -> None:
    if run("iptables", "-t", "mangle", "-n", "-L", CHAIN, check=False).returncode != 0:
        run("iptables", "-t", "mangle", "-N", CHAIN)
    run("iptables", "-t", "mangle", "-F", CHAIN)

    run("iptables", "-t", "mangle", "-A", CHAIN,
        "-m", "set", "--match-set", FORCE_SET, "dst",
        "-j", "MARK", "--set-mark", mark,
        "-m", "comment", "--comment", "webproxy-awg-force")

    run("iptables", "-t", "mangle", "-A", CHAIN,
        "-m", "set", "--match-set", RU_SET, "dst",
        "-j", "RETURN",
        "-m", "comment", "--comment", "webproxy-direct")

    run("iptables", "-t", "mangle", "-A", CHAIN,
        "-j", "MARK", "--set-mark", mark,
        "-m", "comment", "--comment", "webproxy-awg-default")

    if proxy_uid is not None:
        ensure_jump("mangle", "OUTPUT", [
            "OUTPUT", "-m", "owner", "--uid-owner", str(proxy_uid), "-j", CHAIN,
        ])


def configure_policy_route(interface: str, table: str = TABLE, mark: str = MARK, priority: str = "100") -> None:
    run("ip", "link", "show", "dev", interface)
    rules = run("ip", "rule", "show", check=False).stdout.splitlines()
    mark_value = mark.split("/", 1)[0]
    target_mark = int(mark_value, 16 if mark_value.lower().startswith("0x") else 10)
    target_table = int(table, 10) if table.isdecimal() else table
    rule_exists = False

    for line in rules:
        rule_priority, separator, body = line.partition(":")
        if not separator or rule_priority.strip() != priority:
            continue

        parts = body.split()
        try:
            mark_index = parts.index("fwmark") + 1
            table_index = parts.index("lookup") + 1
            existing_mark_value = parts[mark_index].split("/", 1)[0]
            existing_mark = int(
                existing_mark_value,
                16 if existing_mark_value.lower().startswith("0x") else 10,
            )
            raw_table = parts[table_index]
            existing_table = int(raw_table, 10) if raw_table.isdecimal() else raw_table
        except (ValueError, IndexError):
            raise RuntimeError(f"Routing priority {priority} is already in use: {line.strip()}")

        if existing_mark == target_mark and existing_table == target_table:
            rule_exists = True
            continue
        raise RuntimeError(f"Routing priority {priority} conflicts with an existing rule: {line.strip()}")

    run("ip", "route", "replace", "default", "dev", interface, "table", table)
    if not rule_exists:
        run("ip", "rule", "add", "priority", priority, "fwmark", mark, "lookup", table)


def add_networks(name: str, networks: list[str]) -> None:
    ensure_ipset(name)
    for network in networks:
        value = str(ipaddress.ip_network(network, strict=False))
        if ipaddress.ip_network(value).version == 4:
            run("ipset", "add", name, value, "-exist")


def remove_networks(name: str, networks: list[str]) -> None:
    for network in networks:
        run("ipset", "del", name, network, check=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ru-url")
    parser.add_argument("--ru-file")
    parser.add_argument("--direct", nargs="*")
    parser.add_argument("--force-awg", nargs="*")
    parser.add_argument("--remove-direct", nargs="*")
    parser.add_argument("--remove-force-awg", nargs="*")
    parser.add_argument("--interface", default="awg1")
    parser.add_argument("--proxy-user", default="3proxy")
    parser.add_argument("--table", default=TABLE)
    parser.add_argument("--mark", default=MARK)
    parser.add_argument("--priority", default="100")
    args = parser.parse_args()

    require_root()
    LOCK.parent.mkdir(parents=True, exist_ok=True)

    with LOCK.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ensure_ipset(RU_SET)
        ensure_ipset(FORCE_SET)

        if args.ru_url:
            request = urllib.request.Request(args.ru_url, headers={"User-Agent": "webproxy-routing/1.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                networks = parse_networks(response.read())
                atomic_replace(RU_SET, networks)
        elif args.ru_file:
            networks = parse_networks(Path(args.ru_file).read_bytes())
            atomic_replace(RU_SET, networks)

        if args.direct:
            add_networks(RU_SET, args.direct)
        if args.remove_direct:
            remove_networks(RU_SET, args.remove_direct)
        if args.force_awg:
            add_networks(FORCE_SET, args.force_awg)
        if args.remove_force_awg:
            remove_networks(FORCE_SET, args.remove_force_awg)

        try:
            proxy_uid = pwd.getpwnam(args.proxy_user).pw_uid
        except KeyError:
            proxy_uid = None

        configure_chain(proxy_uid, args.mark)
        configure_policy_route(args.interface, args.table, args.mark, args.priority)


if __name__ == "__main__":
    main()
