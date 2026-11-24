#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="web-proxy"
APP_USER="webproxy"
APP_GROUP="webproxy"
SHARED_LOG_GROUP="webproxy-3proxy"
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

INSTALL_DIR_REAL="$(cd -- "${INSTALL_DIR}" && pwd -P)"
COPY_SOURCE=1
if [[ "${SOURCE_DIR}" == "${INSTALL_DIR_REAL}" ]]; then
    COPY_SOURCE=0
    printf 'Source is already installed at %s; skipping copy.\n' "${INSTALL_DIR_REAL}"
elif [[ "${SOURCE_DIR}" == "${INSTALL_DIR_REAL}/"* || "${INSTALL_DIR_REAL}" == "${SOURCE_DIR}/"* ]]; then
    fail "Source (${SOURCE_DIR}) and install directory (${INSTALL_DIR_REAL}) overlap; copy the project to a separate directory and retry"
fi

if [[ "${COPY_SOURCE}" -eq 1 ]]; then
    # Copy source without local environments, credentials, caches, or database files.
    tar -C "${SOURCE_DIR}" \
        --exclude='./.git' \
        --exclude='./.venv' \
        --exclude='./.env' \
        --exclude='./*.db' \
        --exclude='./.pytest_cache' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        -cf - . | tar -C "${INSTALL_DIR_REAL}" -xf -
    chown -R "${APP_USER}:${APP_GROUP}" "${INSTALL_DIR_REAL}"
fi

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
    RU_URL="$(read_env_value WEBPROXY_RU_URL https://www.ipdeny.com/ipblocks/data/aggregated/ru-aggregated.zone)"
    PROXY_USER="$(read_env_value WEBPROXY_PROXY_USER 3proxy)"
    PROXY_SERVICE="$(read_env_value WEBPROXY_PROXY_SERVICE 3proxy.service)"
    PROXY_USERS_FILE="$(read_env_value WEBPROXY_PROXY_USERS_FILE /var/lib/web-proxy/users)"
    PROXY_LOG_FILE="$(read_env_value WEBPROXY_PROXY_LOG_FILE /var/log/3proxy/3proxy.log)"
