#!/usr/bin/env bash
# 用途：在明确授权部署且恢复验证通过后，为既有pokeop普通账号准备本应用连接文件。
# 输入：无参数；固定NAS主机、既有数据库/账号及本轮私有备份目录。
# 输出：仅成功摘要；不输出DSN、密码或密码散列。失败保留受限副本并非零退出。
# 依赖：Docker、OpenSSL、jq；副作用仅为pokeop密码和本应用私有settings.env。
# 原凭据ALTER语句仅存HDD私有回退文件；没有活动应用连接才允许首次配置，不改角色权限或HBA。
set -euo pipefail
umask 077
[[ $# == 0 && "$(hostname)" == Condemned-Tower && "$(id -u)" == 1026 ]] || exit 2
readonly records=/volume1/homes/mental1104/Backup/PokemonBattleInference/nas-deployment-20261125
readonly runtime=/volume2/docker/pokemon-battle-inference
[[ -s "$records/recovery/adopt.json" ]] || exit 2
jq -e '.legacy_adopted == true and .source_commit == "1567d53073a069b6c96e1c393c5c490f602e3ab5"' "$records/recovery/adopt.json" >/dev/null
cmp "$records/recovery/source-fingerprints.txt" "$records/recovery/restored-fingerprints.txt"
[[ ! -e "$runtime/settings.env" && ! -e "$records/role-credential-rollback.sql" ]] || { echo 'Credentials already prepared; refusing to rotate again' >&2; exit 2; }

# 无参数；只在容器内读取管理员身份，透传标准输入SQL，密码从不进入命令行参数。
admin_sql() {
  docker exec -i postgresql sh -c 'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres'
}
[[ "$(admin_sql <<'SQL'
SELECT count(*) FROM pg_stat_activity WHERE datname='pokemon_battle_inference' AND backend_type='client backend';
SQL
)" == 0 ]] || { echo 'Existing application database has active clients' >&2; exit 1; }
[[ "$(admin_sql <<'SQL'
SELECT count(*) FROM pg_roles WHERE rolname='pokeop' AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls;
SQL
)" == 1 ]] || exit 1

mkdir -p "$runtime"
chmod 700 "$runtime"
admin_sql > "$records/role-credential-rollback.sql" <<'SQL'
SELECT format('ALTER ROLE pokeop PASSWORD %L;', rolpassword) FROM pg_authid WHERE rolname='pokeop';
SQL
chmod 600 "$records/role-credential-rollback.sql"
readonly pokemon_password="$(openssl rand -hex 32)"
printf 'PBI_POSTGRES_DSN=postgres://pokeop:%s@postgresql:5432/pokemon_battle_inference?sslmode=disable\n' "$pokemon_password" > "$runtime/settings.env"
chmod 600 "$runtime/settings.env"
# 密码仅由OpenSSL十六进制输出组成；通过stdin执行，不在Docker命令、Git或日志中携带。
printf "ALTER ROLE pokeop PASSWORD '%s';\n" "$pokemon_password" | admin_sql > "$records/credential-prepare.log"
printf 'Application credential prepared; original role credential preserved privately.\n'
