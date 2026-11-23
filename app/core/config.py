from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEBPROXY_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./webproxy.db"
    session_secret: str = "change-me-in-production"

    admin_login: str = "admin"
    admin_password: str = "admin"

    ldap_enabled: bool = False
    ldap_server: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base: str = ""
    ldap_user_filter: str = "(sAMAccountName={username})"

    proxy_config: str = "/etc/3proxy/3proxy.cfg"
    proxy_users_file: str = "/etc/3proxy/users"
    proxy_log_file: str = "/var/log/3proxy/3proxy.log"
    proxy_service: str = "3proxy.service"
    proxy_user: str = "3proxy"

    routing_script: str = "/usr/local/sbin/webproxy-routing"
    ru_url: str = "https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone"


settings = Settings()
