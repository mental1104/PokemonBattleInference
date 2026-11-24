#!/usr/bin/env bash
# 用途：独立空PG/完整CSV/GoHTTP与原Python逐字段比较固定任务和组合预览，并由真实daemon消费单case。
# 输入：显式已验证Core目录及可选报告根；输出构建/初始化/原HTTP请求响应和daemon实际结果。
# 副作用：仅声明maintenance run --rm，自有PG/API/daemon；退出归档日志并精确清理，不访问生产。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-fixed-workflow-$(date +%Y%m%d-%H%M%S)}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core archive directory inside maintenance}"
readonly pg_name="pokemon-fixed-workflow-pg-$$"
readonly api_name="pokemon-fixed-workflow-api-$$"
readonly worker_name="pokemon-fixed-workflow-worker-$$"
pg_id=""; api_id=""; worker_id=""; worker_pid=""
# 参数仅透传到本项目维护角色；无生产Compose或外部数据库地址。
compose(){ bash "$manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；先停止本次daemon、归档各自日志，再精确停止API/PG，保留所有失败证据。
cleanup(){ if [[ -n "$worker_id" ]]; then docker stop "$worker_id" >/dev/null 2>&1 || true; fi; if [[ -n "$worker_pid" ]]; then wait "$worker_pid" || true; fi; if [[ -n "$api_id" ]]; then docker logs "$api_id" >"$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$api_id" >/dev/null 2>&1 || true; fi; if [[ -n "$pg_id" ]]; then docker logs "$pg_id" >"$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$pg_id" >/dev/null 2>&1 || true; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'mkdir -p /build/p3/fixed-workflow /build/p3/fixed-format && cp /source/server/internal/httpapi/fixed_job_submission.go /source/server/internal/httpapi/move_combinations.go /build/p3/fixed-format/ && gofmt -w /build/p3/fixed-format/*.go && cd /source/server && go build -a -o /build/p3/fixed-workflow/ ./cmd/pbi-server ./cmd/pbi-core-worker ./cmd/pbi-worker && CGO_ENABLED=0 go build -o /build/p3/fixed-workflow/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/httpapi' >"$POKEOP_REPORT_ROOT/build.log" 2>&1
pg_id="$(compose run --rm --no-deps -d --name "$pg_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$pg_id" pg_isready -U pokeop -d pokeop >/dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$pg_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/fixed-workflow/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv >"$POKEOP_REPORT_ROOT/initialization.json" 2>"$POKEOP_REPORT_ROOT/initialization.log"
api_id="$(compose run --rm --no-deps -d --name "$api_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$pg_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/fixed-workflow/pbi-server)"
readonly endpoint="http://$(docker port "$api_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" >"$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
# 原HTTP同库重放阶段不启动daemon，避免两次HTTP之间状态自然推进导致比较时序歧义。
compose run --rm --no-deps -e PBI_FIXED_WORKFLOW_URL="http://$api_name:41105" -e PBI_FIXED_WORKFLOW_DSN="postgresql+psycopg://pokeop@$pg_name:5432/pokeop" -e PBI_FIXED_WORKFLOW_REPORT=/reports pokemon-validation python -m pytest -v -k 'not terminal_replay' -o cache_dir=/build/p3/fixed-workflow-pytest-cache /source/tests/migration/test_go_fixed_jobs_combinations.py >"$POKEOP_REPORT_ROOT/differential.log" 2>&1
# 前台日志防止--rm退出丢证据，使用默认lease120s/database10s，不缩短安全租约。
compose run --rm --no-deps --name "$worker_name" -e PBI_POSTGRES_DSN="postgres://pokeop@$pg_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/fixed-workflow/pbi-worker --revision battle-inference.summary-exploration.v2 --native-executable /build/p3/fixed-workflow/pbi-core-worker --poll 100ms >"$POKEOP_REPORT_ROOT/worker.log" 2>&1 &
worker_pid=$!
for attempt in {1..30}; do if worker_id="$(docker inspect --format '{{.Id}}' "$worker_name" 2>/dev/null)"; then break; fi; sleep .1; done
[[ -n "$worker_id" ]]
job_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["job_id"])' "$POKEOP_REPORT_ROOT/fixed-baseline.go.json")"
for attempt in {1..600}; do
 curl -fsS "$endpoint/v1/inference/jobs/$job_id" >"$POKEOP_REPORT_ROOT/worker-state.json"
 phase="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$POKEOP_REPORT_ROOT/worker-state.json")"
 [[ "$phase" != succeeded ]] || break
 sleep .2
done
[[ "$phase" == succeeded ]]
curl -fsS "$endpoint/v1/inference/configuration-jobs/$job_id/results" >"$POKEOP_REPORT_ROOT/worker-results.json"
python3 - "$POKEOP_REPORT_ROOT/worker-results.json" <<'PY'
"""只核验真实已执行结果/精确概率守恒，不在客户端替代伤害或战斗计算。"""
import json
import sys
from fractions import Fraction
result = json.load(open(sys.argv[1]))
assert result['total'] == 1 and len(result['items']) == 1, result
case = result['items'][0]
assert case['status'] == 'succeeded' and case['node_count'] > 0 and case['edge_count'] > 0, case
assert sum(Fraction(int(case[key]['numerator']), int(case[key]['denominator'])) for key in ('attacker_win_probability', 'defender_win_probability', 'draw_probability')) == 1, case
PY
# 真实终态后再次由两端公开提交，旧合同要求返回当前status但phase字段仍为queued。
compose run --rm --no-deps -e PBI_FIXED_WORKFLOW_URL="http://$api_name:41105" -e PBI_FIXED_WORKFLOW_DSN="postgresql+psycopg://pokeop@$pg_name:5432/pokeop" -e PBI_FIXED_WORKFLOW_REPORT=/reports pokemon-validation python -m pytest -v -k terminal_replay -o cache_dir=/build/p3/fixed-workflow-pytest-cache /source/tests/migration/test_go_fixed_jobs_combinations.py >"$POKEOP_REPORT_ROOT/terminal-replay.log" 2>&1
printf 'Go fixed jobs and move combinations acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
