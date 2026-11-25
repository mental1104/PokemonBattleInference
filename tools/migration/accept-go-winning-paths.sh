#!/usr/bin/env bash
# 用途：完整固定CSV/空PG/真实Go图缓存→独立Core winning查询，与原Python公开HTTP逐字段对照。
# 输入：显式已验证且注册winning_paths的Core目录及可选报告根；输出真实请求响应/构建/资料初始化日志。
# 副作用：仅声明maintenance run --rm、自有临时PG/API；退出按精确ID归档清理，不访问生产。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-winning-paths-$(date +%Y%m%d-%H%M%S)}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core directory with winning_paths}"
readonly pg_name="pokemon-winning-pg-$$"
readonly api_name="pokemon-winning-api-$$"
pg_id=""; api_id=""
# 参数只透传到本项目已声明维护角色，不改变通用NAS服务模板。
compose(){ bash "$manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；保存两实例日志后精确停止；--rm与tmpfs释放本次临时状态，历史报告保留。
cleanup(){ if [[ -n "$api_id" ]]; then docker logs "$api_id" >"$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$api_id" >/dev/null 2>&1 || true; fi; if [[ -n "$pg_id" ]]; then docker logs "$pg_id" >"$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$pg_id" >/dev/null 2>&1 || true; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'mkdir -p /build/p3/winning /build/p3/winning-format && cp /source/server/internal/httpapi/winning_paths*.go /build/p3/winning-format/ && gofmt -w /build/p3/winning-format/*.go && cd /source/server && go build -a -o /build/p3/winning/ ./cmd/pbi-core-worker ./cmd/pbi-server && CGO_ENABLED=0 go build -o /build/p3/winning/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/httpapi' >"$POKEOP_REPORT_ROOT/build.log" 2>&1
pg_id="$(compose run --rm --no-deps -d --name "$pg_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$pg_id" pg_isready -U pokeop -d pokeop >/dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$pg_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/winning/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv >"$POKEOP_REPORT_ROOT/initialization.json" 2>"$POKEOP_REPORT_ROOT/initialization.log"
api_id="$(compose run --rm --no-deps -d --name "$api_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$pg_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/winning/pbi-server)"
readonly endpoint="http://$(docker port "$api_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" >"$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
# oracle只改变连接生命周期及随机graph句柄，不替代事件/完整图/原DFS/精确求解/游标算法。
compose run --rm --no-deps -e PBI_FIXED_INFERENCE_URL="http://$api_name:41105" -e PBI_FIXED_INFERENCE_POSTGRES_URL="postgresql+psycopg://pokeop@$pg_name:5432/pokeop" -e PBI_FIXED_INFERENCE_REPORT_DIRECTORY=/reports pokemon-validation python -m pytest -v -o cache_dir=/build/p3-winning-pytest /source/tests/migration/test_go_winning_paths.py >"$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Go winning paths acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
