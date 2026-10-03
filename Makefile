.PHONY: all clean install download preprocess audit test

all: install preprocess audit test

install:
	pip install -r requirements.txt

download:
	python -m src.download

preprocess:
	python -m src.preprocess

audit:
	python -m src.audit

test:
	pytest

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .pytest_cache .mypy_cache build dist
