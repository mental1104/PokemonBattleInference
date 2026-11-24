#!/usr/bin/env bash
# 用途：真实空 PG/全量 CSV 下比较原 FastAPI 与独立 Go HTTP/Core 的静态计算器。
# 输入：项目固定源码与可选构建/报告目录；输出完整 build、初始化、pytest 差分及实例日志。
# 副作用：只创建本脚本专属 maintenance PG/API，退出保存日志并精确清理，不访问生产 URL。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-calculator-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pokemon-go-calculator-pg-$$"
readonly server_name="pokemon-go-calculator-api-$$"
postgres_id=""
server_id=""
# 参数只传给本项目已声明维护服务；不改变通用模板或部署常驻服务。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；归档精确实例日志，再停止本脚本创建的 ID，tmpfs 自动释放。
cleanup(){ if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1; docker stop "$server_id" > /dev/null; fi; if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1; docker stop "$postgres_id" > /dev/null; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS=-L/build/p3/calculator-core -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c \
 'cmake -S /source/core -B /build/p3/calculator-core -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF && cmake --build /build/p3/calculator-core --target pbi_abi -j2 && cd /source/server && mkdir -p /build/p3/calculator && go build -a -o /build/p3/calculator/pbi-core-worker ./cmd/pbi-core-worker && go build -a -o /build/p3/calculator/pbi-server ./cmd/pbi-server && CGO_ENABLED=0 go build -o /build/p3/calculator/pbi-db-init ./cmd/pbi-db-init && go test -race -count=1 -run ^TestCalculator -v ./internal/httpapi && go vet ./internal/catalog ./internal/httpapi' \
 > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/calculator/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/calculator/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
# 独立测试客户端容器与 API/PG 分进程；oracle 只替换连接生命周期，复用原 SQL/用例/HTTP schema。
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_URL="http://$server_name:41105" -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" pokemon-validation sh -c \
 'cd /source && python -m pytest -o cache_dir=/build/p3/calculator-pytest-cache -v tests/migration/test_go_calculator.py' \
 > "$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Go calculator acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
