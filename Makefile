.PHONY: install test lint build lock update-deps install-hooks check-commits

default: test

install:
	uv sync --group dev

install-hooks:
	git config core.hooksPath .githooks

check-commits:
	python3 scripts/check_conventional_commits.py --range "$$(git merge-base HEAD origin/master)..HEAD"

test:
	uv run pytest -v

lint:
	uv run pylint $$(find mqtt_alerts -name "*.py" -type f)

build:
	uv build

lock:
	uv lock

update-deps:
	uv lock --upgrade
	uv sync --group dev
