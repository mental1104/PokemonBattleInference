#!/usr/bin/env bash
# 用途：实际构建并验收不携带 Python/编译器的 Go 运行镜像和独立数据初始化镜像。
# 输入：固定项目源码与已声明维护构建镜像；输出构建/初始化/公开HTTP/运行文件清单和日志。
# 副作用：只创建本次专属 tmpfs PG/API，自有 API 发布随机回环端口，退出精确清理。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-images-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pokemon-go-image-postgres-$$"
postgres_id=""
server_id=""
# 参数仅传到本项目声明的 maintenance 服务，不启停生产服务。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；先保存精确实例日志，再停止本脚本创建的 ID。
cleanup(){ if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1; docker stop "$server_id" > /dev/null; fi; if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1; docker stop "$postgres_id" > /dev/null; fi; }
mkdir -p "$POKEOP_REPORT_ROOT"
trap cleanup EXIT
if ! docker image inspect pokemon-migration-validation:local > /dev/null 2>&1; then compose build pokemon-validation > "$POKEOP_REPORT_ROOT/build-environment.log" 2>&1; fi
compose build pokemon-go-image pokemon-go-db-init-image > "$POKEOP_REPORT_ROOT/images-build.log" 2>&1
docker image inspect pokemon-go-server:migration pokemon-go-db-init:migration --format '{{.Id}} {{.Size}} {{.Architecture}}' > "$POKEOP_REPORT_ROOT/images.txt"
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-go-db-init-image > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
server_id="$(compose run --rm --no-deps -d --name "pokemon-go-image-server-$$" --publish 127.0.0.1::41105 -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-go-image)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for attempt in {1..30}; do if curl -fsS "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .2; done
# 先确认能完整读取实际运行容器文件清单，再检查没有在线 Python/shell/编译工具。
docker export "$server_id" | tar -tf - > "$POKEOP_REPORT_ROOT/runtime-files.txt"
if rg '(^|/)(python[0-9.]*|g\+\+|gcc|go|sh|bash)$' "$POKEOP_REPORT_ROOT/runtime-files.txt" > "$POKEOP_REPORT_ROOT/unexpected-runtime-tools.txt"; then exit 1; fi
for route in 'calculator/pokemon/149' 'calculator/pokemon/149/moves?limit=2&type=dragon' 'calculator/pokemon/149/abilities' 'calculator/items' 'stat-configurations?role=attacker&pokemon_id=149' 'inference/jobs'; do
 name="$(printf '%s' "$route" | tr '/?&=' '____')"
 status="$(curl -sS --max-time 15 -D "$POKEOP_REPORT_ROOT/$name.headers" -o "$POKEOP_REPORT_ROOT/$name.json" -w '%{http_code}' "$endpoint/v1/$route")"
 printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/$name.status"
 [[ "$status" == 200 ]]
done
status="$(curl -sS --max-time 15 -H 'Content-Type: application/json' --data-binary "@$POKEOP_SOURCE_ROOT/tests/vectors/abi-calculations.v1.request.json" -D "$POKEOP_REPORT_ROOT/core.headers" -o "$POKEOP_REPORT_ROOT/core.json" -w '%{http_code}' "$endpoint/v1/core/calculate")"
printf '%s\n' "$status" > "$POKEOP_REPORT_ROOT/core.status"
[[ "$status" == 200 ]]
python3 - "$POKEOP_SOURCE_ROOT/tests/vectors/abi-calculations.v1.response.json" "$POKEOP_REPORT_ROOT/core.json" <<'PY'
"""独立宿主客户端比较完整冻结响应；不调用或导入服务端实现。"""
import json
import sys
from pathlib import Path
expected, actual = (json.loads(Path(name).read_text()) for name in sys.argv[1:])
assert actual == expected, "container HTTP response differs from the shared ABI fixture"
PY
printf 'Go runtime image acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
