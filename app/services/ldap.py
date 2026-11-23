from app.core.config import settings


def authenticate(username: str, password: str) -> bool:
    if not settings.ldap_enabled:
        return False

    try:
        from ldap3 import AUTO_BIND_TLS_BEFORE_BIND, Connection, Server
    except ImportError:
        return False

    server = Server(settings.ldap_server, get_info=None)
    conn = Connection(server, settings.ldap_bind_dn, settings.ldap_bind_password, auto_bind=AUTO_BIND_TLS_BEFORE_BIND)

    search_filter = settings.ldap_user_filter.format(username=username.replace("\\", "\\\\").replace("*", "\\2a").replace("(", "\\28").replace(")", "\\29"))
    if not conn.search(settings.ldap_user_base, search_filter, attributes=["dn"]):
        return False

    user_dn = conn.entries[0].entry_dn
    user_conn = Connection(server, user_dn, password)
    return user_conn.bound
