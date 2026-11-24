#!/usr/bin/env bash
# 用途：验证四条原 configuration-jobs 读取/取消 API，原 Python store 直接写独占 PG 后逐字段比较。
# 输入：固定源码、可选已验证 Core 库目录/构建/报告目录；输出真实PG/race/vet/HTTP差分和实例日志。
# 副作用：只创建自有 maintenance PG/API；不启动worker，不声称这些读取夹具经过计算器执行。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-configuration-jobs-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pokemon-go-configuration-jobs-pg-$$"
readonly server_name="pokemon-go-configuration-jobs-api-$$"
readonly core_directory="${PBI_VALIDATION_CORE_DIRECTORY:-/build/p3/configuration-jobs-core}"
postgres_id=""
server_id=""
# 参数只传给项目声明的维护服务，禁止误用生产Compose或数据库地址。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；归档本次精确实例的日志，再停止本脚本创建的ID，自动释放tmpfs。
cleanup(){ if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1; docker stop "$server_id" > /dev/null; fi; if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1; docker stop "$postgres_id" > /dev/null; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
if [[ -z "${PBI_VALIDATION_CORE_DIRECTORY:-}" ]]; then
 compose run --rm --no-deps pokemon-validation sh -c 'cmake -S /source/core -B /build/p3/configuration-jobs-core -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF && cmake --build /build/p3/configuration-jobs-core --target pbi_abi -j2' > "$POKEOP_REPORT_ROOT/core-build.log" 2>&1
fi
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'cd /source/server && mkdir -p /build/p3/configuration-jobs && go build -a -o /build/p3/configuration-jobs/pbi-server ./cmd/pbi-server && go build -a -o /build/p3/configuration-jobs/pbi-core-worker ./cmd/pbi-core-worker && go build -a -o /build/p3/configuration-jobs/pbi-worker ./cmd/pbi-worker && go vet ./internal/jobs ./internal/httpapi' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/configuration-jobs/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
# 独立的 HTTP 差分仍应执行以保留证据；最后统一返回原生回归失败，不能把失败静默忽略为绿色。
native_status=0
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp -e PBI_TEST_CORE_WORKER=/build/p3/configuration-jobs/pbi-core-worker -e PBI_TEST_WORKER_DAEMON=/build/p3/configuration-jobs/pbi-worker -e PBI_CONTRACT_FIXTURES=/source/tests/vectors -e PBI_TEST_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation sh -c 'cd /source/server && go test -a -race -count=1 -v ./internal/jobs ./internal/nativeworker && go test -race -count=1 -v -run ^TestJobsHTTPPostgres$ ./internal/httpapi' > "$POKEOP_REPORT_ROOT/jobs-postgres.log" 2>&1 || native_status=$?
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_URL="http://$server_name:41105" -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" -e PBI_TEST_CONFIGURATION_JOB_REPORT=/reports/http pokemon-validation sh -c 'cd /source && python -m pytest -o cache_dir=/build/p3/configuration-jobs-pytest-cache -v tests/migration/test_go_configuration_jobs.py' > "$POKEOP_REPORT_ROOT/differential.log" 2>&1
if [[ "$native_status" -ne 0 ]]; then printf 'Native regression failed; HTTP evidence was preserved.\n' >&2; exit "$native_status"; fi
printf 'Go configuration job queries passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
