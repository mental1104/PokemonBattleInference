#!/usr/bin/env bash
# 用途：在维护环境中导入真实 CSV，验收 Go 配置/目录/同步 API 的 PostgreSQL 合同。
# 输入：可选源码、构建、报告目录；按当前源码重建独立 Core，不读取生产连接变量。
# 输出：原始初始化、Go race/vet、curl 响应和服务日志保存到独立 Backup。
# 副作用：创建两个自有临时容器，只停止本脚本精确 ID，退出自动清理 tmpfs 数据。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-server-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pokemon-go-server-postgres-$$"
readonly core_directory="${PBI_VALIDATION_CORE_DIRECTORY:-/build/p3/core}"
postgres_id=""
server_id=""

# 参数透传到本项目已声明的维护服务；不调用生产 Compose。
compose() {
 bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"
}

# 无参数；先保存日志，后停止本脚本成功创建的精确容器，禁止全局清理。
cleanup() {
 if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1; docker stop "$server_id" > /dev/null; fi
 if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1; docker stop "$postgres_id" > /dev/null; fi
}
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
# 默认独立重建；并行开发时可显式指定已验证同版本静态库，Go 仍强制使用 -a。
if [[ -z "${PBI_VALIDATION_CORE_DIRECTORY:-}" ]]; then
compose run --rm --no-deps pokemon-validation sh -c \
 'cmake -S /source/core -B /build/p3/core -DCMAKE_BUILD_TYPE=Release && cmake --build /build/p3/core -j2 && ctest --test-dir /build/p3/core --output-on-failure' \
 > "$POKEOP_REPORT_ROOT/core-build.log" 2>&1
else
 printf 'Using explicitly supplied native archive: %s; C++ tests are not rerun in this invocation.\n' "$core_directory" > "$POKEOP_REPORT_ROOT/core-build.log"
fi
compose run --rm --no-deps -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c \
 'cd /source/server && go build -o /build/p3/pbi-db-init ./cmd/pbi-db-init' \
 > "$POKEOP_REPORT_ROOT/db-init-build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do
 if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi
 sleep 0.2
done
# 真正的 Go 初始化命令导入全部固定 CSV/原 MV；第二次执行独立验证幂等复用。
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
 pokemon-validation /build/p3/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv \
 > "$POKEOP_REPORT_ROOT/catalog-initialization.json" 2> "$POKEOP_REPORT_ROOT/catalog-initialization.log"
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
 pokemon-validation /build/p3/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv \
 > "$POKEOP_REPORT_ROOT/catalog-reuse.json" 2> "$POKEOP_REPORT_ROOT/catalog-reuse.log"
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp \
 -e PBI_TEST_CORE_WORKER=/build/p3/pbi-core-worker -e PBI_TEST_CRASH_WORKER=/build/p3/pbi-crash-worker -e PBI_CONTRACT_FIXTURES=/source/tests/vectors -e PBI_TEST_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
 -e PBI_TEST_WORKER_DAEMON=/build/p3/pbi-worker \
 -e PBI_TEST_CATALOG_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
 -e PBI_TEST_KNOWLEDGE_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" -e PBI_KNOWLEDGE_CSV_ROOT=/source/submodules/pokeapi/data/v2/csv pokemon-validation sh -c \
 'cd /source/server && go build -a -o /build/p3/pbi-core-worker ./cmd/pbi-core-worker && go build -a -o /build/p3/pbi-worker ./cmd/pbi-worker && go build -o /build/p3/pbi-crash-worker ./internal/workerprocess/testdata/crashing-worker && go test -a -race -count=1 -v ./... && go test -race -count=10 -v -run ^TestDaemonStopRetainsLeasesAndRecovers$ ./internal/nativeworker && go vet ./... && go build -a -o /build/p3/pbi-server ./cmd/pbi-server' \
 > "$POKEOP_REPORT_ROOT/go-postgres.log" 2>&1
server_id="$(compose run --rm --no-deps -d --name "pokemon-go-server-$$" --publish 127.0.0.1::41105 \
 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
 pokemon-validation /build/p3/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do
 if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi
 sleep 0.2
done
# 独立宿主 curl 是公开 HTTP 客户端，与 Go 服务及数据库进程隔离。
for route in 'calculator/pokemon/149' 'calculator/pokemon/149/moves?limit=2&type=dragon' 'calculator/pokemon/149/abilities' 'calculator/items' 'stat-configurations?role=attacker&pokemon_id=149' 'inference/jobs'; do
 name="$(printf '%s' "$route" | tr '/?&=' '____')"
 status="$(curl -sS --max-time 15 -D "$POKEOP_REPORT_ROOT/$name.headers" -o "$POKEOP_REPORT_ROOT/$name.json" -w '%{http_code}' "$endpoint/v1/$route")"
 printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/$name.status"
 [[ "$status" == 200 ]]
done
printf 'Go/PostgreSQL acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
