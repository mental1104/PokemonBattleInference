#!/usr/bin/env bash
# 用途：独立Swift客户端→正式Go HTTP→PG/daemon/Core，实际验收原任务提交/幂等/进度/结果和在线/同步。
# 输入：显式PBI_GO_CORE_BUILD_DIR/PBI_SWIFT_CORE_BUILD_DIR（容器内各自兼容的已验证archive）；可覆写POKEOP目录。
# 输出：Backup中编译/导入/健康/Swift/服务日志及真实请求；任何实际业务或测试失败返回非零。
# 副作用：仅使用项目已声明maintenance服务，独占run --rm PG/API/worker；不连接生产数据库、不复用未知容器。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/swift-jobs-$(date +%Y%m%d-%H%M%S)}"
readonly go_core="${PBI_GO_CORE_BUILD_DIR:?Set a verified container Go Core archive directory}"
readonly swift_core="${PBI_SWIFT_CORE_BUILD_DIR:?Set a verified container Swift Core archive directory}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pbi-swift-jobs-pg-$$"
readonly server_name="pbi-swift-jobs-api-$$"
readonly worker_name="pbi-swift-jobs-worker-$$"
postgres_id=""
server_id=""
worker_id=""
# 参数为项目维护服务命令；源码只读，构建与报告目录沿既有声明挂载。
compose() { bash "$manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；先归档精确实例，再停止本次ID，不按名称前缀或全局prune清理其他任务。
cleanup() {
    if [[ -n "$worker_id" ]]; then docker logs "$worker_id" > "$POKEOP_REPORT_ROOT/worker.log" 2>&1 || true; docker stop "$worker_id" >/dev/null || true; fi
    if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$server_id" >/dev/null || true; fi
    if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$postgres_id" >/dev/null || true; fi
}
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/p4-jobs-server" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$go_core" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation \
    sh -c 'cd /source/server && go build -a -p 2 -o /build/p4-jobs-server/ ./cmd/pbi-server ./cmd/pbi-core-worker ./cmd/pbi-worker ./cmd/pbi-db-init' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for _ in {1..100}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop >/dev/null 2>&1; then break; fi; sleep .1; done
database="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable"
compose run --rm --no-deps -e PBI_POSTGRES_DSN="$database" pokemon-validation /build/p4-jobs-server/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/knowledge-import.json" 2> "$POKEOP_REPORT_ROOT/knowledge-import.log"
# 新来源契约的旧记录/null、编码路径、404与损坏边界使用同一独占PG；存储夹具不冒充Core执行。
compose run --rm --no-deps -e CGO_LDFLAGS="-L$go_core" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp \
    -e PBI_TEST_POSTGRES_DSN="$database" pokemon-validation sh -ec 'cd /source/server
go test -a -race -p 2 ./internal/httpapi -run "^TestConfigurationResultMetadataPostgres$" -count=1 -v
go vet ./internal/httpapi' > "$POKEOP_REPORT_ROOT/metadata-http-postgres.log" 2>&1
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_POSTGRES_DSN="$database" -e PBI_CORE_WORKER_PATH=/build/p4-jobs-server/pbi-core-worker pokemon-validation /build/p4-jobs-server/pbi-server)"
worker_id="$(compose run --rm --no-deps -d --name "$worker_name" -e PBI_POSTGRES_DSN="$database" pokemon-validation /build/p4-jobs-server/pbi-worker --revision battle-inference.summary-exploration.v2 --native-executable /build/p4-jobs-server/pbi-core-worker)"
endpoint="http://$(docker port "$server_id" 41105/tcp)"
ready=false
for _ in {1..100}; do if curl -fsS --max-time 1 "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then ready=true; break; fi; sleep .1; done
[[ "$ready" == true ]]
# 三组真实网络入口全部连接独立同一服务；缺API/错误结果不能通过SKIP转成绿色。
compose run --rm --no-deps -e "PBI_ONLINE_TEST_URL=http://$server_name:41105" -e "PBI_SYNC_TEST_URL=http://$server_name:41105" \
    -e "PBI_CONFIGURATION_JOB_TEST_URL=http://$server_name:41105" -e PBI_CONFIGURATION_JOB_REPORT_DIRECTORY=/reports/jobs \
    -e PBI_ONLINE_REPORT_DIRECTORY=/reports/online -e PBI_KNOWLEDGE_HTTP_REPORT_DIRECTORY=/reports/knowledge-http pokemon-swift-validation \
    bash tools/migration/test-swift.sh "$swift_core" > "$POKEOP_REPORT_ROOT/swift-live.log" 2>&1
printf 'Real Swift job, online and synchronization acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
