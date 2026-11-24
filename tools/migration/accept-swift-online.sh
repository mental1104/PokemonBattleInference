#!/usr/bin/env bash
# 用途：真实 Swift 客户端经 HTTP 调用独立 Go 服务，完整核对同 Core 的在线/离线结果及错误传播。
# 输入：已有 Core 库；PBI_GO_CORE_BUILD_DIR/PBI_SWIFT_CORE_BUILD_DIR 可指定容器内独立目录，默认 /build/core、/build/swift-core。
# 依赖：Docker/已声明 maintenance 镜像；构建和报告根可用既有 POKEOP_* 变量覆盖。
# 输出：Backup 中的构建/服务/Swift 日志与完整请求响应 JSON，退出码非零表示验收失败。
# 副作用：构建独立 Go 可执行文件，启动自有 run --rm API；仅健康探测发布随机回环端口，不连接数据库。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/swift-online-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly server_name="pbi-swift-online-$$"
readonly go_core="${PBI_GO_CORE_BUILD_DIR:-/build/core}"
readonly swift_core="${PBI_SWIFT_CORE_BUILD_DIR:-/build/swift-core}"
container_id=""

# 参数为项目 Compose 子命令，标准输出/错误和退出码原样返回；仅使用既有 maintenance 声明。
compose() {
  bash "$nas_manager" compose -p pokemon-migration-validation \
    -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" --profile maintenance "$@"
}

# 无参数；退出时先归档本次 API 日志，再停止精确容器 ID，绝不操作其他服务。
cleanup() {
  if [[ -n "$container_id" ]]; then
    docker logs "$container_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true
    docker stop "$container_id" > /dev/null || true
  fi
}

mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/p2-online/go-tmp"
compose run --rm --no-deps -e "CGO_LDFLAGS=-L$go_core" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path \
  -e GOTMPDIR=/build/p2-online/go-tmp pokemon-validation sh -c \
  'cd server && go build -a -o /build/p2-online/pbi-server ./cmd/pbi-server && go build -a -o /build/p2-online/pbi-core-worker ./cmd/pbi-core-worker' \
  > "$POKEOP_REPORT_ROOT/server-build.log" 2>&1
container_id="$(compose run --rm --no-deps -d --name "$server_name" \
  --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_CORE_WORKER_PATH=/build/p2-online/pbi-core-worker \
  pokemon-validation /build/p2-online/pbi-server)"
trap cleanup EXIT
# 使用宿主已声明的 curl 探测回环健康；工具镜像无需临时安装 HTTP CLI。
endpoint="http://$(docker port "$container_id" 41105/tcp)"
ready=0
for attempt in {1..100}; do
  if curl -fsS --max-time 1 "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>> "$POKEOP_REPORT_ROOT/readiness.log"; then ready=1; break; fi
  sleep 0.1
done
[[ "$ready" == 1 ]]
# 业务请求由另一个 Swift 容器经项目网络访问服务，不在 API 容器内部执行客户端。
compose run --rm --no-deps -e "PBI_ONLINE_TEST_URL=http://$server_name:41105" \
  -e PBI_ONLINE_REPORT_DIRECTORY=/reports/contracts pokemon-swift-validation \
  bash tools/migration/test-swift.sh "$swift_core" > "$POKEOP_REPORT_ROOT/swift-online.log" 2>&1
printf 'Swift online/offline acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
