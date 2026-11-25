#!/usr/bin/env bash
# 用途：在本次独占空PG用原Python重建完整CSV/五图样本及用户记录，再验证Go显式接管。
# 输入：固定源码、显式样本源、SSD构建和HDD报告；输出旧/新完整历史数据dump、接管/复用回执。
# 副作用：仅初始化自己创建的tmpfs PG，结束保存日志并停止精确容器ID；不读取生产连接。
set -euo pipefail
umask 077
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:?Set a private legacy adoption report directory}"
export PBI_SPRITES_SOURCE_ROOT="${PBI_SPRITES_SOURCE_ROOT:?Set an explicit owned fixture or complete sprites source}"
readonly manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pokemon-legacy-adoption-$$"
postgres_id=""
table_arguments=()
# 参数透传到已有维护服务；不启停任何常驻或生产服务，来源仅只读挂载。
compose() { bash "$manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.sprites-validation.yaml" --profile maintenance "$@"; }
# 无参数；只保存自己PG的日志并停止精确ID，tmpfs由--rm释放。
cleanup() { if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1; docker stop "$postgres_id" > /dev/null; fi; }
# 参数为报告文件名；导出接管前已存在的全部raw/runtime表和序列，不含新增Go表。
# 只去除pg_dump随机的执行限制令牌行，业务COPY字节、序列和用户数据逐字节保留。
snapshot() {
  docker exec "$postgres_id" pg_dump -U pokeop -d pokeop --data-only --no-owner --no-privileges "${table_arguments[@]}" |
    sed '/^\\restrict /d; /^\\unrestrict /d' > "$POKEOP_REPORT_ROOT/$1"
}
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/p3/legacy-adoption" "$POKEOP_BUILD_ROOT/go-tmp"
trap cleanup EXIT
compose run --rm --no-deps -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp -e CGO_ENABLED=0 pokemon-validation bash -c 'cd /source/server && go build -trimpath -o /build/p3/legacy-adoption/pbi-db-init ./cmd/pbi-db-init' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for _ in {1..50}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
# reset命令仅面向刚创建的专属空PG；使用原Python importer及RawBase，绝不从Go数据删除标记来替代。
compose run --rm --no-deps -e PGHOST="$postgres_name" -e PGPORT=5432 -e PGDATABASE=pokeop -e PGUSER=pokeop pokemon-validation python scripts/reset_postgres_db.py --allow-remote-host --csv-dir /source/submodules/pokeapi/data/v2/csv --with-materialized-views --with-sprites --sprites-dir /sprites-source > "$POKEOP_REPORT_ROOT/python-initialization.log" 2>&1
docker exec -i "$postgres_id" psql -U pokeop -d pokeop -v ON_ERROR_STOP=1 > "$POKEOP_REPORT_ROOT/legacy-fixture.log" <<'SQL'
INSERT INTO poke_runtime.stat_configurations(id,tenant_id,name,nature_id,role,binding_kind,pokemon_id,ev_hp,ev_attack,ev_defense,ev_special_attack,ev_special_defense,ev_speed,iv_hp,iv_attack,iv_defense,iv_special_attack,iv_special_defense,iv_speed,is_deleted)
VALUES('legacy-kept-id','local','Historical preserved configuration','hardy','both','pokemon',212,252,100,0,0,0,0,31,31,31,31,31,31,false);
INSERT INTO poke_runtime.battle_inference_jobs(job_id,ruleset_id,version_group_id,calculation_revision,status,attempt_count)
VALUES('legacy-job-kept','pokemon-champion',25,'battle-inference.summary-exploration.v2','cancelled',0);
SQL
docker exec "$postgres_id" psql -U pokeop -d pokeop -Atc "SELECT quote_ident(n.nspname)||'.'||quote_ident(c.relname) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('poke_raw','poke_runtime') AND c.relkind IN ('r','S') ORDER BY 1" > "$POKEOP_REPORT_ROOT/legacy-relations.txt"
while IFS= read -r relation; do table_arguments+=("--table=$relation"); done < "$POKEOP_REPORT_ROOT/legacy-relations.txt"
[[ ${#table_arguments[@]} -gt 180 ]]
snapshot before.sql
# 默认入口必须实际拒绝；只有显式接管才可核验并登记，无条件成功不能视为通过。
if compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/legacy-adoption/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/default-rejected.json" 2> "$POKEOP_REPORT_ROOT/default-rejected.log"; then echo 'Default initialization unexpectedly accepted the legacy target' >&2; exit 1; fi
rg -F 'knowledge target contains unversioned data; explicit migration is required' "$POKEOP_REPORT_ROOT/default-rejected.log" > /dev/null
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/legacy-adoption/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv --adopt-legacy-knowledge > "$POKEOP_REPORT_ROOT/adopted.json" 2> "$POKEOP_REPORT_ROOT/adopted.log"
snapshot after.sql
cmp "$POKEOP_REPORT_ROOT/before.sql" "$POKEOP_REPORT_ROOT/after.sql"
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/legacy-adoption/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/reused.json" 2> "$POKEOP_REPORT_ROOT/reused.log"
snapshot reused.sql
cmp "$POKEOP_REPORT_ROOT/before.sql" "$POKEOP_REPORT_ROOT/reused.sql"
jq -e '.legacy_adopted == true and .reused == false and .csv_tables == 177 and .source_rows == 1051800 and .inserted_rows == 1051052' "$POKEOP_REPORT_ROOT/adopted.json" > /dev/null
jq -e '.legacy_adopted == true and .reused == true and .inserted_rows == 1051052' "$POKEOP_REPORT_ROOT/reused.json" > /dev/null
sha256sum "$POKEOP_REPORT_ROOT/before.sql" "$POKEOP_REPORT_ROOT/after.sql" "$POKEOP_REPORT_ROOT/reused.sql" > "$POKEOP_REPORT_ROOT/historical-data.sha256"
printf 'Legacy Python-to-Go adoption and complete historical data preservation passed.\n'
