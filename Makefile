PYTHON2 := python2
PYTHON3 := python3
VENV2 ?= .venv2
VENV3 ?= .venv3

# autopep8 uses pycodestyle but doesn't automatically find files the same way :-/
REFORMAT := ensime_shared/ rplugin/

activate2 := $(VENV2)/bin/activate
activate3 := $(VENV3)/bin/activate
requirements := requirements.txt test-requirements.txt
deps2 := $(VENV2)/deps-updated
deps3 := $(VENV3)/deps-updated

features := test/features

test: unit integration

$(activate2):
	virtualenv -p $(PYTHON2) $(VENV2)

$(activate3):
	virtualenv -p $(PYTHON3) $(VENV3)

$(deps2): $(activate2) $(requirements)
	$(VENV2)/bin/pip install --upgrade --requirement requirements.txt
	$(VENV2)/bin/pip install --upgrade --requirement test-requirements.txt
	touch $(deps2)

$(deps3): $(activate3) $(requirements)
	$(VENV3)/bin/pip install --upgrade --requirement requirements.txt
	$(VENV3)/bin/pip install --upgrade --requirement test-requirements.txt
	touch $(deps3)

unit: $(deps2) $(deps3)
	@echo "Running ensime-vim unit tests"
	. $(activate2) && py.test
	. $(activate3) && py.test

integration: $(deps2) $(deps3)
	@echo "Running ensime-vim lettuce tests"
	. $(activate2) && aloe $(features)
	. $(activate3) && aloe $(features)

coverage: $(deps3)
	. $(activate3) && \
		coverage erase && \
		coverage run --module pytest && \
		coverage run --append $$(which aloe) $(features) && \
		coverage html && \
		coverage report
	@echo
	@echo "Open htmlcov/index.html for an HTML report."

lint: $(deps3)
	. $(activate3) && flake8 --statistics --count --show-source

format: $(deps3)
	. $(activate3) && autopep8 -aaa --in-place -r $(REFORMAT)

clean:
	@echo Cleaning build artifacts...
	-find . -type f -name '*.py[c|o]' -delete
	-find . -type d -name '__pycache__' -delete
	. $(activate3) && coverage erase
	-$(RM) -r htmlcov

distclean: clean
	@echo Cleaning the virtualenv...
	-rm -rf $(VENV2) $(VENV3)

.PHONY: test unit integration coverage lint format clean distclean
