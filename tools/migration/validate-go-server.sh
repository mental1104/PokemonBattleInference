#!/usr/bin/env bash
# 用途：在维护环境中导入真实 CSV，验收 Go 配置/目录/同步 API 的 PostgreSQL 合同。
# 输入：已有 Core 构建和可选源码、构建、报告目录；不读取任何生产连接变量。
# 输出：原始初始化、Go race/vet、curl 响应和服务日志保存到独立 Backup。
# 副作用：创建两个自有临时容器，只停止本脚本精确 ID，退出自动清理 tmpfs 数据。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-server-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pokemon-go-server-postgres-$$"
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
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do
 if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi
 sleep 0.2
done
# 这里只调用现有初始化函数作为真实知识夹具；Go HTTP 运行时不加载 Python。
compose run --rm --no-deps -e PGHOST="$postgres_name" -e PGPORT=5432 -e PGUSER=pokeop -e PGDATABASE=pokeop pokemon-validation python -c \
 '"""导入固定 submodule CSV 并创建原物化视图，目标仅为本脚本自有临时库。"""; from pokeop.persistence.bootstrap import init_db; init_db(create_tables=True, import_csv=True, import_sprites=False, create_materialized_views=True, refresh_materialized_views=True)' \
 > "$POKEOP_REPORT_ROOT/catalog-initialization.log" 2>&1
compose run --rm --no-deps -e CGO_LDFLAGS=-L/build/core -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp \
 -e PBI_TEST_CORE_WORKER=/build/pbi-core-worker -e PBI_CONTRACT_FIXTURES=/source/tests/vectors -e PBI_TEST_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
 -e PBI_TEST_CATALOG_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation sh -c \
 'cd /source/server && go build -a -o /build/pbi-core-worker ./cmd/pbi-core-worker && go test -a -race -count=1 -v ./... && go vet ./... && go build -a -o /build/pbi-server ./cmd/pbi-server' \
 > "$POKEOP_REPORT_ROOT/go-postgres.log" 2>&1
server_id="$(compose run --rm --no-deps -d --name "pokemon-go-server-$$" --publish 127.0.0.1::41105 \
 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" \
 pokemon-validation /build/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do
 if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi
 sleep 0.2
done
# 独立宿主 curl 是公开 HTTP 客户端，与 Go 服务及数据库进程隔离。
for route in 'calculator/pokemon/149' 'calculator/pokemon/149/moves?limit=2&type=dragon' 'calculator/pokemon/149/abilities' 'calculator/items' 'stat-configurations?role=attacker&pokemon_id=149'; do
 name="$(printf '%s' "$route" | tr '/?&=' '____')"
 status="$(curl -sS --max-time 15 -D "$POKEOP_REPORT_ROOT/$name.headers" -o "$POKEOP_REPORT_ROOT/$name.json" -w '%{http_code}' "$endpoint/v1/$route")"
 printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/$name.status"
 [[ "$status" == 200 ]]
done
printf 'Go/PostgreSQL acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
