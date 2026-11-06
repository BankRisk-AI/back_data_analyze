.PHONY: dev start worker initdb openapi test

PYTHON := .venv/bin/python

dev:        ## API with every module, auto-reload
	$(PYTHON) -m app serve --reload

start:
	$(PYTHON) -m app serve --host 0.0.0.0 --port 8000

worker:     ## separate process: loads staging tables and runs validations
	$(PYTHON) -m app.worker

initdb:     ## create or upgrade the tables
	$(PYTHON) -m app init-db

openapi:    ## regenerate docs/openapi.yaml (a test fails when the file is out of date)
	$(PYTHON) -m app openapi --out docs/openapi.yaml

test:
	$(PYTHON) -m pytest -q
