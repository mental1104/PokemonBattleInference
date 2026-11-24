SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c
export PS1 :=

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# 迁移验证必须使用本仓库固定版本的 common，避免相邻源码悄悄改变行为基线。
COMMON_ROOT ?= $(REPO_ROOT)/submodules/common
COMMON_ROOT := $(abspath $(COMMON_ROOT))

# Ensure repo sources are importable alongside the shared common/python package.
PYTHONPATH_LIST := $(REPO_ROOT)
ifneq ($(wildcard $(COMMON_ROOT)/python),)
  PYTHONPATH_LIST := $(COMMON_ROOT)/python:$(PYTHONPATH_LIST)
endif
ifneq ($(wildcard $(COMMON_ROOT)/export/python),)
  PYTHONPATH_LIST := $(COMMON_ROOT)/export/python:$(PYTHONPATH_LIST)
endif
export PYTHONPATH := $(PYTHONPATH_LIST)

VENV_DIR := $(REPO_ROOT)/.venv
VENV_BIN := $(VENV_DIR)/bin
VENV_PYTHON := $(VENV_BIN)/python3
VENV_PIP := $(VENV_BIN)/pip
COMMON_PYTHON := $(COMMON_ROOT)/python
MENTAL1104_PATH := $(COMMON_PYTHON)/mental1104
COMMON_PYPROJECT := $(COMMON_PYTHON)/pyproject.toml
COMMON_REQUIREMENTS := $(COMMON_PYTHON)/requirements.txt
EXPORT_LAYER_PATH := $(abspath $(COMMON_ROOT)/export/python)
PARENT_ROOT := $(abspath $(REPO_ROOT)/..)
COMPOSE_FILE ?= $(REPO_ROOT)/docker-compose.yaml
COMPOSE := docker compose -f "$(COMPOSE_FILE)"

CLEAN_PATTERNS := \
  __pycache__ \
  *.py[cod] \
  *.so \
  .coverage \
  .coverage.* \
  .pytest_cache \
  .hypothesis \
  .cache \
  htmlcov \
  .tox \
  .nox \
  build \
  dist \
  .eggs \
  *.egg-info \
  .venv \
  venv \
  env \
  ENV \
  env.bak \
  venv.bak

.PHONY: default install test coverage clean setup \
	compose-config compose-init compose-up compose-down compose-rebuild \
	compose-assets-rebuild compose-ps compose-logs compose-reset

install:
	python3 -m pip install -r requirements.txt --break-system-packages

test: test-core
	pytest

# macOS/Linux 使用同一入口；外部构建目录允许 NAS 源码保持只读挂载。
CORE_BUILD_DIR ?= $(REPO_ROOT)/build/core
CMAKE ?= cmake
export PBI_CORE_VECTOR_RUNNER := $(CORE_BUILD_DIR)/pbi_core_vectors
export PBI_CORE_LIBRARY_DIR := $(CORE_BUILD_DIR)
# 原生差分入口均由同一次CMake构建提供；避免已有runner在统一入口中因缺环境变量被跳过。
export PBI_CONFIGURATION_STATS_RUNNER := $(CORE_BUILD_DIR)/pbi_configuration_stats_vectors
export PBI_CONFIGURATION_MOVES_RUNNER := $(CORE_BUILD_DIR)/pbi_configuration_moves_vectors
export PBI_CONFIGURATION_SPACE_RUNNER := $(CORE_BUILD_DIR)/pbi_configuration_space_vectors
export PBI_JOB_MOVE_POOL_RUNNER := $(CORE_BUILD_DIR)/pbi_job_move_pool_vectors
export PBI_CONFIGURATION_GOALS_RUNNER := $(CORE_BUILD_DIR)/pbi_configuration_goals_vectors
export PBI_CONFIGURATION_AGGREGATE_RUNNER := $(CORE_BUILD_DIR)/pbi_configuration_aggregate_vectors
export PBI_CONFIGURATION_SPREAD_SEARCH_RUNNER := $(CORE_BUILD_DIR)/pbi_configuration_spread_search_vectors
export PBI_EVENT_ANALYSIS_RUNNER := $(CORE_BUILD_DIR)/pbi_event_analysis_vectors
export PBI_LEGACY_DAMAGE_RUNNER := $(CORE_BUILD_DIR)/pbi_legacy_damage_vectors
export PBI_REFERENCE_STATIC_DAMAGE_RUNNER := $(CORE_BUILD_DIR)/pbi_reference_static_damage_vectors

.PHONY: test-bindings test-native
test-bindings: test-core
	pytest tests/migration/test_native_bindings.py

