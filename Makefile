.PHONY: default install test coverage

# Ensure every recipe runs with the repository on PYTHONPATH so imports resolve.
export PYTHONPATH := $(shell pwd)

# Default initialization step: install Python dependencies for this repo.
default: install

install:
	python3 -m pip install -r requirements.txt --break-system-packages

# Execute the Python test suite with the configured PYTHONPATH.
test:
	pytest

# Run pytest with coverage reporting for the main package.
coverage:
	pytest --cov=pokemon_battle_inference --cov-report=term-missing
