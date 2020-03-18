VENV_DIR = venv3
setup:
	pip3 install --user virtualenv
	virtualenv -p python3 $(VENV_DIR)
	$(VENV_DIR)/bin/pip install -r requirements.txt
	$(VENV_DIR)/bin/pip install -r requirements-for-examples.txt
	$(VENV_DIR)/bin/pip install .
