#!/usr/bin/env bash
# 用途：NAS 上复现迁移验证；输入为 core 或 all（默认），无需生产凭据。
# 依赖：已声明的 maintenance Compose、Docker、Bash、初始化的 Git submodule。
# 输出：Backup 中保存日志、junit 与环境清单；构建缓存只写独立 SSD 目录。
# 副作用：构建测试镜像，all 模式启动自有临时 PostgreSQL；退出时仅停止该实例。
set -euo pipefail

POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_SOURCE_ROOT
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/migration-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly validation_mode="${1:-all}"
readonly postgres_name="pokemon-migration-validation-$$"
postgres_id=""

# 参数为项目 Compose 子命令；透传退出码，只操作本项目声明的 maintenance 服务。
compose() {
  bash "$nas_manager" compose -p pokemon-migration-validation \
    -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" --profile maintenance "$@"
}

# 无参数；只停止本脚本成功创建的精确容器 ID，run --rm 负责移除临时容器。
cleanup() {
  if [[ -n "$postgres_id" ]]; then
    docker stop "$postgres_id" > /dev/null
  fi
}

case "$validation_mode" in
  core|all) ;;
  *) printf 'Usage: %s [core|all]\n' "$0" >&2; exit 2 ;;
esac
mkdir -p "$POKEOP_BUILD_ROOT" "$POKEOP_REPORT_ROOT"
compose build pokemon-validation > "$POKEOP_REPORT_ROOT/environment-build.log" 2>&1

if [[ "$validation_mode" == all ]]; then
  postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-validation-postgres)"
  trap cleanup EXIT
  # URL 只指向这次自有容器；原 fixture 在进入业务断言前完成 SQL readiness 检查。
  compose run --rm --no-deps \
    -e "POKEOP_TEST_POSTGRES_URL=postgresql+psycopg2://pokeop@$postgres_name:5432/pokeop" \
    pokemon-validation make test CORE_BUILD_DIR=/build/core \
    'PYTEST_ADDOPTS=-q -o cache_dir=/tmp/pytest-cache --junitxml=/reports/python-regression.xml' \
    > "$POKEOP_REPORT_ROOT/python-regression.log" 2>&1
  compose run --rm --no-deps pokemon-web-validation \
    > "$POKEOP_REPORT_ROOT/web-regression.log" 2>&1
  compose run --rm --no-deps pokemon-web-validation npm run build \
    > "$POKEOP_REPORT_ROOT/web-build.log" 2>&1
else
  compose run --rm --no-deps pokemon-validation sh -c \
    'make test-core CORE_BUILD_DIR=/build/core && PBI_CORE_VECTOR_RUNNER=/build/core/pbi_core_vectors python -m pytest tests/migration -q -o cache_dir=/tmp/pytest-cache' \
    > "$POKEOP_REPORT_ROOT/core-regression.log" 2>&1
fi
compose run --rm --no-deps pokemon-validation python -m pip freeze \
  > "$POKEOP_REPORT_ROOT/python-environment.txt"
printf 'Validation passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
