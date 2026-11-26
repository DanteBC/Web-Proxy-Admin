import json
import subprocess

from app.core.config import settings


class RoutingError(RuntimeError):
    pass


def apply_routing(extra_args: list[str] | None = None) -> str:
    command = ["sudo", "-n", settings.routing_script]
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
    try:
        result = subprocess.run(
            ["sudo", "-n", settings.routing_script, "--status", "--table", settings.routing_table],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RoutingError(f"Could not read routing status: {exc}") from exc

    if result.returncode != 0:
        raise RoutingError(result.stderr.strip() or "Routing status command failed")

    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RoutingError("Routing status helper returned invalid JSON") from exc

    if not isinstance(output, dict) or not all(
        isinstance(output.get(name), str) for name in ("ipsets", "iptables", "nat", "rules", "routes")
    ):
        raise RoutingError("Routing status helper returned an unexpected response")
    return output
