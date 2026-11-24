from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.tables import UsageDaily
from app.api.statistics import user_usage


def test_user_usage_returns_month_summary_and_daily_rows():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    today = date.today()

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
    if today.day > 1:
        assert result["month"] == {"bytes_in": 400, "bytes_out": 600, "sessions": 5}
        assert [row["day"] for row in result["days"]] == [
            today.isoformat(),
            today.replace(day=1).isoformat(),
        ]
    else:
        assert result["month"] == result["today"]
        assert [row["day"] for row in result["days"]] == [today.isoformat()]
