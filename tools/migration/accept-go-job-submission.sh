#!/usr/bin/env bash
# 用途：真实原HTTP创建→PG→独立daemon→精确结果闭环；可短暂保留同一隔离服务供独立Swift客户端验收。
# 输入：已验证Core目录、可选构建/报告/保留标志；输出完整请求/响应/进度、实例日志及ready.json。
# 副作用：仅声明maintenance run --rm 的自有PG/API/worker；默认退出精确清理，hold最多15分钟。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-job-submission-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly core_directory="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core archive directory inside the maintenance container}"
readonly postgres_name="pokemon-go-submission-pg-$$"
readonly server_name="pokemon-go-submission-api-$$"
readonly worker_name="pokemon-go-submission-worker-$$"
postgres_id=""
server_id=""
worker_id=""
worker_pid=""
# 参数只传给本项目已声明的维护服务，不访问生产Compose或数据库。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；先停止本次worker，再归档API/PG日志并精确关闭。信号和失败也执行相同回收。
cleanup(){ if [[ -n "$worker_id" ]]; then docker stop "$worker_id" > /dev/null 2>&1 || true; fi; if [[ -n "$worker_pid" ]]; then wait "$worker_pid" || true; fi; if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$server_id" > /dev/null 2>&1 || true; fi; if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$postgres_id" > /dev/null 2>&1 || true; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core_directory" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'cd /source/server && mkdir -p /build/p3/submission && go build -a -o /build/p3/submission/ ./cmd/pbi-core-worker ./cmd/pbi-worker ./cmd/pbi-server && CGO_ENABLED=0 go build -o /build/p3/submission/pbi-db-init ./cmd/pbi-db-init && go vet ./internal/jobs ./internal/httpapi' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/submission/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
# 原准备失败oracle使用相同知识的独占参考库，防止真实Go/Python coordinator互相领取任务；仍无生产连接。
docker exec "$postgres_id" psql -U pokeop -d postgres -c 'CREATE DATABASE pokeop_reference TEMPLATE pokeop' > "$POKEOP_REPORT_ROOT/reference-database.log"
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_MIGRATE=1 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/submission/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
# 前台日志持续归档，避免--rm丢失启动错误；使用真实默认lease120s/DB10s，不靠放宽预算掩盖批量问题。
compose run --rm --no-deps --name "$worker_name" -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/submission/pbi-worker --revision battle-inference.summary-exploration.v2 --native-executable /build/p3/submission/pbi-core-worker --poll 100ms > "$POKEOP_REPORT_ROOT/worker.log" 2>&1 &
worker_pid=$!
for attempt in {1..30}; do if worker_id="$(docker inspect --format '{{.Id}}' "$worker_name" 2>/dev/null)"; then break; fi; sleep .1; done
[[ -n "$worker_id" ]]
# 验收 API/daemon 采用项目运行镜像相同的 1GiB 限制；仅调整本脚本创建的精确实例。
docker update --memory 1g --memory-swap 1g "$server_id" "$worker_id" > "$POKEOP_REPORT_ROOT/resource-update.log"
docker inspect --format '{{.Name}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' "$server_id" "$worker_id" > "$POKEOP_REPORT_ROOT/resource-limits.txt"
cat > "$POKEOP_REPORT_ROOT/create-request.json" <<'JSON'
{"contract_version":"one-on-one-move-pool.v1","ruleset_id":"pokemon-champion","version_group_id":25,"calculation_revision":"battle-inference.summary-exploration.v2","dimensions":{"pokemon":"fixed","form":"fixed","level":"fixed","stats":"fixed","ability":"fixed","item":"fixed","moves":"candidate_pool","special_mechanics":"disabled"},"weight_assumption":"uniform_configuration_pair","attacker_policy":"first-legal-action","defender_policy":"first-legal-action","mechanism_admission":"supported_only","attacker":{"fixed":{"pokemon_id":212,"form_id":null,"level":50,"stat_profile_id":"max_atk_plus","ability_identifier":"technician","item_identifier":null},"candidate_move_ids":[404]},"defender":{"fixed":{"pokemon_id":149,"form_id":null,"level":50,"stat_profile_id":"max_hp_def_plus","ability_identifier":"multiscale","item_identifier":null},"candidate_move_ids":[337]},"execution":{"process_count":1,"queue_depth":1,"max_nodes_per_pair":20000,"max_edges_per_pair":80000,"max_turns":100}}
JSON
status="$(curl -sS --max-time 35 -H 'Content-Type: application/json' -H 'Idempotency-Key: p3-real-http-submit' --data-binary "@$POKEOP_REPORT_ROOT/create-request.json" -D "$POKEOP_REPORT_ROOT/create.headers" -o "$POKEOP_REPORT_ROOT/create.json" -w '%{http_code}' "$endpoint/v1/inference/configuration-jobs")"
printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/create.status"
[[ "$status" == 202 ]]
job_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["job_id"])' "$POKEOP_REPORT_ROOT/create.json")"
printf '{"endpoint":"%s","internal_endpoint":"http://%s:41105","job_id":"%s"}\n' "$endpoint" "$server_name" "$job_id" > "$POKEOP_REPORT_ROOT/ready.json"
for attempt in {1..600}; do
 curl -fsS "$endpoint/v1/inference/configuration-jobs/$job_id" > "$POKEOP_REPORT_ROOT/progress-$attempt.json"
 phase="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$POKEOP_REPORT_ROOT/progress-$attempt.json")"
 if [[ "$phase" == completed || "$phase" == partial || "$phase" == failed || "$phase" == cancelled ]]; then break; fi
 sleep .2
