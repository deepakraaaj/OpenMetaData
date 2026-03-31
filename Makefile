PYTHON ?= python3

.PHONY: install install-openmetadata discover onboard api test openmetadata-config tag-bundle

install:
	uv sync --extra dev

install-openmetadata:
	uv sync --extra dev

discover:
	$(PYTHON) -m app.discovery.scan

onboard:
	$(PYTHON) -m app.onboard.run --all-discovered

api:
	uv run uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8088

test:
	uv run pytest

openmetadata-config:
	$(PYTHON) -m app.openmetadata.sync --prepare-only

tag-bundle:
	$(PYTHON) -m app.artifacts.export_tag_bundle --source $(SOURCE) --domain $(DOMAIN)
