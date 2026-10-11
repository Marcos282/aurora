PYTHON := .venv/bin/python
.PHONY: install migrate user web test check
install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt
migrate:
	$(PYTHON) manage.py migrate
user:
	$(PYTHON) manage.py createsuperuser
web:
	$(PYTHON) manage.py runserver 127.0.0.1:8000
test:
	$(PYTHON) manage.py test core --settings=config.test_settings
check:
	$(PYTHON) manage.py check
