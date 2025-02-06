# Installs production dependencies
install:
	pip install .;

# Installs development dependencies
install-dev:
	pip install ".[dev]";

lint:
	ruff check .
	ruff format .

lint-fix:
	ruff check . --fix
	ruff format .

qa:
	make install-dev
	make lint