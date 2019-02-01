.PHONY: help docs liveapi lint

help:
	@echo "Available targets:"
	@echo "  liveapi:  Serve live API documentation through HTTP."
	@echo "  docs:     Generate documentation as HTML files."
	@echo "  lint:     Checks sources with PyLint."
	@echo "  help:     Show this overview."

docs:
	rm -rf docs/api
	PYTHONPATH=$(PWD)/src pdoc apetest --html --html-dir docs/api

liveapi:
	PYTHONPATH=$(PWD)/src pdoc --http localhost:8765 apetest

lint:
	PYTHONPATH=src pylint apetest
