#!/usr/bin/make -f

IMAGE   ?= sagebynature/sage-api
VERSION ?=

.PHONY: check-env sync install update lint format type-check test clean start docker-build docker-up docker-down docker-logs docker-push release

PACKAGE_NAME = sage_api
SRC_DIR = $(PACKAGE_NAME)

check-env:
	@which python >/dev/null 2>&1 || (echo "Python 3 is required. Please install it first." && exit 1)
	@which uv >/dev/null 2>&1 || (echo "uv is required. Please install it first." && exit 1)

sync: check-env
	uv sync --frozen --group dev

install: sync
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg

update: check-env
	uv sync --group dev

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

start:
	uv run uvicorn sage_api.main:app --host 0.0.0.0 --port 8000 --reload

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f api

docker-push:
	@test -n "$(VERSION)" || (echo "VERSION is required. Usage: make docker-push VERSION=v0.2.0" && exit 1)
	docker build -t $(IMAGE):$(VERSION) -t $(IMAGE):latest .
	docker push $(IMAGE):$(VERSION)
	docker push $(IMAGE):latest

release:
	@test -n "$(VERSION)" || (echo "VERSION is required. Usage: make release VERSION=v0.2.0" && exit 1)
	@echo "NOTE: Prefer merging the Release Please PR to trigger an automated release."
	git tag $(VERSION)
	git push origin $(VERSION)

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
