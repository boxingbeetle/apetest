.PHONY: help docs liveapi

help:
	@echo "Available targets:"
	@echo "  liveapi:  Serve live API documentation through HTTP."
	@echo "  docs:     Generate documentation as HTML files."
	@echo "  help:     Show this overview."

docs:
	rm -rf output/docs/api
	PYTHONPATH=. pdoc ape --all-submodules --html --html-dir output/docs/api

liveapi:
	PYTHONPATH=. pdoc --http --http-port 8765
