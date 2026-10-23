PYTHON ?= python3

.PHONY: test test-v demo clean

test:
	$(PYTHON) -m unittest discover -s tests

test-v:
	$(PYTHON) -m unittest discover -s tests -v

demo:
	@mkdir -p demo
	@bash demo/demo.sh | tee demo/transcript.txt

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache build dist *.egg-info
