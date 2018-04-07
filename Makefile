PYTHON := python3
VENV ?= .venv

# autopep8 uses pycodestyle but doesn't automatically find files the same way :-/
REFORMAT := ensime_shared/ rplugin/

activate := $(VENV)/bin/activate
requirements := requirements.txt test-requirements.txt
deps := $(VENV)/deps-updated

features := test/features

test: unit integration

$(activate):
	virtualenv -p $(PYTHON) $(VENV)

$(deps): $(activate) $(requirements)
	$(VENV)/bin/pip install --upgrade --requirement requirements.txt
	$(VENV)/bin/pip install --upgrade --requirement test-requirements.txt
	touch $(deps)

unit: $(deps)
	@echo "Running ensime-vim unit tests"
	. $(activate) && py.test

integration: $(deps)
	@echo "Running ensime-vim lettuce tests"
	. $(activate) && aloe $(features)

coverage: $(deps)
	. $(activate) && \
		coverage erase && \
		coverage run --module pytest && \
		coverage run --append $$(which aloe) $(features) && \
		coverage html && \
		coverage report
	@echo
	@echo "Open htmlcov/index.html for an HTML report."

lint: $(deps)
	. $(activate) && flake8 --statistics --count --show-source

format: $(deps)
	. $(activate) && autopep8 -aaa --in-place -r $(REFORMAT)

clean:
	@echo Cleaning build artifacts...
	-find . -type f -name '*.py[c|o]' -delete
	-find . -type d -name '__pycache__' -delete
	. $(activate) && coverage erase
	-$(RM) -r htmlcov

distclean: clean
	@echo Cleaning the virtualenv...
	-rm -rf $(VENV)

.PHONY: test unit integration coverage lint format clean distclean
