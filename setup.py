#!/usr/bin/env python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import sys
import setuptools
import importlib.util


def import_pyhton_file(module_name, file_path):
    # Import module from file: https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


with open('README.md') as fh:
    long_description = fh.read()

setuptools.setup(
    name='xtsv',
    # Get version without actually importing the module (else we need the dependencies installed)
    version=getattr(import_pyhton_file('version', 'xtsv/version.py'), '__version__'),
    author='dlazesz',
    author_email='devel@oliphant.nytud.hu',
    description='A generic TSV-style format based intermodular communication framework and REST API',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/dlt-rilmta/xtsv',
    packages=setuptools.find_packages(exclude=['tests']),
    install_requires=[
        'werkzeug',
        'Flask',
        'flask-restful',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