done
curl -fsS "$endpoint/v1/inference/configuration-jobs/$job_id/results" > "$POKEOP_REPORT_ROOT/results.json"
python3 - "$POKEOP_REPORT_ROOT/results.json" <<'PY'
"""独立宿主检查真实任务已成功并交付精确概率；不写死胜者或战斗数学结果。"""
import json
import sys
from fractions import Fraction
with open(sys.argv[1]) as source:
    result = json.load(source)
assert result['total'] == 1 and len(result['items']) == 1, result
case = result['items'][0]
assert case['status'] == 'succeeded', case
probabilities = [Fraction(int(case[key]['numerator']), int(case[key]['denominator'])) for key in ('attacker_win_probability', 'defender_win_probability', 'draw_probability')]
assert sum(probabilities) == 1 and case['node_count'] > 0 and case['edge_count'] > 0, case
PY
# 实际合法十招池由固定 PG 知识支持；全部 strict 与具体组合仍由正式 Core 判定，宿主只准备原 HTTP 输入。
python3 - "$POKEOP_REPORT_ROOT" <<'PY'
"""由已成功的原合同输入改为实际 10×10 池和显式小预算，不在客户端产生组合或结果。"""
import json
import sys
from pathlib import Path
directory = Path(sys.argv[1])
request = json.loads((directory / 'create-request.json').read_text())
for side, identifier in (('attacker', 184), ('defender', 183)):
    request[side]['fixed'].update(pokemon_id=identifier, stat_profile_id='max_atk_neutral', ability_identifier='thick-fat')
    request[side]['candidate_move_ids'] = [21, 33, 55, 56, 304, 401, 802, 851, 861, 885]
