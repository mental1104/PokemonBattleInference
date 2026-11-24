#!/usr/bin/env bash
# 用途：单独验证纯 Go CSV/schema/MV 初始化，不依赖 C++ 构建或在线 Python。
# 输入：固定源码与可选构建/报告目录；输出完整首次/重跑回执、差分/PG/race/vet 日志。
# 副作用：只创建本次自有 tmpfs PG，结束保存日志并停止精确容器 ID，不读取生产连接。
set -euo pipefail
export POKEOP_SOURCE_ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
export POKEOP_BUILD_ROOT="${POKEOP_BUILD_ROOT:-/volume2/docker/pokemon-migration-validation/build}"
export POKEOP_REPORT_ROOT="${POKEOP_REPORT_ROOT:-/volume1/homes/mental1104/Backup/PokemonBattleInference/go-knowledge-$(date +%Y%m%d-%H%M%S)}"
readonly nas_manager="${POKEOP_NAS_MANAGER:-/volume2/workflow/code/infra/homelab-services/tools/nas-management/nas-manage.sh}"
readonly postgres_name="pokemon-go-knowledge-$$"
postgres_id=""
# 参数透传到本项目维护服务，不调用常驻业务服务。
compose(){ bash "$nas_manager" compose -p pokemon-migration-validation -f "$POKEOP_SOURCE_ROOT/deploy/compose.validation.yaml" -f "$POKEOP_SOURCE_ROOT/deploy/compose.go-validation.yaml" --profile maintenance "$@"; }
# 无参数；先归档日志，后停止本脚本成功创建的精确 ID。
cleanup(){ if [[ -n "$postgres_id" ]]; then docker logs "$postgres_id" > "$POKEOP_REPORT_ROOT/postgres.log" 2>&1; docker stop "$postgres_id" > /dev/null; fi; }
mkdir -p "$POKEOP_REPORT_ROOT" "$POKEOP_BUILD_ROOT/go-tmp" "$POKEOP_BUILD_ROOT/p3"
trap cleanup EXIT
compose run --rm --no-deps -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp -e CGO_ENABLED=0 pokemon-validation sh -c 'cd /source/server && go build -a -o /build/p3/pbi-db-init ./cmd/pbi-db-init' > "$POKEOP_REPORT_ROOT/build.log" 2>&1
postgres_id="$(compose run --rm --no-deps -d --name "$postgres_name" pokemon-go-postgres)"
for attempt in {1..30}; do if docker exec "$postgres_id" pg_isready -U pokeop -d pokeop > /dev/null 2>&1; then break; fi; sleep .2; done
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/initialization.json" 2> "$POKEOP_REPORT_ROOT/initialization.log"
compose run --rm --no-deps -e PBI_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" pokemon-validation /build/p3/pbi-db-init --csv-root /source/submodules/pokeapi/data/v2/csv > "$POKEOP_REPORT_ROOT/reuse.json" 2> "$POKEOP_REPORT_ROOT/reuse.log"
compose run --rm --no-deps -e GOCACHE=/build/go-cache -e GOPATH=/build/go-path -e GOTMPDIR=/build/go-tmp -e PBI_KNOWLEDGE_CSV_ROOT=/source/submodules/pokeapi/data/v2/csv -e PBI_TEST_POSTGRES_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" -e PBI_TEST_KNOWLEDGE_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" -e PBI_TEST_CATALOG_DSN="postgres://pokeop@$postgres_name:5432/pokeop?sslmode=disable" -e PBI_TEST_INFERENCE_SNAPSHOT_OUTPUT=/reports/inference-snapshot.json pokemon-validation sh -c 'cd /source/server && go test -a -race -count=1 -v ./internal/knowledge ./internal/catalog && go vet ./internal/knowledge ./internal/catalog ./cmd/pbi-db-init' > "$POKEOP_REPORT_ROOT/knowledge-postgres.log" 2>&1
# 仅维护验证层运行原 Python repository，检查新 Go 全部字段；在线初始化/资料读取仍只依赖 Go。
compose run --rm --no-deps -e PBI_TEST_GO_CALCULATOR_POSTGRES_URL="postgresql+psycopg://pokeop@$postgres_name:5432/pokeop" -e PBI_TEST_INFERENCE_SNAPSHOT_OUTPUT=/reports/inference-snapshot.json pokemon-validation sh -c 'cd /source && python -m pytest -o cache_dir=/build/p3/knowledge-pytest-cache -v tests/migration/test_go_inference_knowledge.py' > "$POKEOP_REPORT_ROOT/inference-differential.log" 2>&1
printf 'Go knowledge acceptance passed. Reports: %s\n' "$POKEOP_REPORT_ROOT"
