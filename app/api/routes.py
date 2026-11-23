import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import RouteRuleCreate
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

    args = ["--ru-url", "https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone"]
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
    return status()
