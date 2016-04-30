ACTIVATE = .venv/bin/activate
REQS = pip install -Ur requirements.txt
TESTREQS = pip install -Ur test-requirements.txt
INSTALL = pip install -e '.'

venv: requirements.txt
	test -d .venv || virtualenv -p python3 .venv
	. $(ACTIVATE); $(REQS)
	. $(ACTIVATE); $(TESTREQS)
	#. $(ACTIVATE); $(INSTALL)
	touch $(ACTIVATE)

pytest:
	. $(ACTIVATE); py.test -rf -l -s -x  --cov-report term-missing --cov **/*.py

lint: venv
	. $(ACTIVATE); flake8 --max-complexity=10 *.py **/*.py

autopep8: venv
	. $(ACTIVATE); autopep8 -aaa --in-place *.py **/*.py

clean:
	rm -rf .venv

test:
	coverage run --include=ensime_launcher/__init__.py,rplugin/python/ensime.py lettuce && coverage html
