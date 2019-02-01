.PHONY: help docs liveapi lint test unittest doctest

help:
	@echo "Available targets:"
	@echo "  liveapi:  Serve live API documentation through HTTP."
	@echo "  docs:     Generate documentation as HTML files."
	@echo "  lint:     Checks sources with PyLint."
	@echo "  test:     Run all tests."
	@echo "  unittest: Run unit tests."
	@echo "  doctest:  Check our documentation using APE."
	@echo "  help:     Show this overview."

docs:
	rm -rf docs/api
	PYTHONPATH=$(PWD)/src pdoc apetest --html --html-dir docs/api

liveapi:
	PYTHONPATH=$(PWD)/src pdoc --http localhost:8765 apetest

lint:
	PYTHONPATH=src pylint apetest

test: unittest doctest

unittest:
	PYTHONPATH=src pytest tests

doctest:
	@echo "doctest is not implemented yet"
