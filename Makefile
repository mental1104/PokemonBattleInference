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

# Ensure repo sources are importable alongside the shared common/python package.
export PYTHONPATH := $(REPO_ROOT):$(REPO_ROOT)/../common/python

.PHONY: default install test coverage env-print env-clean

default: install

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
