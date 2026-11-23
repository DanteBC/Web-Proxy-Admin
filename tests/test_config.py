from types import SimpleNamespace

from app.services.proxy_service import render_users, validate_login


def test_validate_login():
    assert validate_login("alice") == "alice"


def test_reject_login_colon():
    import pytest
    from app.services.proxy_service import ProxyConfigError

    with pytest.raises(ProxyConfigError):
        validate_login("bad:login")


def test_render_users():
    users = [
        SimpleNamespace(login="alice", proxy_password="secret", enabled=True),
        SimpleNamespace(login="disabled", proxy_password="secret", enabled=False),
    ]
    assert render_users(users) == "alice:CL:secret\n"
