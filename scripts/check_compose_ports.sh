#!/usr/bin/env bash
set -euo pipefail

# 校验本项目 Compose 发布端口，避免启动到一半才发现端口冲突。

ENV_FILE="${1:-.env.compose}"
PORT_MIN=41100
PORT_MAX=41199

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "missing ${ENV_FILE}; copy .env.compose.example first" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-pokemon-battle-inference}"

port_is_owned_by_this_project() {
  local port_value="$1"
  local container_ids

  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi

  container_ids="$(docker ps --filter "publish=${port_value}" --format '{{.ID}}' 2>/dev/null || true)"
  if [[ -z "${container_ids}" ]]; then
    return 1
  fi

  while IFS= read -r container_id; do
    [[ -z "${container_id}" ]] && continue
    local project_label
    project_label="$(docker inspect \
      --format '{{ index .Config.Labels "com.docker.compose.project" }}' \
      "${container_id}" 2>/dev/null || true)"
    if [[ "${project_label}" == "${COMPOSE_PROJECT_NAME}" ]]; then
      return 0
    fi
  done <<< "${container_ids}"

  return 1
}

check_one_port() {
  local var_name="$1"
  local service_name="$2"
  local port_value="${!var_name:-}"

  if [[ ! "${port_value}" =~ ^[0-9]+$ ]]; then
    echo "${var_name} for ${service_name} must be an integer: ${port_value}" >&2
    exit 2
  fi
  if (( port_value < PORT_MIN || port_value > PORT_MAX )); then
    echo "${var_name}=${port_value} for ${service_name} is outside ${PORT_MIN}-${PORT_MAX}" >&2
    exit 2
  fi

  # 只检查宿主机监听端口；Compose 内部 service DNS 不依赖这些 published ports。
  if python3 - "$port_value" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    exc = sys.exc_info()[1]
    if getattr(exc, "errno", None) == 1:
        print("permission-denied")
        sys.exit(3)
    sys.exit(1)
finally:
    sock.close()
PY
  then
    echo "ok ${service_name}: ${port_value}"
  else
    case "$?" in
      3)
        echo "cannot check ${service_name} port ${port_value}: permission denied by runtime sandbox" >&2
        exit 3
        ;;
      *)
        if port_is_owned_by_this_project "${port_value}"; then
          echo "ok ${service_name}: ${port_value} already owned by ${COMPOSE_PROJECT_NAME}"
          return
        fi
        echo "port ${port_value} for ${service_name} is occupied; change ${var_name}" >&2
        exit 1
        ;;
    esac
  fi
}

check_one_port POKEOP_FRONTEND_PORT frontend
check_one_port POKEOP_BACKEND_PORT backend
check_one_port POKEOP_POSTGRES_PORT postgres
