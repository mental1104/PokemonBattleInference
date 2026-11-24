#!/usr/bin/env bash
# 用途：空PG全量CSV下，将原候选池HTTP与实际Go/Core逐字段差分；包括未支持合法项及业务错误。
# 输入：显式已验证Core目录及可选构建/报告根；输出原始双端JSON、初始化/构建/pytest日志。
# 副作用：仅maintenance run --rm、自有tmpfs PG/API；退出精确回收，绝不使用生产连接或泛化清理。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-candidate-pools-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core_directory="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core archive directory inside maintenance}"
readonly postgres_name="pokemon-go-candidates-pg-$$"
readonly server_name="pokemon-go-candidates-api-$$"
postgres_id=""
server_id=""
# 参数只透传给已声明的本项目验证Compose；无生产服务操作。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；归档实例日志后只关闭本脚本拥有的成功创建ID，失败仍进入相同回收。
cleanup(){ if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$server_id" > /dev/null || true; fi; if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$postgres_id" > /dev/null || true; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'cd /source/server && mkdir -p /build/p3/candidates /build/p3/candidate-format && cp /source/server/internal/httpapi/candidate_pools.go /source/server/internal/httpapi/catalog.go /build/p3/candidate-format/ && gofmt -w /build/p3/candidate-format/*.go && go build -a -o /build/p3/candidates/ ./cmd/pbi-server ./cmd/pbi-core-worker && CGO_ENABLED=0 go build -o /build/p3/candidates/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/catalog ./internal/httpapi' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/candidates/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/candidates/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" -e PBI_TEST_GO_CALCULATOR_URL="http://$server_name:41105" -e PBI_SUBMISSION_REPORT=/reports pokemon-validation python -m pytest -v -o cache_dir=/build/p3/candidate-pytest-cache /source/tests/migration/test_go_candidate_pools.py > "$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Go candidate pool acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
