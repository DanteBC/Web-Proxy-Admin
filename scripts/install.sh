#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="web-proxy"
APP_USER="webproxy"
APP_GROUP="webproxy"
INSTALL_DIR="/opt/web-proxy"
ENV_FILE="/etc/web-proxy.env"
SERVICE_NAME="webproxy.service"
ROUTING_SCRIPT="/usr/local/sbin/webproxy-routing"
SUDOERS_FILE="/etc/sudoers.d/webproxy-routing"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
    fail "Run this installer as root: sudo $0"
fi

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ -f "${SOURCE_DIR}/pyproject.toml" ]] || fail "Could not locate project root"
[[ -f "${SOURCE_DIR}/scripts/route_awg.py" ]] || fail "Routing helper is missing"

[[ -r /etc/os-release ]] || fail "Cannot identify Linux distribution"
# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}" in
    debian|ubuntu) ;;
    *) fail "This installer supports Debian and Ubuntu; detected '${ID:-unknown}'" ;;
esac

command -v apt-get >/dev/null || fail "apt-get is required"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    ca-certificates \
    iproute2 \
    ipset \
    iptables \
    openssl \
    python3 \
    python3-venv \
    sudo

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "Python 3.11 or newer is required"

if ! getent group "${APP_GROUP}" >/dev/null; then
    groupadd --system "${APP_GROUP}"
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --gid "${APP_GROUP}" --home-dir "${INSTALL_DIR}" \
        --shell /usr/sbin/nologin "${APP_USER}"
fi

install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${INSTALL_DIR}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 /var/lib/web-proxy

# Copy source without local environments, credentials, caches, or database files.
tar -C "${SOURCE_DIR}" \
    --exclude='./.git' \
    --exclude='./.venv' \
    --exclude='./.env' \
    --exclude='./*.db' \
    --exclude='./.pytest_cache' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -cf - . | tar -C "${INSTALL_DIR}" -xf -
chown -R "${APP_USER}:${APP_GROUP}" "${INSTALL_DIR}"

runuser -u "${APP_USER}" -- python3 -m venv "${INSTALL_DIR}/.venv"
runuser -u "${APP_USER}" -- "${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade pip
runuser -u "${APP_USER}" -- "${INSTALL_DIR}/.venv/bin/python" -m pip install "${INSTALL_DIR}"

install -o root -g root -m 0750 "${INSTALL_DIR}/scripts/route_awg.py" "${ROUTING_SCRIPT}"

read_env_value() {
    local key="$1"
    local fallback="$2"
    local value=""

    if [[ -f "${ENV_FILE}" ]]; then
        value="$(awk -F= -v key="${key}" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${ENV_FILE}")"
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
    fi

    printf '%s' "${value:-${fallback}}"
}

if [[ -e "${ENV_FILE}" ]]; then
    WEB_HOST="$(read_env_value WEBPROXY_WEB_HOST "${WEBPROXY_WEB_HOST:-127.0.0.1}")"
    AWG_INTERFACE="$(read_env_value WEBPROXY_AWG_INTERFACE awg1)"
    ROUTING_TABLE="$(read_env_value WEBPROXY_ROUTING_TABLE 100)"
    ROUTING_MARK="$(read_env_value WEBPROXY_ROUTING_MARK 1)"
    ROUTING_PRIORITY="$(read_env_value WEBPROXY_ROUTING_PRIORITY 100)"
    RU_URL="$(read_env_value WEBPROXY_RU_URL https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone)"
    PROXY_USER="$(read_env_value WEBPROXY_PROXY_USER 3proxy)"
    PROXY_SERVICE="$(read_env_value WEBPROXY_PROXY_SERVICE 3proxy.service)"
else
    WEB_HOST="${WEBPROXY_WEB_HOST:-127.0.0.1}"
    AWG_INTERFACE="${WEBPROXY_AWG_INTERFACE:-awg1}"
    ROUTING_TABLE="${WEBPROXY_ROUTING_TABLE:-100}"
    ROUTING_MARK="${WEBPROXY_ROUTING_MARK:-1}"
    ROUTING_PRIORITY="${WEBPROXY_ROUTING_PRIORITY:-100}"
    RU_URL="${WEBPROXY_RU_URL:-https://www.ipdeny.com/ipv4-aggregated/ru-aggregated.zone}"
    PROXY_USER="${WEBPROXY_PROXY_USER:-3proxy}"
    PROXY_SERVICE="${WEBPROXY_PROXY_SERVICE:-3proxy.service}"
fi

