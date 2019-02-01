.PHONY: help docs apidocs liveapi lint test unittest doctest

help:
	@echo "Available targets:"
	@echo "  liveapi:  Serve live API documentation through HTTP."
	@echo "  docs:     Generate documentation as HTML files."
	@echo "  lint:     Checks sources with PyLint."
	@echo "  test:     Run all tests."
	@echo "  unittest: Run unit tests."
	@echo "  doctest:  Check our documentation using APE."
	@echo "  help:     Show this overview."

docs: docs/README.html apidocs

liveapi:
	PYTHONPATH=$(PWD)/src pdoc --http localhost:8765 apetest

lint:
	PYTHONPATH=src pylint apetest

test: unittest doctest

unittest:
	PYTHONPATH=src pytest tests

doctest: apidocs
	apetest --check launch docs/api/apetest doctest.html

docs/README.html: README.md
	markdown_py $< -f $@

apidocs:
	rm -rf docs/api
	PYTHONPATH=$(PWD)/src pdoc apetest --html --html-dir docs/api
