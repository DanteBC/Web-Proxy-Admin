from fastapi import APIRouter, Depends
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
