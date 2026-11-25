#!/usr/bin/env bash
# 用途：从空PG经纯Go导入CSV与真实sprites，原Python完整行差分并独立HTTP核验PNG/ETag。
# 输入：显式PBI_SPRITES_SOURCE_ROOT、已验Core目录及可选报告根；输出首次/重跑回执和全部实测日志。
# 副作用：仅声明maintenance、自有tmpfs PG/API；源只读、不接触生产，退出精确清理本次实例。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-sprites-$(date +%Y%m%d-%H%M%S)}"
export PBI_SPRITES_SOURCE_ROOT="${PBI_SPRITES_SOURCE_ROOT:?Set the explicit local sprite source root}"
readonly core="${PBI_VALIDATION_CORE_DIRECTORY:?Set the verified Core archive directory inside maintenance}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pbi-sprites-pg-$$"
readonly server_name="pbi-sprites-api-$$"
postgres_id=""
server_id=""
# 参数只透传本项目声明的维护Compose；图片源始终只读。
compose() { bash "$manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.sprites-validation.yaml" --profile maintenance "$@"; }
# 无参数；先归档本次日志再停止精确ID，绝不按前缀或全局prune处理其他实例。
cleanup() {
    if [[ -n "$server_id" ]]; then docker logs "$server_id" > "$POKEOP_REPORT_ROOT/server.log" 2>&1 || true; docker stop "$server_id" > /dev/null || true; fi
    if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1 || true; docker stop "$postgres_id" > /dev/null || true; fi
}
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp" "$POKEOP_BUILD_ROOT/p3/sprites"
trap cleanup EXIT
compose run --rm --no-deps -e CGO_LDFLAGS="-L$core" -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp pokemon-validation sh -c 'cd /source/server && go build -a -o /build/p3/sprites/ ./cmd/pbi-server ./cmd/pbi-core-worker && CGO_ENABLED=0 go build -o /build/p3/sprites/pbi-db-init ./cmd/pbi-db-init' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for _ in {1..100}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .1; done
readonly database="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable"
for report in initialization reuse; do
    compose run --rm --no-deps -e PBI_POSTGRES_DSN="$database" pokemon-validation /build/p3/sprites/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv --sprites-root /sprites-source --sprites-commit "${PBI_SPRITES_SOURCE_COMMIT:-}" > "$POKEOP_REPORT_ROOT/$report.json" 2> "$POKEOP_REPORT_ROOT/$report.log"
done
server_id="$(compose run --rm --no-deps -d --name "$server_name" --publish 127.0.0.1::41105 -e PBI_LISTEN=0.0.0.0:41105 -e PBI_POSTGRES_DSN="$database" pokemon-validation /build/p3/sprites/pbi-server)"
readonly endpoint="http://$(docker port "$server_id" 41105/tcp)"
for _ in {1..100}; do if curl -fsS --max-time 1 "$endpoint/healthz" > "$POKEOP_REPORT_ROOT/health.json" 2>/dev/null; then break; fi; sleep .1; done
compose run --rm --no-deps -e PBI_SPRITES_TEST_DSN="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" -e PBI_SPRITES_TEST_URL="http://$server_name:41105" -e PBI_SPRITES_TEST_SOURCE=/sprites-source -e PBI_SPRITES_TEST_REPORTS=/reports pokemon-validation python -m pytest -v -o cache_dir=/build/p3/sprites/pytest-cache /source/tests/migration/test_go_sprite_import.py > "$POKEOP_REPORT_ROOT/differential.log" 2>&1
printf 'Go sprite import and public HTTP acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
