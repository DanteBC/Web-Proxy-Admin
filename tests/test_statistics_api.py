from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.tables import UsageDaily
from app.api.statistics import user_usage
from app.core.config import settings


def test_user_usage_returns_month_summary_daily_rows_and_recent_websites(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    today = date.today()
    log_file = tmp_path / "3proxy.log"
    log_file.write_text(
        r" 1795690934\talice\t10.0.0.2\t93.184.216.34\t100\t200\t00000\t3128\tCONNECT example.com:443 HTTP/1.1"
        "\n"
        r" 1795690935\talice\t10.0.0.2\t93.184.216.34\t100\t200\t00000\t3128\tGET https://example.com/path HTTP/1.1"
        "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "proxy_log_file", str(log_file))

    with Session(engine) as db:
        rows = [
            UsageDaily(
                proxy_user="alice",
                day=today,
                bytes_in=100,
                bytes_out=200,
                sessions=2,
            ),
            UsageDaily(
                proxy_user="alice",
                day=today.replace(day=1) - timedelta(days=1),
                bytes_in=900,
                bytes_out=900,
                sessions=9,
            ),
        ]
        if today.day > 1:
            rows.append(
                UsageDaily(
                    proxy_user="alice",
                    day=today.replace(day=1),
                    bytes_in=300,
                    bytes_out=400,
                    sessions=3,
                )
            )
        db.add_all(rows)
        db.commit()

        result = user_usage(username="alice", db=db)

    assert result["today"] == {"bytes_in": 100, "bytes_out": 200, "sessions": 2}
    assert result["recent_websites"] == [
        {"domain": "example.com", "last_accessed": datetime.fromtimestamp(1795690935).isoformat()}
    ]
    if today.day > 1:
        assert result["month"] == {"bytes_in": 400, "bytes_out": 600, "sessions": 5}
        assert [row["day"] for row in result["days"]] == [
            today.isoformat(),
            today.replace(day=1).isoformat(),
        ]
    else:
        assert result["month"] == result["today"]
        assert [row["day"] for row in result["days"]] == [today.isoformat()]
