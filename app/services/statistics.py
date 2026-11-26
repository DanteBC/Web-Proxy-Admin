import gzip
import ipaddress
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tables import UsageDaily


_ROTATED_LOG = re.compile(r"(?:\.\d+|\.\d{4}\.\d{2}\.\d{2}|\.\d{8})(?:\.gz)?$")


def _extract_website(request: str) -> str | None:
    parts = request.strip().split()
    if len(parts) < 2:
        return None

    method, target = parts[0].upper(), parts[1]
    try:
        if method == "CONNECT":
            url = urlsplit(f"//{target}")
        else:
            url = urlsplit(target)
            if url.scheme not in {"http", "https"}:
                return None
        hostname = url.hostname
    except ValueError:
        return None

    if not hostname:
        return None

    hostname = hostname.rstrip(".").lower()
    try:
        ipaddress.ip_address(hostname)
        return None
    except ValueError:
        pass

    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def parse_line(line: str) -> dict | None:
    fields = line.rstrip("\r\n").replace(r"\t", "\t").split("\t")
    if len(fields) < 6:
        return None

    raw_time = fields[0].strip()
    if raw_time.startswith("- "):
        raw_time = raw_time[2:].strip()

    if raw_time.isdecimal():
        try:
            parsed_time = datetime.fromtimestamp(float(raw_time))
        except (OverflowError, OSError, ValueError):
            return None
    else:
        try:
            parsed_time = datetime.fromisoformat(raw_time)
        except ValueError:
            try:
                parsed_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None

    try:
        bytes_in = int(fields[4])
        bytes_out = int(fields[5])
    except ValueError:
        return None

    if len(fields) > 8 and fields[8].lstrip().startswith("Accepting connections"):
        return None

    return {
        "timestamp": parsed_time,
        "username": fields[1].strip() or "-",
        "client_ip": fields[2] or None,
        "remote": fields[3] or None,
        "bytes_in": bytes_in,
        "bytes_out": bytes_out,
        "website": _extract_website(fields[8]) if len(fields) > 8 else None,
    }


def _log_files(path: Path) -> list[Path]:
    files = []
    if path.is_file():
        files.append(path)
    files.extend(
        candidate
        for candidate in path.parent.glob(f"{path.name}.*")
        if candidate.is_file() and _ROTATED_LOG.search(candidate.name[len(path.name):])
    )
    return sorted(files)


def _open_log(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def get_recent_websites(
    username: str,
    log_file: str | None = None,
) -> list[dict[str, str]]:
    path = Path(log_file or settings.proxy_log_file)
    last_access_by_website: dict[str, tuple[float, datetime]] = {}

    for log_path in _log_files(path):
        with _open_log(log_path) as handle:
            for line in handle:
                record = parse_line(line)
                if not record or record["username"] != username or not record["website"]:
                    continue
                website = record["website"]
                accessed_at = record["timestamp"]
                accessed_timestamp = accessed_at.timestamp()
                previous_access = last_access_by_website.get(website)
                if previous_access is None or accessed_timestamp > previous_access[0]:
                    last_access_by_website[website] = (accessed_timestamp, accessed_at)

    return [
        {"domain": website, "last_accessed": accessed_at.isoformat()}
        for website, (_, accessed_at) in sorted(
            last_access_by_website.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[:10]
    ]


def collect_usage(db: Session, log_file: str | None = None) -> int:
    path = Path(log_file or settings.proxy_log_file)
    files = _log_files(path)
    if not files:
        return 0

    totals = defaultdict(lambda: [0, 0, 0])

    for log_path in files:
        with _open_log(log_path) as handle:
            for line in handle:
                record = parse_line(line)
                if not record:
                    continue
                day = record["timestamp"].date()
                key = (record["username"], day)
                totals[key][0] += record["bytes_in"]
                totals[key][1] += record["bytes_out"]
                totals[key][2] += 1

    written = 0
    for (login, day), (bytes_in, bytes_out, sessions) in totals.items():
        row = db.get(UsageDaily, (login, day))
        if row:
            row.bytes_in = bytes_in
            row.bytes_out = bytes_out
            row.sessions = sessions
        else:
            db.add(UsageDaily(
                proxy_user=login,
                day=day,
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                sessions=sessions,
            ))
        written += 1

    db.commit()
    return written
