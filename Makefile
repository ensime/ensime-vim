PYTHON := python2
VENV := .venv

# autopep8 uses pycodestyle but doesn't automatically find files the same way :-/
REFORMAT := ensime_shared/ rplugin/

activate := $(VENV)/bin/activate
requirements := requirements.txt test-requirements.txt
deps := $(VENV)/deps-updated

test: $(deps)
	@echo "Running ensime-vim lettuce tests"
	. $(activate) && lettuce ensime_shared/spec/features

$(activate):
	virtualenv -p $(PYTHON) $(VENV)

$(deps): $(activate) $(requirements)
	$(VENV)/bin/pip install --upgrade --requirement requirements.txt
	$(VENV)/bin/pip install --upgrade --requirement test-requirements.txt
	touch $(deps)

lint: $(deps)
	. $(activate) && flake8 --statistics --count --show-source

format: $(deps)
	. $(activate) && autopep8 -aaa --in-place -r $(REFORMAT)

clean:
	@echo Cleaning build artifacts, including the virtualenv...
	-rm -rf $(VENV)
	-find . -type f -name '*.py[c|o]' -delete
	-find . -type d -name '__pycache__' -delete

.PHONY: test lint format clean
