#!/usr/bin/env bash
# 用途：实际 API 进程验证默认30秒计算截止、子进程回收及SIGTERM时完整取消响应。
# 输入：当前源码及显式已建C ABI目录；输出真实HTTP状态/用时、进程清单和停止日志。
# 副作用：仅启动一个自有维护API和测试慢子进程，不连接数据库，不计算或伪造业务结果。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/http-lifecycle-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly case_name="http-lifecycle-$$"
readonly library_dir="${PBI_CORE_LIBRARY_DIR:-/build/p3/core}"
server_id=""
log_pid=""
request_pid=""
wait_pid=""
# 参数仅传到已声明维护服务，无生产连接或常驻容器生命周期操作。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" --profile maintenance "$@"; }
# 无参数；只停止自有实例，并等待已经启动的日志/HTTP客户端退出，不覆盖已归档日志。
cleanup(){ if [[ -n "$server_id" ]]; then docker stop "$server_id" > /dev/null 2>&1 || true; fi; if [[ -n "$log_pid" ]]; then kill -TERM "$log_pid" 2>/dev/null || true; fi; for owned_pid in "$request_pid" "$wait_pid" "$log_pid"; do if [[ -n "$owned_pid" ]]; then wait "$owned_pid" 2>/dev/null || true; fi; done; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/p3/$case_name" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$library_dir" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp -e PBI_HTTP_CASE="$case_name" pokemon-validation sh -c 'cd /source/server && go build -a -o "/build/p3/$PBI_HTTP_CASE/pbi-server" ./cmd/pbi-server && go build -o "/build/p3/$PBI_HTTP_CASE/pbi-slow-worker" ./internal/httpapi/testdata/slow-worker' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
server_id="$(compose run --rm --no-deps -d --name "$case_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_CORE_WORKER_PATH="/build/p3/$case_name/pbi-slow-worker" -e PBI_HTTP_TEST_STARTED="/build/p3/$case_name/started.pid" pokemon-validation "/build/p3/$case_name/pbi-server")"
docker logs --follow "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 & log_pid=$!
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .1; done
# 真实默认截止不注入短测试超时；应在30秒左右返回完整504，而非socket无响应。
curl -sS --max-time 36 -H 'Content-Type: application/json' --data '{"schema_version":1,"operations":[]}' -D "$POKEOP_REPORT_ROOT/deadline.headers" -o "$POKEOP_REPORT_ROOT/deadline.json" -w '%{http_code} %{time_total}\n' "$endpoint/v1/core/calculate" > "$POKEOP_REPORT_ROOT/deadline.status"
docker top "$server_id" -eo pid,args > "$POKEOP_REPORT_ROOT/after-deadline-processes.txt"
if rg 'pbi-slow-worker' "$POKEOP_REPORT_ROOT/after-deadline-processes.txt" > /dev/null; then exit 1; fi
python3 - "$POKEOP_REPORT_ROOT/deadline.status" <<'PY'
"""检查完整HTTP504和真实默认截止用时，不从进度或socket错误推断成功。"""
import sys
from pathlib import Path
status, elapsed = Path(sys.argv[1]).read_text().split()
assert status == '504' and 29 <= float(elapsed) < 35, 'default deadline differs'
PY
# 清空本次独占启动标记，再确认第二个child实际运行后发送SIGTERM。
: > "$POKEOP_BUILD_ROOT/p3/$case_name/started.pid"
curl -sS --max-time 15 -H 'Content-Type: application/json' --data '{"schema_version":1,"operations":[]}' -D "$POKEOP_REPORT_ROOT/shutdown.headers" -o "$POKEOP_REPORT_ROOT/shutdown.json" -w '%{http_code}\n' "$endpoint/v1/core/calculate" > "$POKEOP_REPORT_ROOT/shutdown.status" & request_pid=$!
for attempt in {1..100}; do if [[ -s "$POKEOP_BUILD_ROOT/p3/$case_name/started.pid" ]]; then break; fi; sleep .02; done
[[ -s "$POKEOP_BUILD_ROOT/p3/$case_name/started.pid" ]]
docker top "$server_id" -eo pid,args > "$POKEOP_REPORT_ROOT/before-shutdown-processes.txt"
rg 'pbi-slow-worker' "$POKEOP_REPORT_ROOT/before-shutdown-processes.txt" > /dev/null
docker wait "$server_id" > "$POKEOP_REPORT_ROOT/exit.status" & wait_pid=$!
docker kill --signal TERM "$server_id" > "$POKEOP_REPORT_ROOT/signal.txt"
wait "$request_pid"; request_pid=""
wait "$wait_pid"; wait_pid=""; server_id=""
# 某些 Docker daemon 在 run --rm 后保持 logs --follow 连接，停止自有日志客户端避免验收挂起。
kill -TERM "$log_pid" 2>/dev/null || true
wait "$log_pid" 2>/dev/null || true; log_pid=""
rg 'listening on ' "$POKEOP_REPORT_ROOT/server.log" > /dev/null
[[ "$(cat "$POKEOP_REPORT_ROOT/shutdown.status")" == 408 ]]
[[ "$(cat "$POKEOP_REPORT_ROOT/exit.status")" == 0 ]]
printf 'HTTP deadline and shutdown acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
