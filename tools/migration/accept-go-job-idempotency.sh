#!/usr/bin/env bash
# 用途：原configuration-jobs跨Python/Go格式与Core元数据变更的真实HTTP幂等回归，不启动worker。
# 输入：显式已验证Core目录及可选报告根；输出原HTTP双方响应、完整知识初始化与构建日志。
# 副作用：仅声明maintenance run --rm、自有空PG/API；退出按精确ID清理，不读取生产连接。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-job-idempotency-$(date +%Y%m%d-%H%M%S)}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core archive directory}"
readonly pg_name="pokemon-job-idempotency-pg-$$"
readonly api_name="pokemon-job-idempotency-api-$$"
pg_id=""; api_id=""
# 参数仅透传到本项目维护角色，不改变通用NAS服务。
compose(){ bash "$manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；归档并停止本次精确API/PG ID，tmpfs数据随--rm释放，报告保留。
cleanup(){ if [[ -n "$api_id" ]]; then docker logs "$api_id" >"$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$api_id" >/dev/null 2>&1 || true; fi; if [[ -n "$pg_id" ]]; then docker logs "$pg_id" >"$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$pg_id" >/dev/null 2>&1 || true; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'mkdir -p /build/p3/job-idempotency /build/p3/idempotency-format && cp /source/server/internal/httpapi/job_submission.go /source/server/internal/httpapi/job_idempotency.go /build/p3/idempotency-format/ && gofmt -w /build/p3/idempotency-format/*.go && cd /source/server && go build -a -o /build/p3/job-idempotency/ ./cmd/pbi-server ./cmd/pbi-core-worker && CGO_ENABLED=0 go build -o /build/p3/job-idempotency/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/httpapi' >"$POKEOP_REPORT_ROOT/build.log" 2>&1
pg_id="$(compose run --rm --no-deps -d --name "$pg_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$pg_id" pg_isready -U pokeop -d pokeop >/dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$pg_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/job-idempotency/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv >"$POKEOP_REPORT_ROOT/initialization.json" 2>"$POKEOP_REPORT_ROOT/initialization.log"
api_id="$(compose run --rm --no-deps -d --name "$api_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$pg_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/job-idempotency/pbi-server)"
readonly endpoint="http://$(docker port "$api_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" >"$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
cat >"$POKEOP_REPORT_ROOT/create-request.json" <<'JSON'
{"contract_version":"one-on-one-move-pool.v1","ruleset_id":"pokemon-champion","version_group_id":25,"calculation_revision":"battle-inference.summary-exploration.v2","dimensions":{"pokemon":"fixed","form":"fixed","level":"fixed","stats":"fixed","ability":"fixed","item":"fixed","moves":"candidate_pool","special_mechanics":"disabled"},"weight_assumption":"uniform_configuration_pair","attacker_policy":"first-legal-action","defender_policy":"first-legal-action","mechanism_admission":"supported_only","attacker":{"fixed":{"pokemon_id":212,"form_id":null,"level":50,"stat_profile_id":"max_atk_plus","ability_identifier":"technician","item_identifier":null},"candidate_move_ids":[404]},"defender":{"fixed":{"pokemon_id":149,"form_id":null,"level":50,"stat_profile_id":"max_hp_def_plus","ability_identifier":"multiscale","item_identifier":null},"candidate_move_ids":[337]},"execution":{"process_count":1,"queue_depth":1,"max_nodes_per_pair":20000,"max_edges_per_pair":80000,"max_turns":100}}
JSON
# 仅替换原HTTP连接端口；原SHA身份/严格准入/SQL任务创建和旧记录冲突都由真实原实现执行。
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_URL="http://$api_name:41105" -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$pg_name:5432/pokeop" -e PBI_SUBMISSION_REPORT=/reports pokemon-validation python -m pytest -v -o cache_dir=/build/p3-idempotency-pytest /source/tests/migration/test_go_job_idempotency.py >"$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Go configuration job idempotency acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
