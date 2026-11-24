#!/usr/bin/env bash
# 用途：原模板/EV-IV WithSpeed HTTP经真实Go/Core与原Python同PG完整差分；从空库纯Go导固定CSV。
# 输入：已验证.8以上Core目录及可选构建/报告根；输出完整请求/双端响应、初始化、race/vet及实例日志。
# 副作用：仅已声明maintenance的自有tmpfs PG/API，退出精确清理；不修改生产资料或启动Python在线业务。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-configuration-solver-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core_directory="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core .8 archive directory inside maintenance}"
readonly postgres_name="pokemon-go-solver-pg-$$"
readonly server_name="pokemon-go-solver-api-$$"
postgres_id=""
server_id=""
# 参数只传给本项目已声明的维护Compose，不查找或连接生产服务。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；归档本次实例日志并按精确ID停止，失败/信号也执行相同回收。
cleanup(){ if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$server_id" > /dev/null || true; fi; if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$postgres_id" > /dev/null || true; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'cd /source/server && mkdir -p /build/p3/solver /build/p3/solver-format && cp /source/server/internal/catalog/goals.go /source/server/internal/httpapi/configuration_solver*.go /build/p3/solver-format/ && gofmt -w /build/p3/solver-format/*.go && go build -a -o /build/p3/solver/ ./cmd/pbi-server ./cmd/pbi-core-worker && CGO_ENABLED=0 go build -o /build/p3/solver/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/catalog ./internal/httpapi' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/solver/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp -e PBI_TEST_CORE_WORKER=/build/p3/solver/pbi-core-worker -e PBI_CONTRACT_FIXTURES=/source/tests/vectors -e PBI_TEST_CATALOG_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation sh -c 'cd /source/server && go test -race -count=1 -v -run "^(TestHTTPCoreRoundTrip|TestInferenceProjectionPostgres)$" ./internal/httpapi ./internal/catalog' > "$POKEOP_REPORT_ROOT/go-race.log" 2>&1
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/solver/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" -e PBI_TEST_GO_CALCULATOR_URL="http://$server_name:41105" -e PBI_SOLVER_REPORT=/reports pokemon-validation python -m pytest -v -o cache_dir=/build/p3/solver-pytest-cache /source/tests/migration/test_go_configuration_solver.py > "$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Go configuration solver acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
