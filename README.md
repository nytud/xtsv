# xtsv – A generic TSV-style format based intermodular communication framework and REST API implemented in Python

- inter-module communication via a TSV-style format
  - processing can be started or stopped at any module
  - module dependency checks before processing
  - easy to add new modules
  - multiple alternative modules for some tasks
- easy to use command-line interface
- convenient REST API with simple web frontend
- Python library API
- Can be turned into a docker image and runnable docker form

If a bug is found please leave feedback with the exact details.

## Citing and License

``xtsv`` is licensed under the LGPL 3.0 license. The submodules have their
own license.

If you use this library, please cite the following paper:

[Indig, Balázs, Bálint Sass, and Iván Mittelholcz. "The xtsv Framework and the Twelve Virtues of Pipelines." Proceedings of The 12th Language Resources and Evaluation Conference. 2020.](https://www.aclweb.org/anthology/2020.lrec-1.871/)

```
@inproceedings{indig-etal-2020-xtsv,
    title = "The xtsv Framework and the Twelve Virtues of Pipelines",
    author = "Indig, Bal{\'a}zs  and
      Sass, B{\'a}lint  and
      Mittelholcz, Iv{\'a}n",
    booktitle = "Proceedings of The 12th Language Resources and Evaluation Conference",
    month = may,
    year = "2020",
    address = "Marseille, France",
    publisher = "European Language Resources Association",
    url = "https://www.aclweb.org/anthology/2020.lrec-1.871",
    pages = "7044--7052",
    abstract = "We present xtsv, an abstract framework for building NLP pipelines. It covers several kinds of functionalities which can be implemented at an abstract level. We survey these features and argue that all are desired in a modern pipeline. The framework has a simple yet powerful internal communication format which is essentially tsv (tab separated values) with header plus some additional features. We put emphasis on the capabilities of the presented framework, for example its ability to allow new modules to be easily integrated or replaced, or the variety of its usage options. When a module is put into xtsv, all functionalities of the system are immediately available for that module, and the module can be be a part of an xtsv pipeline. The design also allows convenient investigation and manual correction of the data flow from one module to another. We demonstrate the power of our framework with a successful application: a concrete NLP pipeline for Hungarian called e-magyar text processing system (emtsv) which integrates Hungarian NLP tools in xtsv. All the advantages of the pipeline come from the inherent properties of the xtsv framework.",
    language = "English",
    ISBN = "979-10-95546-34-4",
}
```

## Requirements

- Python 3.5 <=
- [Optional, if required by any module] PyJNIus and OpenJDK 11 JDK

## API documentation

- `ModuleError`: The exception thrown when something bad happened to the
  modules (e.g. the module could not be found or the ordering of the modules is
  not feasible because of the required and supplied fields)
- `HeaderError`: The exception thrown when the input could not satisfy the
  required fields in its header
- `jnius_config`: Set JAVA VM options and CLASSPATH for the PyJNIus library
- `build_pipeline(inp_data, used_tools, available_tools, presets, conll_comments=False) -> iterator_on_output_lines`:
  Build the current pipeline from the input data (stream, iterable or string),
  the list of the elements of the desired pipeline chosen from the available
  tools and presets returning an output iterator
- `pipeline_rest_api(name, available_tools, presets, conll_comments, singleton_store=None, form_title, doc_link) -> app`:
  Create a Flask application with the REST API and web frontend on the
  available initialised tools and presets with the desired name. Run with a
  wsgi server or Flask's built-in server with with `app.run()` (see [REST API
  section](#REST-API))
- `singleton_store_factory() -> singleton`: Singletons can be used for
  initialisation of modules (eg. when the application is restarted frequently
  and not all modules are used between restarts)
- `process(stream, initialised_app, conll_comments=False) -> iterator_on_output_lines`:
  A low-level API to run a specific member of the pipeline on a specific
  input stream, returning an output iterator
- `parser_skeleton(...) -> argparse.ArgumentParser(...)`: A CLI argument
  parser skeleton can be further customized when needed
- `add_bool_arg(parser, name, help_text, default=False, has_negative_variant=True)`:
  A helper function to easily add BOOL arguments to the ArgumentParser class
- `download(available_models=None, required_models=None)`: Download all (or a
subset of) large model files specified in models.yaml (filename can be
changed in the first parameter)

To be defined by the actual pipeline:

- `tools`: The list of tools (see
  [configuration](#creating-a-module-that-can-be-used-with-xtsv) for details)
- `presets`: The dictionary of shorthands for tasks which are defined as list
  of tools to be run in a pipeline (see
  [configuration](#creating-a-module-that-can-be-used-with-xtsv) for details)

## Data format

The input and output can be one of the following:

- Free form text file
- TSV file with fixed column order and without header (like CoNLL-U)
- TSV file with arbitrary column order where the columns are identified by
  the TSV header (main format of `xtsv`)

The TSV files are formatted as follows (closely resembling the CoNLL-U,
vertical format):

- The first line is the __header__ (when the column order is not fixed,
  therefore the next module identifies columns by their names)
- Columns are separated by TAB characters
- One token per line (one column), the other columns contain the information
  (stem, POS-tag, etc.) of that individual token
- Sentences are separated by emtpy lines
- If allowed by settings, zero or more comment lines (e.g. lines starting
  with hashtag and space) immediately precede the sentences

The fields (represented by TSV columns) are identified by the header in the
first line of the input. Each module can (but does not necessarily have to)
define:

- A set of source fields which is required to present in the input
- A list of target fields which are to be generated to the output in order
  - Newly generated fields are started from the right of the rightmost
    column, the existing columns _should_ not be modified at all

The following types of modules can be defined by their input and output
format requirements:

- __Tokeniser__: No source fields, no header, has target fields, free-format
  text as input, TSV+header output
- __Internal module__: Has source fields, has header, has target fields,
  TSV+header input, TSV+header output
- __Finalizer__: Has source fields, no header, no target fields, TSV+header
  input, free-format text as output
- __Fixed-order TSV importer__: No source fields, no header, has target
  fields, Fixed-order TSV w/o header as input, TSV+header output
- __Fixed-order TSV processor__: No source fields, no header, no target
  fields, Fixed-order TSV w/o header as input, Fixed-order TSV w/o header as
  output

## Creating a module that can be used with `xtsv`

The following requirements apply for a new module:

1. It must provide (at least) the mandatory API (see
[emDummy](https://github.com/dlt-rilmta/emdummy) for a well-documented
example)
1. It must conform to the (to be defined) field-name conventions and the
format conventions
1. It must have an LGPL 3.0 compatible license

The following steps are needed to insert the new module into the pipeline:

1. Add the new module as submodule to the repository
1. Insert the configuration in `config.py`:

    ```python
    # Setup the tuple:
    #   module name (ending with the filename the class defined in),
    #   class,
    #   friendly name,
    #   args (tuple),
    #   kwargs (dict)
    em_dummy = (
        'emdummy.dummytagger',
        'DummyTagger',
        'EXAMPLE (The friendly name of DummyTagger used in REST API form)',
        ('Params', 'goes', 'here'),
        {
            'source_fields': {'Source field names'},
            'target_fields': ['Target field names']
        }
    )
    ```

1. Add the new module to `tools` list in `config.py`, optionally also to
`presets` dictionary

    ```python
    tools = [
        ...,
        (em_dummy, ('dummy-tagger', 'emDummy')),
    ]
    ```

1. Test, commit and push

## Installation

- Can be installed as pip package: `pip3 install xtsv`
- Or by using the git repository as submodule for another git repository

## Usage

Here we present the usage scenarios.

To extend the toolchain with new modules, [just add new modules to
`config.py`](#creating-a-module-that-can-be-used-with-xtsv).

Some examples of the realised applications:

- [`emtsv`](https://github.com/dlt-rilmta/emtsv)
- [`emmorphpy`](https://github.com/ppke-nlpg/emmorphpy/)
- [`HunTag3`](https://github.com/ppke-nlpg/HunTag3)

### Command-line interface

- Multiple modules at once (not necessarily starting with raw text):

  ```bash
  echo "Input text." | python3 ./main.py modules,separated,by,comas
  ```

- Modules _glued together_ one by one with the _standard *nix pipelines_
__where users can interact with the data__ between the modules:

  ```bash
  echo "Input text." | \
      python3 main.py module | \
      python3 main.py separated | \
      python3 main.py by | \
      python3 main.py comas
  ```

- Independently from the other options, `xtsv` can also be used with input or
output streams redirected or with string input (this applies to the runnable
docker form as well):

  ```bash
  python3 ./main.py modules,separated,by,comas -i input.txt -o output.txt
  python3 ./main.py modules,separated,by,comas --text "Input text."
  ```

### __Docker image__

With the appropriate Dockerfile `xtsv` can be used as follows:

- Runnable docker form (CLI usage of docker image):

  ```bash
  cat input.txt | docker run -i xtsv-docker task,separated,by,comas > output.txt
  ```

- As service through Rest API (docker container)

  ```bash
  docker run --rm -p5000:5000 -it xtsv-docker  # REST API listening on http://0.0.0.0:5000
  ```

### REST API

Server:

- Docker image ([see above](#docker-image))
- Any wsgi server (`uwsgi`, `gunicorn`, `waitress`, etc.) can be configured
to run with a prepared wsgi file .
- Debug server (Flask) __only for development (single threaded, one request
  at a time)__:

  When the server outputs a message like `* Running on` then it is ready to
  accept requests on <http://127.0.0.1:5000>. (__We do not recommend using
  this method in production as it is built atop of Flask debug server! Please
  consider using the Docker image for REST API in production!__)

- Any wsgi server (`uwsgi`, `gunicorn`, `waitress`, etc.) can be configured
  to run with a prepared wsgi file .
- Docker image (see above)

Client:

- Web fronted provided by `xtsv`
- From Python (the URL contains the tools to be run separated by `/`):

  ```python
  >>> import requests
  >>> # With input file
  >>> r = requests.post('http://127.0.0.1:5000/tools/separated/by/slashes', files={'file': open('input.file', encoding='UTF-8')})
  >>> print(r.text)
  ...
  >>> # With input text
  >>> r = requests.post('http://127.0.0.1:5000/tools/separated/by/slashes', data={'text': 'Input text.'})
  >>> print(r.text)
  ...
  >>> # CoNLL style comments can be enabled per request (disabled by default):
  >>> r = requests.post('http://127.0.0.1:5000/tools/separated/by/slashes', files={'file':open('input.file', encoding='UTF-8')}, data={'conll_comments': True})
  >>> print(r.text)
  ...
  ```

  The server checks whether the module order is feasible, and returns an
  error message if there are any problems.

### As Python Library

TODO

1. Install xtsv in `xtsv` directory or make sure the emtsv installation is in
the `PYTHONPATH` environment variable.
1. `import xtsv`
1. Example:

    ```Python
    import sys
    from xtsv import build_pipeline, jnius_config, process, pipeline_rest_api, singleton_store_factory

    jnius_config.classpath_show_warning = False  # To suppress warning

    tools = ...
    presets = ...

    # Imports end here. Must do only once per Python session

    # Set input from any stream or iterable and output stream...
    input_data = sys.stdin
    output_iterator = sys.stdout
    # Raw, or processed TSV input list and output file...
    # input_data = iter(['A kutya', 'elment sétálni.'])  # Raw text line by line
    # Processed data: header and the token POS-tag pairs line by line
    # input_data = iter([['form', 'xpostag'], ['A', '[/Det|Art.Def]'], ['kutya', '[/N][Nom]'], ['elment', '[/V][Pst.NDef.3Sg]'], ['sétálni', '[/V][Inf]'], ['.', '.']])
    # output_iterator = open('output.txt', 'w', encoding='UTF-8')  # File
    # input_data = 'A kutya elment sétálni.'  # Or raw string in any acceptable format.

    # Select a predefined task to do or provide your own list of pipeline
    # elements
    used_tools = ['tools', 'in', 'a', 'list']

    conll_comments = True  # Enable the usage of CoNLL comments

    # Run the pipeline on input and write result to the output...
    output_iterator.writelines(build_pipeline(input_data, used_tools, tools, presets, conll_comments))

    # Alternative: Run specific tool for input streams (still in emtsv format).
    # Useful for training a module (see Huntag3 for details):
    output_iterator.writelines(process(sys.stdin, an_inited_tool))

    # Or process individual tokens further... WARNING: The header will be the
    # first item in the iterator!
    for tok in build_pipeline(input_data, used_tools, tools, presets, conll_comments):
        if len(tok) > 1:  # Empty line (='\n') means end of sentence
            form, xpostag, *rest = tok.strip().split('\t')  # Split to the expected columns

    # Alternative2: Flask application (REST API)
    singleton_store = singleton_store_factory()
    app = application = pipeline_rest_api(name='e-magyar-tsv', available_tools=tools, presets=presets,
                                conll_comments=conll_comments, singleton_store=singleton_store,
                                form_title='e-magyar text processing system',
                                doc_link='https://github.com/dlt-rilmta/emtsv')
    # And run the Flask debug server separately
    app.run()
    ```
