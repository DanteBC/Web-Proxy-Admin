import subprocess

from app.core.config import settings


class RoutingError(RuntimeError):
    pass


def apply_routing(extra_args: list[str] | None = None) -> str:
    command = ["sudo", "-n", "python3", settings.routing_script]
    command.extend(extra_args or ["--ru-url", settings.ru_url])

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RoutingError(result.stderr.strip() or "Routing application failed")
    return result.stdout


def status() -> dict:
    commands = {
        "ipsets": ["ipset", "list"],
        "iptables": ["iptables", "-t", "mangle", "-n", "-v", "-L", "WEBPROXY_AWG"],
        "rules": ["ip", "rule", "show"],
        "routes": ["ip", "route", "show", "table", "100"],
    }

    output = {}
    for name, command in commands.items():
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output[name] = result.stdout if result.returncode == 0 else f"ERROR: {result.stderr.strip()}"
    return output
