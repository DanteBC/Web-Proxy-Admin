import os
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings


class ProxyConfigError(RuntimeError):
    pass


def atomic_write(path: str, content: str, mode: int = 0o640) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)

        if settings.proxy_user:
            try:
                account = pwd.getpwnam(settings.proxy_user)
                os.chown(target, account.pw_uid, account.pw_gid)
            except KeyError:
                pass
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def render_users(users) -> str:
    lines = []
    for user in users:
        if not user.enabled:
            continue
        safe_login = user.login.replace("\\n", "").replace("\\r", "")
        safe_password = user.proxy_password.replace("\\n", "").replace("\\r", "")
        lines.append(f"{safe_login}:CL:{safe_password}")
    return "\n".join(lines) + ("\n" if lines else "")


def validate_login(login: str) -> str:
    if not login or len(login) > 128:
        raise ProxyConfigError("Login must contain 1–128 characters")
    forbidden = set(" \t\n\r:$")
    if any(char in forbidden for char in login):
        raise ProxyConfigError("Login contains forbidden characters")
    return login


def reload_proxy() -> None:
    if shutil.which("systemctl") is None:
        raise ProxyConfigError("systemctl is not available")

    result = subprocess.run(
        ["systemctl", "reload", settings.proxy_service],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise ProxyConfigError(result.stderr.strip() or "Could not reload 3proxy")

    status = subprocess.run(
        ["systemctl", "is-active", settings.proxy_service],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if status.stdout.strip() != "active":
        raise ProxyConfigError("3proxy is not active after reload")
