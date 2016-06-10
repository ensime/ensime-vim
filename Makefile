ACTIVATE = .venv/bin/activate
REQS = pip install -Ur requirements.txt
TESTREQS = pip install -Ur test-requirements.txt
INSTALL = pip install -e '.'

venv: requirements.txt
	test -d .venv || virtualenv -p python2 .venv
	. $(ACTIVATE); $(REQS)
	. $(ACTIVATE); $(TESTREQS)
	#. $(ACTIVATE); $(INSTALL)
	touch $(ACTIVATE)

lint: venv
	. $(ACTIVATE); flake8 --max-complexity=10 *.py **/*.py

autopep8: venv
	. $(ACTIVATE); autopep8 -aaa --in-place *.py **/*.py

clean:
	rm -rf .venv

run-tests:

	@echo "Running ensime-vim lettuce tests"
	. $(ACTIVATE); lettuce ensime_shared/spec/features

