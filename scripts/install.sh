#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "This script must run as root."
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/tgbot}"
SERVICE_NAME="${SERVICE_NAME:-tgbot}"
BOT_USER="${BOT_USER:-tgbot}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[1/7] Installing dependencies..."
apt-get update
apt-get install -y "${PYTHON_BIN}" python3-venv python3-pip rsync

echo "[2/7] Preparing runtime user..."
if ! id "${BOT_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/${BOT_USER}" --shell /usr/sbin/nologin "${BOT_USER}"
fi

echo "[3/7] Syncing project to ${APP_DIR}..."
mkdir -p "${APP_DIR}"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  --exclude ".pytest_cache" \
  --exclude "data/*.db" \
  "${PROJECT_ROOT}/" "${APP_DIR}/"
chown -R "${BOT_USER}:${BOT_USER}" "${APP_DIR}"

echo "[4/7] Building virtualenv..."
runuser -u "${BOT_USER}" -- "${PYTHON_BIN}" -m venv "${APP_DIR}/.venv"
runuser -u "${BOT_USER}" -- "${APP_DIR}/.venv/bin/pip" install --upgrade pip
runuser -u "${BOT_USER}" -- "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "[5/7] Preparing environment..."
if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
fi

read -r -p "Enter BOT_TOKEN: " INPUT_BOT_TOKEN
while [[ -z "${INPUT_BOT_TOKEN}" ]]; do
  echo "BOT_TOKEN cannot be empty."
  read -r -p "Enter BOT_TOKEN: " INPUT_BOT_TOKEN
done

read -r -p "Enter ADMIN_IDS (comma-separated numeric Telegram IDs): " INPUT_ADMIN_IDS
while [[ -z "${INPUT_ADMIN_IDS}" ]]; do
  echo "ADMIN_IDS cannot be empty."
  read -r -p "Enter ADMIN_IDS (comma-separated numeric Telegram IDs): " INPUT_ADMIN_IDS
done
if ! [[ "${INPUT_ADMIN_IDS}" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
  echo "ADMIN_IDS format invalid. Expected: 12345,67890"
  exit 1
fi

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${APP_DIR}/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${APP_DIR}/.env"
  else
    echo "${key}=${value}" >> "${APP_DIR}/.env"
  fi
}

CURRENT_KEY="$(grep '^ENCRYPTION_KEY=' "${APP_DIR}/.env" | cut -d'=' -f2- || true)"
if [[ -z "${CURRENT_KEY}" || "${CURRENT_KEY}" == "replace_me" ]]; then
  GENERATED_KEY="$(${APP_DIR}/.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
else
  GENERATED_KEY="${CURRENT_KEY}"
fi

set_env_value "BOT_TOKEN" "${INPUT_BOT_TOKEN}"
set_env_value "ADMIN_IDS" "${INPUT_ADMIN_IDS}"
set_env_value "ENCRYPTION_KEY" "${GENERATED_KEY}"
chown "${BOT_USER}:${BOT_USER}" "${APP_DIR}/.env"

echo "[6/7] Installing systemd service..."
cat >/etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Telegram 3x-ui Bot (Python)
After=network.target

[Service]
Type=simple
User=${BOT_USER}
Group=${BOT_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/main.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${APP_DIR}
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
MemoryDenyWriteExecute=true

[Install]
WantedBy=multi-user.target
EOF

echo "[7/7] Enabling and starting service..."
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true

echo "Install complete."
echo "Configured BOT_TOKEN and ADMIN_IDS in ${APP_DIR}/.env"
