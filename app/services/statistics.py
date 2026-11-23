import os
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tables import UsageDaily


_LOG_FIELDS = re.compile(
    r"^(?P<timestamp>[^\t]+)\t"
    r"(?P<username>[^\t]*)\t"
    r"(?P<client>[^\t]*)\t"
    r"(?P<remote>[^\t]*)\t"
    r"(?P<bytes_in>\d+)\t"
    r"(?P<bytes_out>\d+)"
)


def parse_line(line: str) -> dict | None:
    match = _LOG_FIELDS.match(line.strip())
    if not match:
        return None

    raw_time = match.group("timestamp")
    try:
        parsed_time = datetime.fromisoformat(raw_time)
    except ValueError:
        try:
            parsed_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    return {
        "timestamp": parsed_time,
        "username": match.group("username") or "-",
        "client_ip": match.group("client") or None,
        "remote": match.group("remote") or None,
        "bytes_in": int(match.group("bytes_in")),
        "bytes_out": int(match.group("bytes_out")),
    }


def collect_usage(db: Session, log_file: str | None = None) -> int:
    path = Path(log_file or settings.proxy_log_file)
    if not path.exists():
        return 0

    totals = defaultdict(lambda: [0, 0, 0])

    with path.open("r", encoding="utf-8", errors="replace") as handle:
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
