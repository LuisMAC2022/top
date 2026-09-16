# Optional Bash-friendly shortcuts. All logic lives in Python; these are aliases.
PY      ?= python3
BIB     := PYTHONPATH=src $(PY) -m bibgraph
PORT    ?= 8000

.PHONY: help doctor validate fetch extract resolve analyze site check-site serve test publish clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

doctor:       ## report environment capabilities
	$(BIB) doctor
validate:     ## validate the manifests
	$(BIB) validate
fetch:        ## acquire requested assets (strict)
	$(BIB) fetch --strict
extract:      ## extract first-pass structure (strict)
	$(BIB) extract --strict
resolve:      ## resolve references (strict)
	$(BIB) resolve --strict
analyze:      ## build graphs, clusters, rankings and survey
	$(BIB) analyze
site:         ## build the local static site
	$(BIB) build-site --local
check-site:   ## link-check and escape-check the built site
	$(BIB) check-site build/site
publish:      ## build the allowlisted public site
	$(BIB) build-site --public && $(BIB) check-site publish --public
serve:        ## serve the local build
	$(PY) -m http.server --directory build/site $(PORT)
test:         ## run the standard library test suite
	$(PY) -m unittest
clean:
	rm -rf build publish
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
