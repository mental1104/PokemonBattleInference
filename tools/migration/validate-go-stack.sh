#!/usr/bin/env bash
# 用途：完整原Vue/Nginx、Go API、独立Worker、PostgreSQL的隔离验收和实际健康/回滚/恢复演练。
# 输入：干净源码checkout和已验证的旧API镜像；所有状态仅在本次tmpfs，端口仅随机回环。
# 输出：HDD独占报告含HTTP、浏览器截图/trace、实际镜像ID、数据库备份及各实例日志。
# 副作用：只构建本项目镜像和创建专属maintenance run --rm容器，退出精确清理本项目网络。
set -euo pipefail
umask 077
export PBI_STACK_VALIDATION_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_SOURCE_ROOT="${PBI_STACK_SOURCE_ROOT:-$PBI_STACK_VALIDATION_ROOT}"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-stack-$(date +%Y%m%d-%H%M%S)}"
export PBI_STACK_SERVER_IMAGE="${PBI_STACK_SERVER_IMAGE:-pokemon-go-server:stack-validation}"
export PBI_STACK_DATA_IMAGE="${PBI_STACK_DATA_IMAGE:-pokemon-go-data:stack-validation}"
export PBI_STACK_FRONTEND_IMAGE="${PBI_STACK_FRONTEND_IMAGE:-pokemon-go-frontend:stack-validation}"
export PBI_STACK_DATABASE=pokeop
export PBI_STACK_SUBNET="${PBI_STACK_SUBNET:?Set PBI_STACK_SUBNET after checking local routes and Docker networks}"
readonly previous_image="${PBI_STACK_PREVIOUS_IMAGE:?Set PBI_STACK_PREVIOUS_IMAGE to a previously verified API image}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly project="pokemon-go-stack-$$"
postgres_id=""
server_id=""
worker_id=""
frontend_id=""
endpoint=""

# 参数透传本次专属Compose项目；不会启停原生产或其他测试项目。
compose() { bash "$manager" compose -p "$project" -f "$PBI_STACK_VALIDATION_ROOT/deploy/compose.go-stack-validation.yaml" --profile maintenance "$@"; }
# 无参数；先解除自己API的STOP信号再保存日志/退出，最后仅删除本项目创建的网络。
cleanup() {
  local role id
  for role in frontend server worker postgres; do
    case "$role" in frontend) id="$frontend_id";; server) id="$server_id";; worker) id="$worker_id";; postgres) id="$postgres_id";; esac
    if [[ -n "$id" ]]; then
      if [[ "$role" == server ]]; then docker kill --signal=CONT "$id" > /dev/null 2>&1 || true; fi
      docker logs "$id" > "$POKEOP_REPORT_ROOT/$role.log" 2>&1 || true
      docker stop "$id" > /dev/null 2>&1 || true
    fi
  done
  compose down > "$POKEOP_REPORT_ROOT/cleanup.log" 2>&1 || true
}
# id 为自己的API容器，expected为实际Docker健康终态，name为独立证据文件前缀。
wait_health() {
  local id="$1" expected="$2" name="$3" actual
  for _ in {1..40}; do
    actual="$(docker inspect "$id" --format '{{.State.Health.Status}}')"
    if [[ "$actual" == "$expected" ]]; then
      docker inspect "$id" --format '{{json .State.Health}}' > "$POKEOP_REPORT_ROOT/$name.json"
      return
    fi
    sleep 1
  done
  printf 'API did not reach expected health status: %s\n' "$expected" >&2
  return 1
}
# method/path/name/expected为公开HTTP合同；可选body是本次报告内已有JSON文件。
request() {
  local method="$1" path="$2" name="$3" expected="$4" body="${5:-}" status
  local arguments=()
  if [[ -n "$body" ]]; then arguments=(-H 'Content-Type: application/json' --data-binary "@$body"); fi
  status="$(curl --silent --show-error --max-time 40 -X "$method" "${arguments[@]}" -D "$POKEOP_REPORT_ROOT/$name.headers" -o "$POKEOP_REPORT_ROOT/$name.json" -w '%{http_code}' "$endpoint$path")"
  printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/$name.status"
  [[ "$status" == "$expected" ]]
}
# image为明确的运行镜像；database为本次自有库，启动后等待实际Docker探针通过。
start_api() {
  export PBI_STACK_SERVER_IMAGE="$1" PBI_STACK_DATABASE="$2"
  server_id="$(compose run --rm --no-deps -d --name "$project-api" --use-aliases --publish 127.0.0.1::41104 backend)"
  wait_health "$server_id" healthy "$3"
  endpoint="http://$(docker port "$server_id" 41104/tcp)"
}

mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/p6-browser"
[[ -z "$(git -C "$POKEOP_SOURCE_ROOT" status --porcelain)" ]] || { echo 'Stack source must be a clean committed checkout' >&2; exit 2; }
readonly previous_id="$(docker image inspect "$previous_image" --format '{{.Id}}')"
trap cleanup EXIT
compose build backend db-init frontend > "$POKEOP_REPORT_ROOT/build.log" 2>&1
readonly current_id="$(docker image inspect "$PBI_STACK_SERVER_IMAGE" --format '{{.Id}}')"
[[ "$previous_id" != "$current_id" ]] || { echo 'Rollback requires two different verified image IDs' >&2; exit 2; }
git -C "$POKEOP_SOURCE_ROOT" rev-parse HEAD > "$POKEOP_REPORT_ROOT/source-commit.txt"
docker image inspect "$current_id" "$previous_id" "$PBI_STACK_DATA_IMAGE" "$PBI_STACK_FRONTEND_IMAGE" --format '{{json .}}' > "$POKEOP_REPORT_ROOT/images.jsonl"
postgres_id="$(compose run --rm --no-deps -d --name "$project-postgres" --use-aliases postgres)"
for _ in {1..100}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .1; done
compose run --rm --no-deps db-init > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
worker_id="$(compose run --rm --no-deps -d --name "$project-worker" worker)"
start_api "$current_id" pokeop health-initial
request GET /healthz health 200
request POST /v1/core/calculate core 200 "$POKEOP_SOURCE_ROOT/tests/vectors/abi-calculations.v1.request.json"
python3 - "$POKEOP_SOURCE_ROOT/tests/vectors/abi-calculations.v1.response.json" "$POKEOP_REPORT_ROOT/core.json" <<'PY'
"""独立客户端比较完整冻结Core响应，不复制或导入应用计算规则。"""
import json
import sys
from pathlib import Path
expected, actual = (json.loads(Path(path).read_text()) for path in sys.argv[1:])
assert actual == expected, "stack Core response differs from the frozen fixture"
PY
frontend_id="$(compose run --rm --no-deps -d --name "$project-frontend" --publish 127.0.0.1::80 frontend)"
endpoint="http://$(docker port "$frontend_id" 80/tcp)"
for _ in {1..40}; do if curl -fsS "$endpoint/api/healthz" > "$POKEOP_REPORT_ROOT/proxy-health.json" 2>/dev/null; then break; fi; sleep .1; done
curl -fsS "$endpoint/" > "$POKEOP_REPORT_ROOT/index.html"
compose run --rm --no-deps browser npm install --prefix /build/p6-browser --no-audit --no-fund playwright@1.65.0 > "$POKEOP_REPORT_ROOT/browser-install.log" 2>&1
compose run --rm --no-deps -e PBI_STACK_WEB_URL="http://$project-frontend" browser node /validation/accept-web-go.mjs > "$POKEOP_REPORT_ROOT/browser.log" 2>&1

# 故障真实暂停API PID1；Docker必须观测失败并在恢复后重新healthy。
docker kill --signal=STOP "$server_id" > /dev/null
wait_health "$server_id" unhealthy health-stopped
docker kill --signal=CONT "$server_id" > /dev/null
wait_health "$server_id" healthy health-recovered
endpoint="http://$(docker port "$server_id" 41104/tcp)"
cat > "$POKEOP_REPORT_ROOT/configuration-request.json" <<'JSON'
{"name":"Go stack preservation","nature_id":"hardy","role":"attacker","binding_kind":"pokemon","pokemon_id":212,"evs":{"hp":0,"attack":252,"defense":0,"special_attack":0,"special_defense":0,"speed":0}}
JSON
request POST /v1/stat-configurations configuration-created 201 "$POKEOP_REPORT_ROOT/configuration-request.json"
request GET '/v1/stat-configurations?role=attacker&pokemon_id=212' configurations-before 200
docker exec "$postgres_id" pg_dump -U pokeop -d pokeop -Fc > "$POKEOP_REPORT_ROOT/pokeop-before-rollback.dump"
sha256sum "$POKEOP_REPORT_ROOT/pokeop-before-rollback.dump" > "$POKEOP_REPORT_ROOT/database-backup.sha256"
docker logs "$server_id" > "$POKEOP_REPORT_ROOT/api-current.log" 2>&1
docker stop "$server_id" > /dev/null
server_id=""
start_api "$previous_id" pokeop health-rollback
request GET '/v1/stat-configurations?role=attacker&pokemon_id=212' configurations-rollback 200
docker logs "$server_id" > "$POKEOP_REPORT_ROOT/api-rollback.log" 2>&1
docker stop "$server_id" > /dev/null
server_id=""
docker exec "$postgres_id" createdb -U pokeop recovered
docker exec -i "$postgres_id" pg_restore -U pokeop -d recovered --exit-on-error < "$POKEOP_REPORT_ROOT/pokeop-before-rollback.dump"
start_api "$current_id" recovered health-restored
request GET '/v1/stat-configurations?role=attacker&pokemon_id=212' configurations-restored 200
python3 - "$POKEOP_REPORT_ROOT" <<'PY'
"""验证旧镜像回退和独立恢复库保留完整用户读取模型，不能只比较行数。"""
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
snapshots = [json.loads((root / (name + '.json')).read_text()) for name in ('configurations-before', 'configurations-rollback', 'configurations-restored')]
assert snapshots[0] == snapshots[1] == snapshots[2], 'configuration changed during rollback or restore'
created = json.loads((root / 'configuration-created.json').read_text())
assert created['name'] == 'Go stack preservation'
PY
[[ "$(docker inspect "$worker_id" --format '{{.State.Running}}')" == true ]]
printf 'Go stack, browser, health, rollback and restore acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
