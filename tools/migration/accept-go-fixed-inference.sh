#!/usr/bin/env bash
# 用途：独立Go HTTP/真实空PG/全量CSV/Core固定摘要、图导航、单步与受控旅程对照原Python owning路由。
# 输入：PBI_VALIDATION_CORE_DIRECTORY指定同snapshot完整构建的Core/ABI目录；构建与HDD报告根可显式覆盖。
# 输出：构建/初始化/差分/协议产物及精确实例日志；失败非零，不把缺集成环境当PASS。
# 副作用：只创建自有maintenance PG/API，无生产连接、无daemon，退出精确回收所拥有的容器。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/fixed-inference-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core_directory="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified matching Core/ABI archive directory inside the maintenance container}"
# 显式选择同一真实环境的验收集合；默认仍为已交付summary，graph/all绝不静默缩减。
case "${PBI_FIXED_INFERENCE_SUITE:-summary}" in
  summary) test_files=(tests/migration/test_go_fixed_inference.py) ;;
  graph) test_files=(tests/migration/test_go_fixed_graph.py) ;;
  step) test_files=(tests/migration/test_go_fixed_snapshot.py) ;;
  dragonite) test_files=(tests/migration/test_go_dragonite.py) ;;
  remaining) test_files=(tests/migration/test_go_fixed_snapshot.py tests/migration/test_go_dragonite.py) ;;
  all) test_files=(tests/migration/test_go_fixed_inference.py tests/migration/test_go_fixed_graph.py tests/migration/test_go_fixed_snapshot.py tests/migration/test_go_dragonite.py) ;;
  *) printf 'Unsupported fixed inference acceptance suite\n' >&2; exit 2 ;;
esac
readonly postgres_name="pbi-fixed-inference-pg-$$"
readonly server_name="pbi-fixed-inference-api-$$"
postgres_id=""
server_id=""

# 参数是已有Compose维护命令；返回原输出与状态，不修改模板权限或注册常驻服务。
compose() {
  bash "$nas_manager" compose -p pokemon-migration-validation \
    -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"
}

# 无参数；回收前归档自有实例日志，仅停止已捕获的精确ID，退出后tmpfs自动释放。
cleanup() {
  if [[ -n "$server_id" ]]; then
    docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true
    docker stop "$server_id" > /dev/null 2>&1 || true
  fi
  if [[ -n "$postgres_id" ]]; then
    docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true
    docker stop "$postgres_id" > /dev/null 2>&1 || true
  fi
}

mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e "CGO_LDFLAGS=-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c \
  'cd server && mkdir -p /build/p2-fixed-http && go build -a -o /build/p2-fixed-http/ ./cmd/pbi-server ./cmd/pbi-core-worker && CGO_ENABLED=0 go build -o /build/p2-fixed-http/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/httpapi ./internal/nativeworker' \
  > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..50}; do
  if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi
  sleep 0.2
done
compose run --rm --no-deps -e "PBI_POSTGRES_DSN=postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation \
  /build/p2-fixed-http/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 \
  -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_CORE_WORKER_PATH=/build/p2-fixed-http/pbi-core-worker \
  -e "PBI_POSTGRES_DSN=postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p2-fixed-http/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
ready=0
for attempt in {1..100}; do
  if curl -fsS --max-time 1 "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>> "$POKEOP_REPORT_ROOT/readiness.log"; then ready=1; break; fi
  sleep 0.1
done
[[ "$ready" == 1 ]]
# 客户端是另一维护容器；原Python只注入同一真实PG连接端口，不替代SQL、工厂或solver。
compose run --rm --no-deps -e "PBI_FIXED_INFERENCE_URL=http://$server_name:41105" \
  -e "PBI_FIXED_INFERENCE_POSTGRES_URL=postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" \
  -e PBI_FIXED_INFERENCE_REPORT_DIRECTORY=/reports/http pokemon-validation \
  python -m pytest "${test_files[@]}" -v -o cache_dir=/tmp/pytest-cache --junitxml=/reports/http.xml \
  > "$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Fixed inference HTTP acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
