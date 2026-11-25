.PHONY: dev start worker initdb openapi test

PYTHON := .venv/bin/python
TARGET ?= test

dev:        ## API with every module, auto-reload
	$(PYTHON) -m app serve --reload

start:
	$(PYTHON) -m app serve --host 0.0.0.0 --port 8000

worker:     ## separate process: loads staging tables and runs validations
	$(PYTHON) -m app.worker

initdb:     ## create or upgrade the tables
	$(PYTHON) -m scripts.data.init_db --target $(TARGET)

openapi:    ## regenerate docs/openapi.yaml (a test fails when the file is out of date)
	$(PYTHON) -m scripts.data.export_openapi --out docs/openapi.yaml

test:
	$(PYTHON) -m pytest -q
