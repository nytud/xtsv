all:
	@echo 'test'
.PHONY: all


packaging_env:
	python3 -m venv venv
	. venv/bin/activate ; \
		python3 -m pip install --upgrade pip setuptools wheel ; \
		python3 -m pip install -r requirements.txt ;
.PHONY: packaging_env

