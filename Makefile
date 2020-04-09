all:
	@echo 'test'
.PHONY: all

build:
	python3 setup.py sdist bdist_wheel

upload:
	python3 -m twine upload dist/*

clean:
	rm -rf dist/ build/ xtsv.egg-info/

packaging_env:
	python3 -m venv venv
	. venv/bin/activate ; \
		python3 -m pip install --upgrade pip setuptools wheel twine; \
		python3 -m pip install -r requirements.txt ;
.PHONY: packaging_env
