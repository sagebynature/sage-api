#!/usr/bin/make -f

.PHONY: check-env sync install update lint format type-check test clean

PACKAGE_NAME = sage_api
SRC_DIR = $(PACKAGE_NAME)
UV_AUTH_ENV = UV_INDEX_URL=https://user:${AZURE_ARTIFACTS_ENV_ACCESS_TOKEN}@pkgs.dev.azure.com/ApolloAzureDevOps/_packaging/ApolloAzureDevOps/pypi/simple/

check-env:
	@which python >/dev/null 2>&1 || (echo "Python 3 is required. Please install it first." && exit 1)
	@which uv >/dev/null 2>&1 || (echo "uv is required. Please install it first." && exit 1)

sync: check-env
	${UV_AUTH_ENV} uv sync --group dev

install: check-env
	${UV_AUTH_ENV} uv sync --frozen --group dev

update: check-env
	${UV_AUTH_ENV} uv sync --group dev

lint:
	uv run ruff check $(SRC_DIR) tests --fix

format:
	uv run ruff format $(SRC_DIR) tests

type-check:
	uv run mypy $(SRC_DIR)

test: install
	uv run pytest tests/ -v

test-only:
	uv run pytest tests/ -v

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
