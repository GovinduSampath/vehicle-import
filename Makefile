.PHONY: install lint test run up down check

install:
	python -m pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .
	mypy app

test:
	pytest -v

check: lint test   ## exactly what CI runs -- run this before you push

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

up:
	docker compose up --build

down:
	docker compose down -v