request['execution'].update(max_nodes_per_pair=1000, max_edges_per_pair=5000, max_turns=20)
(directory / 'bulk-request.json').write_text(json.dumps(request, ensure_ascii=True))
PY
curl -sS --max-time 35 -H 'Content-Type: application/json' -H 'Idempotency-Key: p3-bulk-44100-shared-template' --data-binary "@$POKEOP_REPORT_ROOT/bulk-request.json" -D "$POKEOP_REPORT_ROOT/bulk-create.headers" -o "$POKEOP_REPORT_ROOT/bulk-create.json" -w '%{http_code} %{time_total}\n' "$endpoint/v1/inference/configuration-jobs" > "$POKEOP_REPORT_ROOT/bulk-create.status"
[[ "$(cut -d ' ' -f1 "$POKEOP_REPORT_ROOT/bulk-create.status")" == 202 ]]
bulk_id="$(python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["submitted_configuration_pairs"] == 44100; print(value["job_id"])' "$POKEOP_REPORT_ROOT/bulk-create.json")"
for attempt in {1..100}; do
 curl -fsS "$endpoint/v1/inference/configuration-jobs/$bulk_id" > "$POKEOP_REPORT_ROOT/bulk-before-cancel.json"
 phase="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$POKEOP_REPORT_ROOT/bulk-before-cancel.json")"
 [[ "$phase" != running ]] || break
 sleep .1
done
[[ "$phase" == running ]]
curl -fsS --max-time 15 -X POST "$endpoint/v1/inference/configuration-jobs/$bulk_id/cancel" > "$POKEOP_REPORT_ROOT/bulk-cancel.json"
for attempt in {1..300}; do
 curl -fsS "$endpoint/v1/inference/configuration-jobs/$bulk_id" > "$POKEOP_REPORT_ROOT/bulk-after-cancel.json"
 phase="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$POKEOP_REPORT_ROOT/bulk-after-cancel.json")"
 [[ "$phase" != cancelled ]] || break
 sleep .1
done
[[ "$phase" == cancelled ]]
python3 - "$POKEOP_REPORT_ROOT/bulk-after-cancel.json" <<'PY'
"""核验真实取消后的全池守恒；不将预算截断改写为成功或数学平局。"""
import json
import sys
value = json.load(open(sys.argv[1]))
counts = value['counts']
assert counts['total'] == counts['completed'] == 44100, counts
assert counts['pending'] == counts['running'] == 0 and counts['cancelled'] > 0, counts
assert sum(counts[key] for key in ('succeeded', 'failed', 'truncated', 'cancelled')) == 44100, counts
PY
# bulk_id 只接受本服务生成的规范ID；SQL只读本次独占PG，保存真实完整定义及未压缩/压缩字节。
[[ "$bulk_id" =~ ^battle-inference-idempotent-[0-9a-f]{64}$ ]]
docker exec "$postgres_id" psql -U pokeop -d pokeop -Atc "SELECT definition_json::text FROM poke_runtime.go_job_definitions WHERE job_id='$bulk_id'" > "$POKEOP_REPORT_ROOT/bulk-definition.json"
docker exec "$postgres_id" psql -U pokeop -d pokeop -Atc "SELECT octet_length(definition_json::text),pg_column_size(definition_json),json_array_length(definition_json->'cases'),octet_length((definition_json->'core_request_template')::text),octet_length((definition_json->'admission')::text) FROM poke_runtime.go_job_definitions WHERE job_id='$bulk_id'" > "$POKEOP_REPORT_ROOT/bulk-definition-size.tsv"
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" -e PBI_TEST_PREPARATION_REFERENCE_DSN="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop_reference" -e PBI_TEST_GO_CALCULATOR_URL="http://$server_name:41105" -e PBI_SUBMISSION_REPORT=/reports pokemon-validation python -m pytest -v -o cache_dir=/build/p3/submission-pytest-cache /source/tests/migration/test_go_job_submission.py /source/tests/migration/test_go_job_preparation.py > "$POKEOP_REPORT_ROOT/oracle.log" 2>&1
printf 'Actual HTTP job submission completed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
if [[ "${PBI_JOB_VALIDATION_HOLD:-0}" == 1 ]]; then
 touch "$POKEOP_REPORT_ROOT/hold"
 readonly hold_started="$SECONDS"
 while [[ -f "$POKEOP_REPORT_ROOT/hold" && $((SECONDS-hold_started)) -lt 900 ]]; do sleep 1; done
fi
