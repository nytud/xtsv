import setuptools

with open('README.md') as fh:
    long_description = fh.read()

setuptools.setup(
    name='xtsv',
    version='1.0.2',
    author='dlazesz',
    author_email='devel@oliphant.nytud.hu',
    description='A generic TSV-style format based intermodular communication framework and REST API',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/dlt-rilmta/xtsv',
    packages=setuptools.find_packages(),
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
