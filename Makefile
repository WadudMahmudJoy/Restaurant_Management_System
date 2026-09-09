# Lumière RMS — everyday commands
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: help setup migrate seed run test smoke lint clean reset

help:            ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10m\033[0m %s\n", $$1, $$2}'

setup:           ## create .venv and install dependencies
	python3 -m venv .venv
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements.txt

migrate:         ## apply migrations
	$(PY) manage.py migrate

seed:            ## fill the database with a full demo install
	$(PY) manage.py seed_demo

run:             ## run the dev server on :8000
	$(PY) manage.py runserver 0.0.0.0:8000

test:            ## run the Django test suite
	$(PY) manage.py test -v 1

smoke:           ## end-to-end smoke test against the seeded dev database
	$(PY) scripts/smoke.py

lint:            ## byte-compile check (no external linter required)
	$(PY) -m compileall -q apps config manage.py

clean:           ## remove caches and build artefacts
	find . -name '__pycache__' -type d -not -path './.venv/*' -exec rm -rf {} +
	rm -rf staticfiles .pytest_cache

reset:           ## wipe the database and re-seed from scratch
	rm -f db.sqlite3*
	$(MAKE) migrate seed
