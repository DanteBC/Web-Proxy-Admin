import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import RouteRuleCreate
from app.core.config import settings
from app.core.database import get_db
from app.models.tables import RouteRule
from app.services.routing import RoutingError, apply_routing, status

router = APIRouter(prefix="/api/routes", tags=["routes"])


@router.get("")
def list_rules(db: Session = Depends(get_db)):
    rules = db.query(RouteRule).order_by(RouteRule.kind, RouteRule.cidr).all()
    return [
        {"id": r.id, "cidr": r.cidr, "kind": r.kind, "comment": r.comment, "enabled": r.enabled}
        for r in rules
    ]


@router.post("", status_code=201)
def create_rule(payload: RouteRuleCreate, db: Session = Depends(get_db)):
    if payload.kind not in {"DIRECT", "AWG"}:
        raise HTTPException(422, "kind must be DIRECT or AWG")

    try:
        cidr = str(ipaddress.ip_network(payload.cidr, strict=False))
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    if db.query(RouteRule).filter_by(cidr=cidr, kind=payload.kind).first():
        raise HTTPException(409, "Rule already exists")

    rule = RouteRule(cidr=cidr, kind=payload.kind, comment=payload.comment, enabled=payload.enabled)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "cidr": rule.cidr, "kind": rule.kind, "comment": rule.comment, "enabled": rule.enabled}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(RouteRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


@router.post("/apply")
def apply(db: Session = Depends(get_db)):
    direct = [r.cidr for r in db.query(RouteRule).filter_by(kind="DIRECT", enabled=True).all()]
    awg = [r.cidr for r in db.query(RouteRule).filter_by(kind="AWG", enabled=True).all()]

    args = [
        "--interface", settings.awg_interface,
        "--table", settings.routing_table,
        "--mark", settings.routing_mark,
        "--priority", str(settings.routing_priority),
    ]
    if settings.ru_file:
        args += ["--ru-file", settings.ru_file]
    else:
        args += ["--ru-url", settings.ru_url]
    if direct:
        args += ["--direct", *direct]
    if awg:
        args += ["--force-awg", *awg]

    try:
        return {"output": apply_routing(args)}
    except RoutingError as exc:
        raise HTTPException(500, str(exc))


@router.get("/status")
def route_status():
    try:
        return status()
    except RoutingError as exc:
        raise HTTPException(500, str(exc)) from exc
