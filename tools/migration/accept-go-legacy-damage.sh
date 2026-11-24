#!/usr/bin/env bash
# 用途：从空PG纯Go导CSV，验证旧damage故障修复和现代reference_static完整兼容；不把二者算法混用。
# 输入：已验证.9 Core目录及可选构建/报告根；输出完整请求/旧构造oracle/随机支持集、现代完整diff与race/vet。
# 副作用：仅本项目已声明maintenance run --rm、自有tmpfs PG/API；不访问生产连接，退出精确回收。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-legacy-damage-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core_directory="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core .9 archive directory inside maintenance}"
readonly postgres_name="pokemon-go-legacy-pg-$$"
readonly server_name="pokemon-go-legacy-api-$$"
postgres_id=""
server_id=""
# 参数仅透传到本项目维护Compose，不查询生产服务。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；先保存日志，再按精确ID停止本次API/PG，错误与信号使用相同清理。
cleanup(){ if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$server_id" > /dev/null || true; fi; if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$postgres_id" > /dev/null || true; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'mkdir -p /build/p3/legacy-http /build/p3/legacy-format && cp /source/server/internal/catalog/legacy_damage*.go /build/p3/legacy-format/ && cp /source/server/internal/httpapi/legacy_damage.go /build/p3/legacy-format/legacy_http.go && cp /source/server/internal/httpapi/calculator.go /build/p3/legacy-format/ && gofmt -w /build/p3/legacy-format/*.go && cd /source/server && go build -a -o /build/p3/legacy-http/ ./cmd/pbi-server ./cmd/pbi-core-worker && CGO_ENABLED=0 go build -o /build/p3/legacy-http/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/catalog ./internal/httpapi' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/legacy-http/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp -e PBI_TEST_CATALOG_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation sh -c 'cd /source/server && go test -race -count=1 -v -run "^(TestLegacyFullPokedexSnapshotPostgres|TestCalculatorSchemaRejectsBeforeDatabase)$" ./internal/catalog ./internal/httpapi' > "$POKEOP_REPORT_ROOT/go-race.log" 2>&1
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/legacy-http/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" -e PBI_TEST_GO_CALCULATOR_URL="http://$server_name:41105" -e PBI_LEGACY_HTTP_REPORT=/reports pokemon-validation python -m pytest -v -o cache_dir=/build/p3/legacy-http-pytest-cache /source/tests/migration/test_go_legacy_damage.py /source/tests/migration/test_go_calculator.py > "$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Go legacy and reference static damage acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
