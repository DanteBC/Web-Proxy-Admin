from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tables import UsageDaily
from app.services.statistics import collect_usage

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


@router.post("/collect")
def collect(db: Session = Depends(get_db)):
    return {"rows_updated": collect_usage(db)}


@router.get("")
def usage(db: Session = Depends(get_db)):
    rows = db.query(UsageDaily).order_by(UsageDaily.day.desc(), UsageDaily.proxy_user).all()
    return [
        {
            "proxy_user": row.proxy_user,
            "day": row.day.isoformat(),
            "bytes_in": row.bytes_in,
            "bytes_out": row.bytes_out,
            "sessions": row.sessions,
        }
        for row in rows
    ]


@router.get("/user")
def user_usage(username: str = Query(min_length=1, max_length=128), db: Session = Depends(get_db)):
    today = date.today()
    month_start = today.replace(day=1)
    rows = (
        db.query(UsageDaily)
        .filter(UsageDaily.proxy_user == username, UsageDaily.day >= month_start)
        .order_by(UsageDaily.day.desc())
        .all()
    )

    month = {"bytes_in": 0, "bytes_out": 0, "sessions": 0}
    today_totals = {"bytes_in": 0, "bytes_out": 0, "sessions": 0}
    for row in rows:
        month["bytes_in"] += row.bytes_in
        month["bytes_out"] += row.bytes_out
        month["sessions"] += row.sessions
        if row.day == today:
            today_totals["bytes_in"] += row.bytes_in
            today_totals["bytes_out"] += row.bytes_out
            today_totals["sessions"] += row.sessions

    return {
        "proxy_user": username,
        "today": today_totals,
        "month": month,
        "days": [
            {
                "day": row.day.isoformat(),
                "bytes_in": row.bytes_in,
                "bytes_out": row.bytes_out,
                "sessions": row.sessions,
            }
            for row in rows
        ],
    }
