.PHONY: install install-dev format lint test run clean

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pre-commit install

format:
	black .

lint:
	ruff check .
	mypy core cli api

test:
	pytest tests/

run:
	python main.py

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -r {} +