if ! python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "${WEB_HOST}" 2>/dev/null; then
    fail "WEBPROXY_WEB_HOST must be a valid IPv4 or IPv6 address"
fi

[[ "${AWG_INTERFACE}" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail "Invalid AWG interface name"
[[ "${ROUTING_TABLE}" =~ ^[0-9]+$ ]] || fail "Routing table must be numeric"
[[ "${ROUTING_PRIORITY}" =~ ^[0-9]+$ ]] || fail "Routing priority must be numeric"
[[ "${ROUTING_MARK}" =~ ^(0[xX][[:xdigit:]]+|[0-9]+)(/(0[xX][[:xdigit:]]+|[0-9]+))?$ ]] \
    || fail "Invalid routing mark"
[[ "${RU_URL}" =~ ^https://[a-zA-Z0-9._/-]+$ ]] || fail "RU list URL must be a plain HTTPS URL"
[[ "${PROXY_USER}" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*[$]?$ ]] || fail "Invalid 3proxy system user"
[[ "${PROXY_SERVICE}" =~ ^[a-zA-Z0-9_.@:-]+$ ]] || fail "Invalid 3proxy systemd service name"

if [[ ! -e "${ENV_FILE}" ]]; then
    ADMIN_LOGIN="${WEBPROXY_ADMIN_LOGIN:-admin}"
    ADMIN_PASSWORD="${WEBPROXY_ADMIN_PASSWORD:-$(openssl rand -hex 18)}"
    SESSION_SECRET="${WEBPROXY_SESSION_SECRET:-$(openssl rand -hex 32)}"
    [[ "${ADMIN_LOGIN}" =~ ^[a-zA-Z0-9_.@-]+$ ]] || fail "Admin login contains unsupported characters"
    [[ "${ADMIN_PASSWORD}" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail "Admin password must contain only letters, digits, dot, underscore, or hyphen"
    [[ "${SESSION_SECRET}" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail "Session secret contains unsupported characters"

    install -o root -g root -m 0600 /dev/null "${ENV_FILE}"
    cat >"${ENV_FILE}" <<EOF
WEBPROXY_DATABASE_URL=sqlite:////var/lib/web-proxy/webproxy.db
WEBPROXY_SESSION_SECRET=${SESSION_SECRET}
WEBPROXY_ADMIN_LOGIN=${ADMIN_LOGIN}
WEBPROXY_ADMIN_PASSWORD=${ADMIN_PASSWORD}
WEBPROXY_WEB_HOST=${WEB_HOST}
WEBPROXY_PROXY_CONFIG=/etc/3proxy/3proxy.cfg
WEBPROXY_PROXY_USERS_FILE=/var/lib/web-proxy/users
WEBPROXY_PROXY_LOG_FILE=/var/log/3proxy/3proxy.log
WEBPROXY_PROXY_SERVICE=${PROXY_SERVICE}
WEBPROXY_PROXY_USER=${PROXY_USER}
WEBPROXY_ROUTING_SCRIPT=${ROUTING_SCRIPT}
WEBPROXY_RU_URL=${RU_URL}
WEBPROXY_AWG_INTERFACE=${AWG_INTERFACE}
WEBPROXY_ROUTING_TABLE=${ROUTING_TABLE}
WEBPROXY_ROUTING_MARK=${ROUTING_MARK}
WEBPROXY_ROUTING_PRIORITY=${ROUTING_PRIORITY}
EOF
    chmod 0600 "${ENV_FILE}"
    CREATED_CREDENTIALS=1
else
    CREATED_CREDENTIALS=0
    if grep -q '^WEBPROXY_WEB_HOST=' "${ENV_FILE}"; then
        sed -i "s|^WEBPROXY_WEB_HOST=.*|WEBPROXY_WEB_HOST=${WEB_HOST}|" "${ENV_FILE}"
    else
        printf '\nWEBPROXY_WEB_HOST=%s\n' "${WEB_HOST}" >>"${ENV_FILE}"
    fi
    chown root:root "${ENV_FILE}"
    chmod 0600 "${ENV_FILE}"
    printf 'Keeping existing environment file: %s\n' "${ENV_FILE}"
fi

if id "${PROXY_USER}" >/dev/null 2>&1; then
    if ! id -nG "${PROXY_USER}" | tr ' ' '\n' | grep -Fxq "${APP_GROUP}"; then
        usermod -a -G "${APP_GROUP}" "${PROXY_USER}"
        PROXY_GROUP_UPDATED=1
    else
        PROXY_GROUP_UPDATED=0
    fi
else
    PROXY_GROUP_UPDATED=0
    printf 'WARNING: system user %s does not exist; verify 3proxy can read %s.\n' \
        "${PROXY_USER}" "/var/lib/web-proxy/users" >&2
fi

if id "${PROXY_USER}" >/dev/null 2>&1; then
    PROXY_PRIMARY_GROUP="$(id -gn "${PROXY_USER}")"
    if [[ "${PROXY_PRIMARY_GROUP}" != "${APP_GROUP}" ]]; then
        usermod -a -G "${PROXY_PRIMARY_GROUP}" "${APP_USER}"
        install -d -o root -g root -m 0755 "/etc/systemd/system/${SERVICE_NAME}.d"
        cat >"/etc/systemd/system/${SERVICE_NAME}.d/proxy-group.conf" <<EOF
[Service]
SupplementaryGroups=${PROXY_PRIMARY_GROUP}
EOF
        chmod 0644 "/etc/systemd/system/${SERVICE_NAME}.d/proxy-group.conf"
    fi
fi

SUDOERS_TMP="$(mktemp)"
trap 'rm -f "${SUDOERS_TMP}"' EXIT
cat >"${SUDOERS_TMP}" <<EOF
${APP_USER} ALL=(root) NOPASSWD: ${ROUTING_SCRIPT} --interface ${AWG_INTERFACE} --table ${ROUTING_TABLE} --mark ${ROUTING_MARK} --priority ${ROUTING_PRIORITY} --ru-url *
${APP_USER} ALL=(root) NOPASSWD: ${ROUTING_SCRIPT} --interface ${AWG_INTERFACE} --table ${ROUTING_TABLE} --mark ${ROUTING_MARK} --priority ${ROUTING_PRIORITY} --ru-file *
${APP_USER} ALL=(root) NOPASSWD: ${ROUTING_SCRIPT} --interface ${AWG_INTERFACE} --table ${ROUTING_TABLE} --mark ${ROUTING_MARK} --priority ${ROUTING_PRIORITY} --direct *
${APP_USER} ALL=(root) NOPASSWD: ${ROUTING_SCRIPT} --interface ${AWG_INTERFACE} --table ${ROUTING_TABLE} --mark ${ROUTING_MARK} --priority ${ROUTING_PRIORITY} --force-awg *
${APP_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl reload ${PROXY_SERVICE}
${APP_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl is-active ${PROXY_SERVICE}
EOF
visudo -cf "${SUDOERS_TMP}" >/dev/null || fail "Generated sudoers configuration is invalid"
install -o root -g root -m 0440 "${SUDOERS_TMP}" "${SUDOERS_FILE}"
visudo -c

install -o root -g root -m 0644 "${INSTALL_DIR}/deploy/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"

printf '\n%s installed and started.\n' "${APP_NAME}"
if [[ "${WEB_HOST}" == *:* ]]; then
    printf 'Dashboard: http://[%s]:8000/login\n' "${WEB_HOST}"
else
    printf 'Dashboard: http://%s:8000/login\n' "${WEB_HOST}"
fi
printf 'Environment: %s (mode 0600)\n' "${ENV_FILE}"
printf 'Routing helper: %s\n' "${ROUTING_SCRIPT}"

if [[ "${CREATED_CREDENTIALS}" -eq 1 ]]; then
    printf 'Initial login: %s\n' "${ADMIN_LOGIN}"
    printf 'Initial password: %s\n' "${ADMIN_PASSWORD}"
    printf 'Store this password securely; it is not shown again.\n'
fi

cat <<EOF

AmneziaWG profile hook for [Interface] (if this client supports PostUp/PostDown):
PostUp = ${ROUTING_SCRIPT} --interface %i --table ${ROUTING_TABLE} --mark ${ROUTING_MARK} --priority ${ROUTING_PRIORITY} --ru-url ${RU_URL}
PostDown = ip route del default dev %i table ${ROUTING_TABLE}; ip rule del priority ${ROUTING_PRIORITY} fwmark ${ROUTING_MARK} lookup ${ROUTING_TABLE} 2>/dev/null || true

This installer does not install or modify 3proxy/AmneziaWG profiles. Configure 3proxy's users-file and log path to match ${ENV_FILE}, then reload 3proxy. Apply the AWG hook only after verifying that your Amnezia client supports these directives and expands %i.
EOF

if [[ "${PROXY_GROUP_UPDATED}" -eq 1 ]]; then
    printf '\nRestart %s once during a maintenance window so it receives the added %s group membership.\n' \
        "${PROXY_SERVICE}" "${APP_GROUP}"
fi