else
    WEB_HOST="${WEBPROXY_WEB_HOST:-127.0.0.1}"
    AWG_INTERFACE="${WEBPROXY_AWG_INTERFACE:-awg1}"
    ROUTING_TABLE="${WEBPROXY_ROUTING_TABLE:-100}"
    ROUTING_MARK="${WEBPROXY_ROUTING_MARK:-1}"
    ROUTING_PRIORITY="${WEBPROXY_ROUTING_PRIORITY:-100}"
    RU_URL="${WEBPROXY_RU_URL:-https://www.ipdeny.com/ipblocks/data/aggregated/ru-aggregated.zone}"
    PROXY_USER="${WEBPROXY_PROXY_USER:-3proxy}"
    PROXY_SERVICE="${WEBPROXY_PROXY_SERVICE:-3proxy.service}"
    PROXY_USERS_FILE="/var/lib/web-proxy/users"
    PROXY_LOG_FILE="/var/log/3proxy/3proxy.log"
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
[[ "${PROXY_USER}" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ]] || fail "Invalid 3proxy system user"
[[ "${PROXY_SERVICE}" =~ ^[a-zA-Z0-9_.@:-]+$ ]] || fail "Invalid 3proxy systemd service name"
[[ "${PROXY_USERS_FILE}" == /var/lib/web-proxy/* ]] \
    || fail "WEBPROXY_PROXY_USERS_FILE must be inside /var/lib/web-proxy so the app can safely manage it"
[[ "${PROXY_LOG_FILE}" == /var/log/3proxy/* ]] \
    || fail "WEBPROXY_PROXY_LOG_FILE must be inside /var/log/3proxy so file permissions remain scoped"

if [[ "${PROXY_USER}" == "${APP_USER}" ]]; then
    fail "WEBPROXY_PROXY_USER must differ from the application account '${APP_USER}'"
fi

if ! id "${PROXY_USER}" >/dev/null 2>&1; then
    if ! getent group "${PROXY_USER}" >/dev/null; then
        groupadd --system "${PROXY_USER}"
    fi
    useradd --system --gid "${PROXY_USER}" --home-dir /var/lib/3proxy \
        --no-create-home --shell /usr/sbin/nologin "${PROXY_USER}"
fi

PROXY_GROUP="$(id -gn "${PROXY_USER}")"
getent group "${PROXY_GROUP}" >/dev/null || fail "Primary group '${PROXY_GROUP}' for ${PROXY_USER} does not exist"
if ! getent group "${SHARED_LOG_GROUP}" >/dev/null; then
    groupadd --system "${SHARED_LOG_GROUP}"
fi
install -d -o "${PROXY_USER}" -g "${PROXY_GROUP}" -m 0750 /var/lib/3proxy

usermod -a -G "${APP_GROUP},${SHARED_LOG_GROUP}" "${PROXY_USER}"
usermod -a -G "${SHARED_LOG_GROUP}" "${APP_USER}"

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
WEBPROXY_PROXY_USERS_FILE=${PROXY_USERS_FILE}
WEBPROXY_PROXY_LOG_FILE=${PROXY_LOG_FILE}
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

PROXY_USERS_DIR="$(dirname -- "${PROXY_USERS_FILE}")"
PROXY_LOG_DIR="$(dirname -- "${PROXY_LOG_FILE}")"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${PROXY_USERS_DIR}"
if [[ ! -e "${PROXY_USERS_FILE}" ]]; then
    install -o "${APP_USER}" -g "${APP_GROUP}" -m 0640 /dev/null "${PROXY_USERS_FILE}"
else
    chown "${APP_USER}:${APP_GROUP}" "${PROXY_USERS_FILE}"
    chmod 0640 "${PROXY_USERS_FILE}"
fi

install -d -o "${PROXY_USER}" -g "${SHARED_LOG_GROUP}" -m 0750 "${PROXY_LOG_DIR}"
if [[ ! -e "${PROXY_LOG_FILE}" ]]; then
    install -o "${PROXY_USER}" -g "${SHARED_LOG_GROUP}" -m 0640 /dev/null "${PROXY_LOG_FILE}"
else
    chown "${PROXY_USER}:${SHARED_LOG_GROUP}" "${PROXY_LOG_FILE}"
    chmod 0640 "${PROXY_LOG_FILE}"
fi

install -d -o root -g root -m 0755 "/etc/systemd/system/${SERVICE_NAME}.d"
cat >"/etc/systemd/system/${SERVICE_NAME}.d/proxy-group.conf" <<EOF
[Service]
SupplementaryGroups=${SHARED_LOG_GROUP}
EOF
chmod 0644 "/etc/systemd/system/${SERVICE_NAME}.d/proxy-group.conf"

if systemctl cat "${PROXY_SERVICE}" >/dev/null 2>&1; then
    PROXY_UNIT_DROPIN_DIR="/etc/systemd/system/${PROXY_SERVICE}.d"
    install -d -o root -g root -m 0755 "${PROXY_UNIT_DROPIN_DIR}"
    cat >"${PROXY_UNIT_DROPIN_DIR}/webproxy-users.conf" <<EOF
[Service]
SupplementaryGroups=${APP_GROUP} ${SHARED_LOG_GROUP}
EOF
    chmod 0644 "${PROXY_UNIT_DROPIN_DIR}/webproxy-users.conf"
    PROXY_UNIT_FOUND=1
else
    PROXY_UNIT_FOUND=0
    printf 'WARNING: systemd unit %s was not found; configure its service process to read group %s.\n' \
        "${PROXY_SERVICE}" "${APP_GROUP}" >&2
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
systemctl enable "${SERVICE_NAME}"
if systemctl is-active --quiet "${SERVICE_NAME}"; then
    systemctl restart "${SERVICE_NAME}"
else
    systemctl start "${SERVICE_NAME}"
fi

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

if [[ "${PROXY_UNIT_FOUND}" -eq 1 ]]; then
    printf '\nRestart %s during a maintenance window to apply its new supplementary groups %s and %s.\n' \
        "${PROXY_SERVICE}" "${APP_GROUP}" "${SHARED_LOG_GROUP}"
fi

cat <<EOF

AmneziaWG profile hook for [Interface] (if this client supports PostUp/PostDown):
PostUp = ${ROUTING_SCRIPT} --interface %i --table ${ROUTING_TABLE} --mark ${ROUTING_MARK} --priority ${ROUTING_PRIORITY} --ru-url ${RU_URL}
PostDown = ip route del default dev %i table ${ROUTING_TABLE}; ip rule del priority ${ROUTING_PRIORITY} fwmark ${ROUTING_MARK} lookup ${ROUTING_TABLE} 2>/dev/null || true

This installer does not install or rewrite 3proxy/AmneziaWG configuration. Configure 3proxy to read users from ${PROXY_USERS_FILE} and write logs to ${PROXY_LOG_FILE}. Apply the AWG hook only after verifying that your Amnezia client supports these directives and expands %i.
EOF
