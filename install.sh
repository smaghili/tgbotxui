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
REPO_SLUG="${REPO_SLUG:-smaghili/tgbotxui}"
REPO_BRANCH="${REPO_BRANCH:-main}"
STATE_DIR_NAME=".install-state"
SYSTEM_DEPS=(python3 python3-venv python3-pip python3-socks rsync)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
PROJECT_SOURCE="${PROJECT_ROOT}"
TEMP_PROJECT_DIR=""
BACKUP_STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${APP_DIR}/backups/${BACKUP_STAMP}"
INSTALL_MODE="auto"
TOTAL_STEPS=9
UPDATED_ENV_KEYS=()
ADDED_ENV_KEYS=()
REQUIREMENTS_CHANGED=1
SOURCE_CHANGED=1
SHOULD_INSTALL_SYSTEM_DEPS=1
REMOTE_COMMIT=""
PROJECT_REVISION="local"
NO_UPDATE_MESSAGE=""

cleanup() {
  if [[ -n "${TEMP_PROJECT_DIR}" && -d "${TEMP_PROJECT_DIR}" ]]; then
    rm -rf "${TEMP_PROJECT_DIR}"
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage:
  sudo bash install.sh [install|update|auto|help]

Modes:
  install  Fresh install
  update   Update existing install and preserve .env/data
  auto     Detect existing install and ask interactively
  help     Show this help

Environment overrides:
  REPO_SLUG   GitHub repo slug (default: smaghili/tgbotxui)
  REPO_BRANCH GitHub branch/tag to download when source files are not local
EOF
}

case "${1:-auto}" in
  install)
    INSTALL_MODE="install"
    ;;
  update)
    INSTALL_MODE="update"
    ;;
  auto|"")
    INSTALL_MODE="auto"
    ;;
  help|-h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Invalid mode: ${1}"
    usage
    exit 1
    ;;
esac

log_step() {
  echo
  echo "[$1] $2"
}

state_dir() {
  echo "${APP_DIR}/${STATE_DIR_NAME}"
}

state_file() {
  local name="$1"
  echo "$(state_dir)/${name}"
}

ensure_state_dir() {
  mkdir -p "$(state_dir)"
}

read_state_value() {
  local name="$1"
  local file
  file="$(state_file "${name}")"
  if [[ -f "${file}" ]]; then
    cat "${file}"
  fi
}

write_state_value() {
  local name="$1"
  local value="$2"
  ensure_state_dir
  printf '%s' "${value}" >"$(state_file "${name}")"
}

sha256_file() {
  local path="$1"
  sha256sum "${path}" | awk '{print $1}'
}

remote_head_commit() {
  local api_url="https://api.github.com/repos/${REPO_SLUG}/commits/${REPO_BRANCH}"
  if ! command -v curl >/dev/null 2>&1; then
    return
  fi
  curl -fsSL "${api_url}" 2>/dev/null | sed -n 's/.*"sha": "\([a-f0-9]\{40\}\)".*/\1/p' | head -n 1
}

project_manifest_hash() {
  tar -cf - \
    --exclude="${STATE_DIR_NAME}" \
    --exclude="./${STATE_DIR_NAME}" \
    --exclude="backups" \
    --exclude="./backups" \
    --exclude="data" \
    --exclude="./data" \
    --exclude=".venv" \
    --exclude="./.venv" \
    --exclude="__pycache__" \
    --exclude="./__pycache__" \
    --exclude=".pytest_cache" \
    --exclude="./.pytest_cache" \
    --exclude=".env" \
    --exclude="./.env" \
    -C "${APP_DIR}" . | sha256sum | awk '{print $1}'
}

