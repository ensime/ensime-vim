ACTIVATE = .venv/bin/activate

venv: $(ACTIVATE)

$(ACTIVATE): requirements.txt
	test -d .venv || virtualenv -p python2 .venv
	.venv/bin/pip install -Ur requirements.txt
	.venv/bin/pip install -Ur test-requirements.txt
	touch $(ACTIVATE)

lint: venv
	. $(ACTIVATE); flake8 --max-complexity=10 *.py **/*.py

autopep8: venv
	. $(ACTIVATE); autopep8 -aaa --in-place *.py **/*.py

clean:
	rm -rf .venv

run-tests: venv
	@echo "Running ensime-vim lettuce tests"
	. $(ACTIVATE); lettuce ensime_shared/spec/features

