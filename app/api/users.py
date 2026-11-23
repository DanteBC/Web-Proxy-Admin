from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.tables import AuditLog, ProxyUser
from app.api.schemas import ProxyUserCreate, ProxyUserUpdate
from app.services.proxy_service import (
    ProxyConfigError,
    atomic_write,
    render_users,
    reload_proxy,
    validate_login,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def persist_users(db: Session) -> None:
    users = db.query(ProxyUser).order_by(ProxyUser.login).all()
    atomic_write(settings.proxy_users_file, render_users(users))


@router.get("")
def list_users(db: Session = Depends(get_db)):
    users = db.query(ProxyUser).order_by(ProxyUser.login).all()
    return [
        {
            "id": u.id,
            "login": u.login,
            "enabled": u.enabled,
            "max_bytes": u.max_bytes,
            "expire_at": u.expire_at,
            "source": u.source,
        }
        for u in users
    ]


@router.post("", status_code=201)
def create_user(payload: ProxyUserCreate, db: Session = Depends(get_db)):
    try:
        login = validate_login(payload.login)
    except ProxyConfigError as exc:
        raise HTTPException(422, str(exc))

    if db.query(ProxyUser).filter_by(login=login).first():
        raise HTTPException(409, "Login already exists")

    user = ProxyUser(
        login=login,
        proxy_password=payload.password,
        enabled=payload.enabled,
        max_bytes=payload.max_bytes,
        expire_at=payload.expire_at,
    )
    db.add(user)
    db.commit()

    try:
        persist_users(db)
        reload_proxy()
    except Exception:
        db.delete(user)
        db.commit()
        raise

    db.add(AuditLog(actor="admin", action="CREATE_PROXY_USER", target=login, detail=None))
    db.commit()
    return {"id": user.id, "login": user.login, "enabled": user.enabled}


@router.patch("/{user_id}")
def update_user(user_id: int, payload: ProxyUserUpdate, db: Session = Depends(get_db)):
    user = db.get(ProxyUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    old_snapshot = {
        "enabled": user.enabled,
        "max_bytes": user.max_bytes,
        "expire_at": user.expire_at,
    }
    if payload.password is not None:
        user.proxy_password = payload.password
    if payload.enabled is not None:
        user.enabled = payload.enabled
    if payload.max_bytes is not None:
        user.max_bytes = payload.max_bytes
    if payload.expire_at is not None:
        user.expire_at = payload.expire_at

    db.commit()
    try:
        persist_users(db)
        reload_proxy()
    except Exception:
        db.rollback()
        raise

    db.add(AuditLog(actor="admin", action="UPDATE_PROXY_USER", target=user.login, detail=str(old_snapshot)))
    db.commit()
    return {"id": user.id, "login": user.login, "enabled": user.enabled}


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(ProxyUser, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    login = user.login
    db.delete(user)
    db.commit()
    try:
        persist_users(db)
        reload_proxy()
    except Exception:
        raise

    db.add(AuditLog(actor="admin", action="DELETE_PROXY_USER", target=login, detail=None))
    db.commit()
    return {"deleted": True}
