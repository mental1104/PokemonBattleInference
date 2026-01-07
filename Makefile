SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

# === 自动加载 .env 到 Make 环境 ==========================
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ENV_SRC   ?= $(REPO_ROOT)/.env
ENV_HAVE  := $(wildcard $(ENV_SRC))

ifeq ($(strip $(ENV_HAVE)),)
  ENV_MK := /dev/null
else
  ENV_MK := $(abspath $(ENV_SRC)).mk

  $(ENV_MK): $(ENV_SRC)
	@set -e
	awk '\
	  /^[[:space:]]*#/ || /^[[:space:]]*$$/ { next } \
	  { line=$$0; sub(/^[[:space:]]*export[[:space:]]+/, "", line); \
	    i=index(line,"="); if(i==0) next; \
	    key=substr(line,1,i-1); val=substr(line,i+1); \
	    sub(/^[[:space:]]+|[[:space:]]+$$/,"",key); \
	    sub(/^[[:space:]]+/,"",val); sub(/[[:space:]]+#.*/, "", val); \
	    if(val ~ /^".*"$$/){sub(/^"/,"",val); sub(/"$$/,"",val)} \
	    else if(val ~ /^'\''.*'\''$$/){sub(/^'\''/,"",val); sub(/'\''$$/,"",val)} \
	    print "export " key " = " val; }' \
	  "$(ENV_SRC)" > "$(ENV_MK)"
	echo "[ok] .env -> $(ENV_MK)"
  include $(ENV_MK)
endif
# =========================================================

# --- Common repo resolution (prefer ~/code/common, fallback to ../common) ---
PREFERRED_COMMON_ROOT := $(HOME)/code/common
FALLBACK_COMMON_ROOT := $(abspath $(REPO_ROOT)/../common)
COMMON_ROOT ?= $(PREFERRED_COMMON_ROOT)
# Normalize to absolute path for downstream usage
COMMON_ROOT := $(abspath $(COMMON_ROOT))
ifeq ($(wildcard $(COMMON_ROOT)),)
  COMMON_ROOT := $(FALLBACK_COMMON_ROOT)
endif

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

.PHONY: default install test coverage env-print env-clean clean setup



install:
	python3 -m pip install -r requirements.txt --break-system-packages

test:
	pytest

coverage:
	pytest --cov=pokemon_battle_inference --cov-report=term-missing

env-print:
	@env | grep -E '^(PG|PULSAR|REDIS|CLICKHOUSE)' | sort || true

env-clean:
	@[ "$(ENV_MK)" != "/dev/null" ] && rm -f "$(ENV_MK)" || true

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

clean: env-clean
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
	  done; \
	done


.DEFAULT_GOAL := setup
