#!/usr/bin/env bash
# 用途：独立 curl 客户端验收实际 Go 服务进程，含 CGO/Core 完整计算和错误响应。
# 输入：已构建的 /build/core 库与可选构建/报告目录变量；不读取生产凭据。
# 输出：请求、状态、响应头/正文和容器日志保存到 Backup；退出码 0 表示完整比较通过。
# 副作用：构建当前 Go 可执行文件，启动自有 run --rm 容器，仅发布随机回环端口，退出清理。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/abi-http-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
container_id=""

# 参数为专用 Compose 子命令；透传状态码，不调用常驻服务的 up 或 reset。
compose() {
  bash "$nas_manager" compose -p pokemon-migration-validation \
    -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" --profile maintenance "$@"
}

# 无参数；先归档本次实例日志，再停止精确 ID；run --rm 移除临时实例。
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker logs "$container_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1
    docker stop "$container_id" > /dev/null
  fi
}

mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
compose run --rm --no-deps -e CGO_LDFLAGS=-L/build/core -e GOCACHE=/build/go-cache \
  -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c \
  'cd server && go build -a -o /build/pbi-server ./cmd/pbi-server' \
  > "$POKEOP_REPORT_ROOT/server-build.log" 2>&1
container_id="$(compose run --rm --no-deps -d --name "pbi-core-acceptance-$$" \
  --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 pokemon-validation /build/pbi-server)"
trap cleanup EXIT
readonly endpoint="http://$(docker port "$container_id" 41105/tcp)"
for attempt in {1..30}; do
  if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi
  sleep 0.1
done
cp "$POKEOP_SOURCE_ROOT/tests/vectors/abi-calculations.v1.request.json" "$POKEOP_REPORT_ROOT/request.json"
status="$(curl -sS --max-time 15 -H 'Content-Type: application/json' \
  --data-binary "@$POKEOP_REPORT_ROOT/request.json" -D "$POKEOP_REPORT_ROOT/response.headers" \
  -o "$POKEOP_REPORT_ROOT/response.json" -w '%{http_code}' "$endpoint/v1/core/calculate")"
printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/response.status"
[[ "$status" == 200 ]]
python3 - "$POKEOP_SOURCE_ROOT/tests/vectors/abi-calculations.v1.response.json" "$POKEOP_REPORT_ROOT/response.json" <<'PY'
"""argv 为冻结响应与实际正文路径；比较所有版本、字段与结果槽位，不读取服务实现。"""
import json
import sys
from pathlib import Path
expected, actual = (json.loads(Path(name).read_text()) for name in sys.argv[1:])
assert actual == expected, "HTTP response differs from the shared ABI fixture"
PY
printf '%s' '{"schema_version":1,"operations":[{"kind":"unknown"}]}' > "$POKEOP_REPORT_ROOT/unsupported-request.json"
status="$(curl -sS --max-time 15 -H 'Content-Type: application/json' \
  --data-binary "@$POKEOP_REPORT_ROOT/unsupported-request.json" -D "$POKEOP_REPORT_ROOT/unsupported.headers" \
  -o "$POKEOP_REPORT_ROOT/unsupported.json" -w '%{http_code}' "$endpoint/v1/core/calculate")"
printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/unsupported.status"
[[ "$status" == 422 ]]
python3 - "$POKEOP_REPORT_ROOT/unsupported.json" <<'PY'
"""argv 为实际拒绝正文；拒绝必须是明确错误，不得携带部分成功结果。"""
import json
import sys
from pathlib import Path
response = json.loads(Path(sys.argv[1]).read_text())
assert response['error']['code'] == 'unsupported' and 'results' not in response
PY
printf 'HTTP Core acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