has_socks_proxy() {
  local proxy_value
  for proxy_value in \
    "${http_proxy:-}" \
    "${https_proxy:-}" \
    "${all_proxy:-}" \
    "${HTTP_PROXY:-}" \
    "${HTTPS_PROXY:-}" \
    "${ALL_PROXY:-}"; do
    if [[ "${proxy_value}" =~ ^socks5h?:// || "${proxy_value}" =~ ^socks4a?:// ]]; then
      return 0
    fi
  done
  return 1
}

run_as_bot() {
  local env_args=()
  local key
  for key in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY no_proxy NO_PROXY; do
    if [[ -n "${!key:-}" ]]; then
      env_args+=("${key}=${!key}")
    fi
  done
  runuser -u "${BOT_USER}" -- env "${env_args[@]}" "$@"
}

resolve_database_path() {
  local configured_path
  configured_path="$(get_env_value "DATABASE_PATH")"
  if [[ -z "${configured_path}" ]]; then
    configured_path="data/bot.db"
  fi
  if [[ "${configured_path}" = /* ]]; then
    echo "${configured_path}"
  else
    echo "${APP_DIR}/${configured_path}"
  fi
}

project_files_present() {
  [[ -f "${PROJECT_ROOT}/main.py" && -f "${PROJECT_ROOT}/requirements.txt" && -f "${PROJECT_ROOT}/.env.example" ]]
}

download_project_archive() {
  local archive_url="https://codeload.github.com/${REPO_SLUG}/tar.gz/refs/heads/${REPO_BRANCH}"
  local archive_path
  local extracted_dir

  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to download project files."
    exit 1
  fi
  if ! command -v tar >/dev/null 2>&1; then
    echo "tar is required to extract project files."
    exit 1
  fi
  if ! command -v mktemp >/dev/null 2>&1; then
    echo "mktemp is required to prepare temporary project files."
    exit 1
  fi

  TEMP_PROJECT_DIR="$(mktemp -d)"
  archive_path="${TEMP_PROJECT_DIR}/repo.tar.gz"

  echo "Local project files were not found. Downloading ${REPO_SLUG} (${REPO_BRANCH})..."
  curl -fsSL "${archive_url}" -o "${archive_path}"
  tar -xzf "${archive_path}" -C "${TEMP_PROJECT_DIR}"

  extracted_dir="$(find "${TEMP_PROJECT_DIR}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [[ -z "${extracted_dir}" ]]; then
    echo "Failed to extract downloaded project archive."
    exit 1
  fi

  PROJECT_ROOT="${extracted_dir}"
  if [[ -n "${REMOTE_COMMIT}" ]]; then
    PROJECT_REVISION="${REMOTE_COMMIT}"
    PROJECT_SOURCE="github:${REPO_SLUG}@${REMOTE_COMMIT}"
  else
    PROJECT_SOURCE="github:${REPO_SLUG}@${REPO_BRANCH}"
  fi

  if ! project_files_present; then
    echo "Downloaded archive is missing required project files."
    exit 1
  fi
}

ensure_project_root() {
  if project_files_present; then
    PROJECT_SOURCE="${PROJECT_ROOT}"
    return
  fi
  download_project_archive
}

prepare_update_metadata() {
  if [[ "${INSTALL_MODE}" != "update" ]]; then
    return
  fi

  local current_revision=""
  current_revision="$(read_state_value "source_revision")"

  if [[ "${PROJECT_SOURCE}" != "${PROJECT_ROOT}" ]]; then
    REMOTE_COMMIT="$(remote_head_commit || true)"
    if [[ -n "${REMOTE_COMMIT}" ]]; then
      PROJECT_REVISION="${REMOTE_COMMIT}"
      if [[ -n "${current_revision}" && "${current_revision}" == "${REMOTE_COMMIT}" ]]; then
        echo "TgBot is already up to date."
        echo "Current revision: ${current_revision}"
        exit 0
      fi
    fi
  fi

  local current_requirements_hash=""
  local project_requirements_hash=""
  current_requirements_hash="$(read_state_value "requirements.sha256")"
  if [[ -f "${PROJECT_ROOT}/requirements.txt" ]]; then
    project_requirements_hash="$(sha256_file "${PROJECT_ROOT}/requirements.txt")"
  fi
  if [[ -n "${current_requirements_hash}" && -n "${project_requirements_hash}" && "${current_requirements_hash}" == "${project_requirements_hash}" ]]; then
    REQUIREMENTS_CHANGED=0
    SHOULD_INSTALL_SYSTEM_DEPS=0
  else
    REQUIREMENTS_CHANGED=1
    SHOULD_INSTALL_SYSTEM_DEPS=1
  fi
}

prepare_remote_update_check() {
  if [[ "${INSTALL_MODE}" != "update" ]]; then
    return
  fi

  if project_files_present; then
    return
  fi

  local current_revision=""
  current_revision="$(read_state_value "source_revision")"
  if [[ -z "${current_revision}" ]]; then
    return
  fi

  REMOTE_COMMIT="$(remote_head_commit || true)"
  if [[ -n "${REMOTE_COMMIT}" ]]; then
    PROJECT_REVISION="${REMOTE_COMMIT}"
    PROJECT_SOURCE="github:${REPO_SLUG}@${REMOTE_COMMIT}"
    if [[ "${current_revision}" == "${REMOTE_COMMIT}" ]]; then
      echo "TgBot is already up to date."
      echo "Current revision: ${current_revision}"
      exit 0
    fi
  fi
}

detect_existing_install() {
  [[ -d "${APP_DIR}" && ( -f "${APP_DIR}/main.py" || -f "${APP_DIR}/.env" || -d "${APP_DIR}/data" ) ]]
}

prompt_install_mode() {
  if [[ "${INSTALL_MODE}" == "install" || "${INSTALL_MODE}" == "update" ]]; then
    return
  fi

  if ! detect_existing_install; then
    INSTALL_MODE="install"
    return
  fi

  echo "Existing installation detected in ${APP_DIR}."
  echo "1) Update existing bot (replace files, keep database/data)"
  echo "2) Fresh install over current path"
  echo "3) Cancel"
  read -r -p "Choose an option [1-3]: " MODE_CHOICE

  case "${MODE_CHOICE}" in
    1) INSTALL_MODE="update" ;;
    2) INSTALL_MODE="install" ;;
    3)
      echo "Cancelled."
      exit 0
      ;;
    *)
      echo "Invalid choice."
      exit 1
      ;;
  esac
}

ensure_runtime_user() {
  if ! id "${BOT_USER}" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "/home/${BOT_USER}" --shell /usr/sbin/nologin "${BOT_USER}"
  fi
}

backup_existing_state() {
  if [[ "${INSTALL_MODE}" != "update" ]]; then
    return
  fi

  mkdir -p "${BACKUP_DIR}"

  if [[ -f "${APP_DIR}/.env" ]]; then
    cp -a "${APP_DIR}/.env" "${BACKUP_DIR}/.env"
  fi

  if [[ -d "${APP_DIR}/data" ]]; then
    mkdir -p "${BACKUP_DIR}/data"
    set +e
    rsync -a \
      --exclude "*.db-journal" \
      --exclude "*.db-wal" \
      --exclude "*.db-shm" \
      "${APP_DIR}/data/" "${BACKUP_DIR}/data/"
    local rsync_code=$?
    set -e
    if [[ "${rsync_code}" -ne 0 && "${rsync_code}" -ne 24 ]]; then
      exit "${rsync_code}"
    fi
  fi
}

sync_project_files() {
  mkdir -p "${APP_DIR}" "${APP_DIR}/data"

  if [[ "${INSTALL_MODE}" == "update" ]]; then
    rsync -a --delete \
      --exclude ".git" \
      --exclude ".venv" \
      --exclude "__pycache__" \
      --exclude ".pytest_cache" \
      --exclude ".env" \
      --exclude "data/" \
      --exclude "backups/" \
      "${PROJECT_ROOT}/" "${APP_DIR}/"
  else
    rsync -a --delete \
      --exclude ".git" \
      --exclude ".venv" \
      --exclude "__pycache__" \
      --exclude ".pytest_cache" \
      --exclude "data/" \
      --exclude "backups/" \
      "${PROJECT_ROOT}/" "${APP_DIR}/"
  fi

  chown -R "${BOT_USER}:${BOT_USER}" "${APP_DIR}/bot" "${APP_DIR}/scripts" "${APP_DIR}/tests" "${APP_DIR}/tools" 2>/dev/null || true
  chown "${BOT_USER}:${BOT_USER}" \
    "${APP_DIR}/main.py" \
    "${APP_DIR}/install.sh" \
    "${APP_DIR}/requirements.txt" \
    "${APP_DIR}/README.md" \
    "${APP_DIR}/pytest.ini" \
    "${APP_DIR}/.env.example" 2>/dev/null || true
}

detect_update_changes() {
  if [[ "${INSTALL_MODE}" != "update" ]]; then
    REQUIREMENTS_CHANGED=1
    SOURCE_CHANGED=1
    SHOULD_INSTALL_SYSTEM_DEPS=1
    return
  fi

  local current_requirements_hash=""
  local new_requirements_hash=""
  current_requirements_hash="$(read_state_value "requirements.sha256")"
  new_requirements_hash="$(sha256_file "${APP_DIR}/requirements.txt")"

  if [[ -n "${current_requirements_hash}" && "${current_requirements_hash}" == "${new_requirements_hash}" ]]; then
    REQUIREMENTS_CHANGED=0
  else
    REQUIREMENTS_CHANGED=1
  fi

  local current_revision=""
  current_revision="$(read_state_value "source_revision")"
  if [[ -n "${REMOTE_COMMIT}" && -n "${current_revision}" && "${current_revision}" == "${REMOTE_COMMIT}" ]]; then
    SOURCE_CHANGED=0
  elif [[ -n "${REMOTE_COMMIT}" ]]; then
    SOURCE_CHANGED=1
  else
    local current_source_hash=""
    local new_source_hash=""
    current_source_hash="$(read_state_value "source.sha256")"
    new_source_hash="$(project_manifest_hash)"
    if [[ -n "${current_source_hash}" && "${current_source_hash}" == "${new_source_hash}" ]]; then
      SOURCE_CHANGED=0
    else
      SOURCE_CHANGED=1
    fi
  fi

  SHOULD_INSTALL_SYSTEM_DEPS="${REQUIREMENTS_CHANGED}"
}

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${APP_DIR}/.env"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${APP_DIR}/.env"
  else
    echo "${key}=${value}" >> "${APP_DIR}/.env"
  fi
}

get_env_value() {
  local key="$1"
  if [[ ! -f "${APP_DIR}/.env" ]]; then
    return
  fi
  grep "^${key}=" "${APP_DIR}/.env" | head -n 1 | cut -d'=' -f2- || true
}

sync_env_template() {
  local example_file="${APP_DIR}/.env.example"
  local line
  local key

  if [[ ! -f "${example_file}" || ! -f "${APP_DIR}/.env" ]]; then
    return
  fi

  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ -z "${line}" || "${line}" =~ ^[[:space:]]*# ]]; then
      continue
    fi
    if [[ "${line}" != *=* ]]; then
      continue
    fi
    key="${line%%=*}"
    if ! grep -q "^${key}=" "${APP_DIR}/.env"; then
      echo "${line}" >> "${APP_DIR}/.env"
      ADDED_ENV_KEYS+=("${key}")
    fi
  done < "${example_file}"
}

prompt_required_value() {
  local label="$1"
  local current_value="$2"
  local prompt_text
  local value

  if [[ -n "${current_value}" ]]; then
    prompt_text="Enter ${label} [leave empty to keep current]: "
  else
    prompt_text="Enter ${label}: "
  fi

  while true; do
    read -r -p "${prompt_text}" value
    if [[ -n "${value}" ]]; then
      echo "${value}"
      return
    fi
    if [[ -n "${current_value}" ]]; then
      echo "${current_value}"
      return
    fi
    echo "${label} cannot be empty."
  done
}

prompt_optional_value() {
  local label="$1"
  local current_value="$2"
  local value

  if [[ -n "${current_value}" ]]; then
    read -r -p "Enter ${label} [leave empty to keep current]: " value
    if [[ -z "${value}" ]]; then
      echo "${current_value}"
      return
    fi
  else
    read -r -p "Enter ${label} (optional): " value
  fi

  echo "${value}"
}

build_virtualenv() {
  local venv_args=()
  local venv_python="${APP_DIR}/.venv/bin/python"

  if [[ "${INSTALL_MODE}" != "update" ]]; then
    rm -rf "${APP_DIR}/.venv"
  fi

  if [[ ! -x "${venv_python}" ]]; then
    if has_socks_proxy; then
      venv_args+=(--system-site-packages)
    fi

    "${PYTHON_BIN}" -m venv "${venv_args[@]}" "${APP_DIR}/.venv"
    "${venv_python}" -m pip install --upgrade pip
  fi

  if [[ "${INSTALL_MODE}" == "update" && "${REQUIREMENTS_CHANGED}" -eq 0 ]]; then
    echo "requirements.txt unchanged; skipping pip install."
  else
    "${venv_python}" -m pip install -r "${APP_DIR}/requirements.txt"
  fi
  chown -R "${BOT_USER}:${BOT_USER}" "${APP_DIR}/.venv"
}

persist_install_state() {
  write_state_value "requirements.sha256" "$(sha256_file "${APP_DIR}/requirements.txt")"
  write_state_value "source.sha256" "$(project_manifest_hash)"
  write_state_value "source_revision" "${PROJECT_REVISION}"
  chown -R "${BOT_USER}:${BOT_USER}" "$(state_dir)"
}

apply_database_migrations() {
  echo
  echo "Applying database migrations safely..."
  local venv_python="${APP_DIR}/.venv/bin/python"
  if [[ ! -x "${venv_python}" ]]; then
    echo "Virtualenv python not found: ${venv_python}"
    exit 1
  fi
  (
    cd "${APP_DIR}"
    run_as_bot "${venv_python}" scripts/apply_migrations.py
  )
}

prepare_environment_file() {
  if [[ ! -f "${APP_DIR}/.env" ]]; then
    cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  fi

  sync_env_template

  local current_bot_token
  local current_admin_ids
  local current_telegram_proxies
  local current_key
  local input_bot_token
  local input_admin_ids
  local input_telegram_proxies
  local generated_key

  current_bot_token="$(get_env_value "BOT_TOKEN")"
  current_admin_ids="$(get_env_value "ADMIN_IDS")"
  current_telegram_proxies="$(get_env_value "TELEGRAM_PROXIES")"
  current_key="$(get_env_value "ENCRYPTION_KEY")"

  if [[ "${INSTALL_MODE}" == "update" ]]; then
    if [[ -z "${current_bot_token}" ]]; then
      echo "BOT_TOKEN is missing in existing .env; update cannot continue safely."
      exit 1
    fi
    if [[ -z "${current_admin_ids}" ]]; then
      echo "ADMIN_IDS is missing in existing .env; update cannot continue safely."
      exit 1
    fi
    input_bot_token="${current_bot_token}"
    input_admin_ids="${current_admin_ids}"
    input_telegram_proxies="${current_telegram_proxies}"
  else
    input_bot_token="$(prompt_required_value "BOT_TOKEN" "${current_bot_token}")"
    input_admin_ids="$(prompt_required_value "ADMIN_IDS (comma-separated numeric Telegram IDs)" "${current_admin_ids}")"
    if ! [[ "${input_admin_ids}" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
      echo "ADMIN_IDS format invalid. Expected: 12345,67890"
      exit 1
    fi

    echo "If Telegram is filtered on your server, enter one or more proxies."
    echo "Example: http://user:pass@host:port,http://user:pass@host2:port2"
    input_telegram_proxies="$(prompt_optional_value "TELEGRAM_PROXIES" "${current_telegram_proxies}")"
  fi

  if [[ -z "${current_key}" || "${current_key}" == "replace_me" ]]; then
    generated_key="$(${APP_DIR}/.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
  else
    generated_key="${current_key}"
  fi

  set_env_value "BOT_TOKEN" "${input_bot_token}"
  set_env_value "ADMIN_IDS" "${input_admin_ids}"
  set_env_value "TELEGRAM_PROXIES" "${input_telegram_proxies}"
  set_env_value "ENCRYPTION_KEY" "${generated_key}"

  UPDATED_ENV_KEYS=("BOT_TOKEN" "ADMIN_IDS" "TELEGRAM_PROXIES" "ENCRYPTION_KEY")
  chown "${BOT_USER}:${BOT_USER}" "${APP_DIR}/.env"
}

install_service_file() {
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
}

start_service() {
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
  systemctl restart "${SERVICE_NAME}"
}

print_report() {
  local db_path
  db_path="$(resolve_database_path)"
  local status_summary="unknown"
  local db_summary="not found"

  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    status_summary="active"
  else
    status_summary="inactive"
  fi

  if [[ -f "${db_path}" ]]; then
    db_summary="preserved at ${db_path} ($(du -h "${db_path}" | awk '{print $1}'))"
  elif [[ -d "${APP_DIR}/data" ]]; then
    db_summary="data directory preserved at ${APP_DIR}/data"
  fi

  echo
  echo "===== ${INSTALL_MODE^^} REPORT ====="
  echo "Mode: ${INSTALL_MODE}"
  echo "App dir: ${APP_DIR}"
  echo "Service: ${SERVICE_NAME} (${status_summary})"
  echo "Runtime user: ${BOT_USER}"
  echo "Project files: synced from ${PROJECT_SOURCE}"
  echo "Database/data: ${db_summary}"
  if [[ "${INSTALL_MODE}" == "update" ]]; then
    echo "Backup: ${BACKUP_DIR}"
    echo "Update behavior: bot files replaced, .env and data preserved"
  fi
  echo "Environment keys configured: ${UPDATED_ENV_KEYS[*]}"
  if [[ "${#ADDED_ENV_KEYS[@]}" -gt 0 ]]; then
    echo "New .env keys added from template: ${ADDED_ENV_KEYS[*]}"
  else
    echo "New .env keys added from template: none"
  fi
  echo "Migrations: applied automatically on bot startup"
  echo "==================================="
  systemctl --no-pager --full status "${SERVICE_NAME}" || true
}

prompt_install_mode

prepare_remote_update_check
ensure_project_root
prepare_update_metadata

log_step "1/${TOTAL_STEPS}" "Installing dependencies..."
if [[ "${INSTALL_MODE}" == "update" && "${SHOULD_INSTALL_SYSTEM_DEPS}" -eq 0 ]]; then
  echo "System dependencies unchanged; skipping apt install."
else
  apt-get update
  apt-get install -y "${SYSTEM_DEPS[@]}"
fi

log_step "2/${TOTAL_STEPS}" "Preparing runtime user..."
ensure_runtime_user

log_step "3/${TOTAL_STEPS}" "Backing up existing state (update mode only)..."
backup_existing_state

log_step "4/${TOTAL_STEPS}" "Syncing project to ${APP_DIR}..."
sync_project_files
detect_update_changes

log_step "5/${TOTAL_STEPS}" "Building virtualenv..."
build_virtualenv

log_step "6/${TOTAL_STEPS}" "Preparing environment..."
prepare_environment_file

log_step "7/${TOTAL_STEPS}" "Installing systemd service..."
install_service_file

apply_database_migrations

log_step "8/${TOTAL_STEPS}" "Enabling and starting service..."
start_service
persist_install_state

log_step "9/${TOTAL_STEPS}" "Printing report..."
print_report