test-native: test-core
	pytest tests/migration

.PHONY: test-core
test-core:
	$(CMAKE) -S "$(REPO_ROOT)/core" -B "$(CORE_BUILD_DIR)" -DCMAKE_BUILD_TYPE=Release
	$(CMAKE) --build "$(CORE_BUILD_DIR)" --parallel 2
	ctest --test-dir "$(CORE_BUILD_DIR)" --output-on-failure

coverage:
	pytest --cov=pokeop/domain --cov=pokeop/application --cov-report=term-missing

setup:
	# 1) 创建虚拟环境
	if [ ! -d "$(VENV_DIR)" ]; then \
	  python3 -m venv "$(VENV_DIR)"; \
	fi
	# 1.1) 确保 pip/setuptools/wheel 可用（供后续本地可编辑安装使用）
	"$(VENV_PYTHON)" -m pip install --no-build-isolation --upgrade pip setuptools wheel
	# 2) 如果存在 common，则安装本地 mental1104；否则跳过，使用系统安装的版本
	if [ -d "$(COMMON_PYTHON)" ] && [ -d "$(MENTAL1104_PATH)" ]; then \
	  echo "使用本地 common: $(COMMON_PYTHON)"; \
	  @COMMON_REQ_BACKUP="$(COMMON_REQUIREMENTS).bak.setup"; \
	  restore_req() { [ -f "$$COMMON_REQ_BACKUP" ] && mv "$$COMMON_REQ_BACKUP" "$(COMMON_REQUIREMENTS)"; }; \
	  trap 'restore_req' EXIT; \
	  if grep -q 'file://../export/python' "$(COMMON_REQUIREMENTS)"; then \
	    cp "$(COMMON_REQUIREMENTS)" "$$COMMON_REQ_BACKUP"; \
	    python3 - "$(COMMON_REQUIREMENTS)" "$(EXPORT_LAYER_PATH)" <<-'PY'
	from pathlib import Path; import sys
	req = Path(sys.argv[1]); target = Path(sys.argv[2]).resolve()
	req.write_text(req.read_text().replace("file://../export/python", f"file://{target}"))
	PY
	  fi; \
	  "$(VENV_PIP)" install --force-reinstall --no-build-isolation -e "$(COMMON_PYTHON)"; \
	  restore_req; trap - EXIT; \
	else \
	  echo "未找到本地 common，跳过本地安装，使用系统可用的 mental1104（若已安装）"; \
	fi
	# 3) 安装当前项目的 requirements.txt
	"$(VENV_PIP)" install -r "$(REPO_ROOT)/requirements.txt"

compose-config:
	$(COMPOSE) --profile ops config --services

compose-init:
	$(COMPOSE) build backend
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm db-init

compose-up:
	$(COMPOSE) --profile ops config --services >/dev/null
	$(COMPOSE) build frontend backend
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm db-init
	$(COMPOSE) up -d backend worker frontend --remove-orphans

compose-frontend-rebuild:
	$(COMPOSE) build frontend
	$(COMPOSE) up -d frontend

compose-down:
	$(COMPOSE) down --remove-orphans

compose-rebuild:
	$(COMPOSE) build --no-cache frontend backend
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm db-init
	$(COMPOSE) up -d --force-recreate backend worker frontend --remove-orphans

compose-assets-rebuild:
	$(COMPOSE) build backend
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm db-init \
	  python3 scripts/reset_postgres_db.py \
	  --allow-remote-host \
	  --with-sprites \
	  --with-materialized-views

compose-ps:
	$(COMPOSE) ps

compose-logs:
	$(COMPOSE) logs -f --tail=200

compose-reset:
	$(COMPOSE) down -v --remove-orphans

clean:
	@echo "Removing common build/cache artifacts (only if gitignored when git metadata is present)"
	@for pattern in $(CLEAN_PATTERNS); do \
	  find "$(REPO_ROOT)" -path "$(REPO_ROOT)/.git" -prune -o -name "$$pattern" -print0 | while IFS= read -r -d '' path; do \
	    rel_path="$$path"; \
	    case "$$rel_path" in "$(REPO_ROOT)"/*) rel_path=$${rel_path#$(REPO_ROOT)/};; esac; \
	    if git -C "$(REPO_ROOT)" rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
	      if ! git -C "$(REPO_ROOT)" check-ignore -q -- "$$rel_path"; then \
	        continue; \
	      fi; \
	    fi; \
	    rm -rf "$$path"; \
	    echo "removed $$rel_path"; \
	  done
	done

.DEFAULT_GOAL := setup
