#!/usr/bin/env bash
# 用途：真实 PostgreSQL + 独立 Core 子进程验证 coordinator 的完成、取消、停机恢复及错误结果。
# 输入：已有 Core 静态库；PBI_NATIVE_CORE_BUILD_DIR 为容器内路径，默认 /build/core。
# 依赖：已声明 maintenance/Docker；源码只读，SSD 构建，报告保存到 HDD Backup。
# 输出：完整 race/vet/构建日志及原生库摘要；任何断言/环境错误非零退出。
# 副作用：只创建本次独占 tmpfs PG，不发布端口，退出只停止精确容器 ID，不操作生产。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/native-worker-$(date +%Y%m%d-%H%M%S)}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly native_core="${PBI_NATIVE_CORE_BUILD_DIR:-/build/core}"
readonly postgres_name="pbi-native-worker-pg-$$"
postgres_id=""

# 参数透传项目 Compose；输出/退出码原样返回，仅访问本仓库已声明的 maintenance 服务。
compose() {
  bash "$manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" --profile maintenance "$@"
}

# 无参数；保存本次 PG 日志并仅回收成功创建的精确实例，run --rm 负责移除。
cleanup() {
  if [[ -n "$postgres_id" ]]; then
    docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true
    docker stop "$postgres_id" > /dev/null || true
  fi
}

mkdir -p "$POKEOP_BUILD_ROOT/nativeworker/go-tmp" "$POKEOP_REPORT_ROOT"
compose run --rm --no-deps -e "CGO_LDFLAGS=-L$native_core" -e NATIVE_CORE="$native_core" \
  -e GOPATH=/build/go-path -e GOCACHE=/build/go-cache -e GOTMPDIR=/build/nativeworker/go-tmp pokemon-validation bash -euo pipefail -c '
    test -s "$NATIVE_CORE/libpbi_core.a" && test -s "$NATIVE_CORE/libpbi_abi.a"
    sha256sum "$NATIVE_CORE/libpbi_core.a" "$NATIVE_CORE/libpbi_abi.a" > /reports/native-archives.sha256
    cd server
    go build -a -o /build/nativeworker/pbi-core-worker ./cmd/pbi-core-worker
    go build -a -o /build/nativeworker/pbi-worker ./cmd/pbi-worker
    CGO_ENABLED=0 go build -o /build/nativeworker/pbi-healthcheck ./cmd/pbi-healthcheck
  ' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-validation-postgres)"
trap cleanup EXIT
ready=0
for attempt in {1..100}; do
  if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then ready=1; break; fi
  sleep 0.1
done
[[ "$ready" == 1 ]]
compose run --rm --no-deps -e "CGO_LDFLAGS=-L$native_core" -e GOPATH=/build/go-path \
  -e GOCACHE=/build/go-cache -e GOTMPDIR=/build/nativeworker/go-tmp \
  -e PBI_TEST_CORE_WORKER=/build/nativeworker/pbi-core-worker \
  -e PBI_TEST_WORKER_DAEMON=/build/nativeworker/pbi-worker \
  -e "PBI_TEST_POSTGRES_DSN=postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
  pokemon-validation bash -euo pipefail -c 'cd server && go test -a -race -count=1 -v -timeout 120s ./internal/nativeworker && go vet ./internal/nativeworker ./cmd/pbi-worker ./cmd/pbi-healthcheck' \
  > "$POKEOP_REPORT_ROOT/worker-postgres.log" 2>&1
printf 'Native worker acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
