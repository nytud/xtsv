# Bash is needed for time
SHELL := /bin/bash -o pipefail
DIR := ${CURDIR}
red := $(shell tput setaf 1)
green := $(shell tput setaf 2)
sgr0 := $(shell tput sgr0)
MODULE := "xtsv"

# Parse version string and create new version. Originally from: https://github.com/mittelholcz/contextfun
# Variable is empty in Travis-CI if not git tag present
TRAVIS_TAG ?= ""
OLDVER := $$(grep -P -o "(?<=__version__ = ')[^']+" $(MODULE)/version.py)

MAJOR := $$(echo $(OLDVER) | sed -r s"/([0-9]+)\.([0-9]+)\.([0-9]+)/\1/")
MINOR := $$(echo $(OLDVER) | sed -r s"/([0-9]+)\.([0-9]+)\.([0-9]+)/\2/")
PATCH := $$(echo $(OLDVER) | sed -r s"/([0-9]+)\.([0-9]+)\.([0-9]+)/\3/")

NEWMAJORVER="$$(( $(MAJOR)+1 )).0.0"
NEWMINORVER="$(MAJOR).$$(( $(MINOR)+1 )).0"
NEWPATCHVER="$(MAJOR).$(MINOR).$$(( $(PATCH)+1 ))"

all:
	@echo "See Makefile for possible targets!"
.PHONY: all

build:
	python3 setup.py sdist bdist_wheel

upload:
	python3 -m twine upload dist/*


packaging_env:
	python3 -m venv venv
	. venv/bin/activate ; \
		python3 -m pip install --upgrade pip setuptools wheel twine; \
		python3 -m pip install -r requirements.txt ;
.PHONY: packaging_env

check-version:
	@echo "Comparing GIT TAG (\"$(TRAVIS_TAG)\") with pacakge version (\"v$(OLDVER)\")..."
	 @[[ "$(TRAVIS_TAG)" == "v$(OLDVER)" || "$(TRAVIS_TAG)" == "" ]] && \
	  echo "$(green)OK!$(sgr0)" || \
	  (echo "$(red)Versions do not match!$(sgr0)" && exit 1)

uninstall:
	@echo "Uninstalling..."
	python3 -m pip uninstall -y ${MODULE}

clean:
	rm -rf dist/ build/ ${MODULE}.egg-info/

clean-build: clean build

# Do actual release with new version. Originally from: https://github.com/mittelholcz/contextfun
release-major:
	@make -s __release NEWVER=$(NEWMAJORVER)
.PHONY: release-major


release-minor:
	@make -s __release NEWVER=$(NEWMINORVER)
.PHONY: release-minor


release-patch:
	@make -s __release NEWVER=$(NEWPATCHVER)
.PHONY: release-patch


__release:
	@if [[ -z "$(NEWVER)" ]] ; then \
		echo 'Do not call this target!' ; \
		echo 'Use "release-major", "release-minor" or "release-patch"!' ; \
		exit 1 ; \
		fi
	@if [[ $$(git status --porcelain) ]] ; then \
		echo 'Working dir is dirty!' ; \
		exit 1 ; \
		fi
	@echo "NEW VERSION: $(NEWVER)"
	@sed -i -r "s/__version__ = '$(OLDVER)'/__version__ = '$(NEWVER)'/" $(MODULE)/version.py
	@make  uninstall clean-build
	@make check-version
	@git add $(MODULE)/version.py
	@git commit -m "Release $(NEWVER)"
	@git tag -a "v$(NEWVER)" -m "Release $(NEWVER)"
	@git push --tags
.PHONY: __release
