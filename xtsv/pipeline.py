#!/usr/bin/env python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import importlib
import codecs
from itertools import chain
from collections import defaultdict, OrderedDict, abc
from os.path import abspath as os_path_abspath, dirname as os_path_dirname, join as os_path_join

# import atexit

from json import dumps as json_dumps

from flask import Flask, request, Response, stream_with_context, make_response, render_template
from flask_restful import Api, Resource
from flask_restful.inputs import boolean
from werkzeug.exceptions import abort

from .tsvhandler import process, HeaderError
from .jnius_wrapper import jnius_config, import_pyjnius


class ModuleError(ValueError):
    pass


def build_pipeline(input_data, used_tools, available_tools, presets, conll_comments=False, singleton_store=None,
                   output_header=True):
    friendly_name_for_modules = {name: tool_params[1] for tool_params, names in available_tools for name in names}
    current_initialised_tools = lazy_init_tools(used_tools, available_tools, presets, singleton_store)

    used_tools = resolve_presets(presets, used_tools)

    if isinstance(input_data, str):
        inp_stream = iter(input_data.splitlines(keepends=True))
    elif isinstance(input_data, abc.Iterable):
        inp_stream = input_data
    else:
        raise ValueError('The input should be string or iterable!')

    # Peek header...
    header = next(inp_stream)
    # ...and restore iterator...
    inp_stream = chain([header], inp_stream)

    pipeline_begin = inp_stream
    pipeline_begin_friendly = 'Input Text'
    pipeline_begin_prod = set(header.strip().split('\t'))

    pipeline_end = pipeline_begin
    pipeline_end_friendly = pipeline_begin_friendly
    pipeline_prod = pipeline_begin_prod

    last_used_tool_nr = len(used_tools) - 1
    for i, program in enumerate(used_tools):
        program_friendly = friendly_name_for_modules[program]
        pr = current_initialised_tools.get(program)
        if pr is not None:
            if i == 0 and len(pr.source_fields) == 0:  # If first module expects raw text, there are no fields!
                pipeline_prod = set()
            if not pr.source_fields.issubset(pipeline_prod):
                raise ModuleError('ERROR: \'{0}\' module requires {1} fields but the previous module \'{2}\''
                                  ' has only {3} fields!'.format(program_friendly, pr.source_fields,
                                                                 pipeline_end_friendly, pipeline_prod))
            pipeline_end = process(pipeline_end, pr, conll_comments, i != last_used_tool_nr or output_header)
            pipeline_end_friendly = program_friendly
            pipeline_prod |= set(pr.target_fields)
        else:
            raise ModuleError('ERROR: \'{0}\' module not found. Available modules: {1}'.
                              format(program, ','.join(m for _, names in available_tools for m in names)))

    return pipeline_end


def pipeline_rest_api(name, available_tools, presets, conll_comments, singleton_store=None, form_title='xtsv pipeline',
                      form_type='checkbox', doc_link='', output_header=True):
    if available_tools is None:
        raise ValueError('No internal_app is given!')

    kwargs = {'internal_apps': available_tools, 'presets': presets, 'conll_comments': conll_comments,
              'singleton_store': singleton_store, 'form_title': form_title, 'form_type': form_type,
              'doc_link': doc_link, 'output_header': output_header}

    app = Flask(name,  template_folder=os_path_join(os_path_dirname(os_path_abspath(__file__)), 'templates'))
    api = Api(app)
    api.add_resource(RESTapp, '/', '/<path:path>', resource_class_kwargs=kwargs)  # Catch-all with self

    return app


def singleton_store_factory():
    """ Store already initialised tools for reuse without reinitialization (singleton store)
         must explicitly pass it to init_everything() or pipeline_rest_api()
    """
    return {}, defaultdict(list)


# From here, there are only private methods
def resolve_presets(presets, used_tools):  # Resolve presets to module names to enable shorter URLs/task definitions...
    if len(used_tools) == 1 and used_tools[0] in presets:
        used_tools = presets[used_tools[0]][1]
    return used_tools


def lazy_init_tools(used_tools, available_tools, presets, singleton_store=None):
    """ Resolve presets and initialise what is needed if it were not initialised before or not available """
    # Sanity check params!
    for app, _ in available_tools:
        if not isinstance(app, tuple):
            raise TypeError('When using lazy initialisation internal_apps should be'
                            ' the dict of the uninitialised tools!')
        module, prog, friendly_name, prog_args, prog_kwargs = app
        try:
            importlib.import_module(module), prog   # Silently import everything for the JAVA CLASSPATH...
        except ModuleNotFoundError:
            pass

    # Resolve presets to module names to init only the needed modules...
    used_tools = set(resolve_presets(presets, used_tools))

    # If there is preinitialised tool pool check the type, else create a new!
    if singleton_store is None:
        singleton_store = singleton_store_factory()
    elif not isinstance(singleton_store, tuple) or len(singleton_store) != 2 or \
            not isinstance(singleton_store[0], dict) or not isinstance(singleton_store[1], defaultdict) or \
            not issubclass(singleton_store[1].default_factory, list):
        raise ValueError('singleton_store  is expected to be the type of tuple(dict(), defaultdict(list))'
                         ' instead of {0} !'.format(type(singleton_store)))

    selected_tools = [(k, v) for k, v in available_tools if len(used_tools.intersection(set(v)))]
    # Init everything properly
    # Here we must challenge if any classpath or JAVA VM options are set to be able to throw the exception if needed
    if jnius_config.classpath is not None or len(jnius_config.options) > 0:
        import_pyjnius()

    current_initialised_tools = singleton_store[0]
    currrent_alias_store = singleton_store[1]
    for prog_params, prog_names in selected_tools:  # prog_names are individual, prog_params can be the same!
        module, prog, friendly_name, prog_args, prog_kwargs = prog_params
        # Dealias aliases to find the initialised versions
        for inited_prog_names, curr_prog_params in currrent_alias_store[prog]:
            if curr_prog_params == prog_params:  # If prog_params match prog_name is an alias for inited_prog_names
                for prog_name in prog_names:
                    current_initialised_tools[prog_name] = current_initialised_tools[inited_prog_names[0]]
                break
        else:  # No initialised alias found... Initialize and store as initialised alias!
            prog_imp = getattr(importlib.import_module(module), prog)
            inited_prog = prog_imp(*prog_args, **prog_kwargs)  # Inint programs...
            if (not hasattr(inited_prog, 'source_fields') or not isinstance(inited_prog.source_fields, set)) and \
               (not hasattr(inited_prog, 'target_fields') or not isinstance(inited_prog.target_fields, list)):
                raise ModuleError('Module named {0} has no source_fields or target_fields attributes'
                                  ' or some of them has wrong type !'.format(','.join(prog_names)))
            for prog_name in prog_names:
                current_initialised_tools[prog_name] = inited_prog
            currrent_alias_store[prog].append((prog_names, prog_params))  # For lookup we need prog_names as well!
    return current_initialised_tools


class RESTapp(Resource):
    def __init__(self, internal_apps=None, presets=(), conll_comments=False, singleton_store=None,
                 form_title='xtsv pipeline', form_type='checkbox', doc_link='', output_header=True):
        """
        Init REST API class
        :param internal_apps: pre-inicialised applications
        :param presets: pre-defined chains eg. from tokenisation to dependency parsing'
        :param conll_comments: CoNLL-U-style comments (lines beginning with '# ') before sentences
        :param singleton_store: preinitialised tool pool, which mustbe defined externally,
                or new is created on every call!
        :param form_title: the title of the HTML form shown when URL opened in a browser
        :param form_type: Some tools can be used as alternatives (e.g. different modes of emMorph),
                some allow sequences to be defined
        :param doc_link: A link to documentation on usage for helping newbies
        :param output_header: Make header for output or not
        """
        self._internal_apps = internal_apps
        self._presets = presets
        self._conll_comments = conll_comments
        self._output_header = output_header

        self._singleton_store = singleton_store
        self._title = form_title
        if form_type not in {'checkbox', 'radio'}:
            raise ValueError('form_type should be either \'checkbox\' or \'radio\' instead of {0}'.format(form_type))
        if form_type == 'radio' and len(presets) != 0:
            raise ValueError('Presets and radio buttons are mutually exclusive options!')
        self._tools_type = form_type

        self._doc_link = doc_link

        # Dict of default tool names -> friendly names
        self._available_tools = {names[0]: tool_params[2] for tool_params, names in internal_apps}
        # atexit.register(self._internal_apps.__del__)  # For clean exit...

    def get(self, path=''):
        # fun/token
        fun, token = None, ''
        if '/' in path:
            fun, token = path.split('/', maxsplit=1)
        curr_tools = lazy_init_tools([fun], self._internal_apps, self._presets, self._singleton_store)
        prog = getattr(curr_tools.get(fun), 'process_token', None)

        if len(path) == 0 or len(token) == 0 or prog is None:
            base_url = request.url_root.rstrip('/')  # FORM URL

            out_html = render_template('layout.html', title=self._title, base_url=base_url, doc_link=self._doc_link,
                                       presets=self._presets, available_tools=self._available_tools,
                                       tools_type=self._tools_type)
            return Response(out_html)

        json_text = json_dumps({token: prog(token)}, indent=2, sort_keys=True, ensure_ascii=False)

        return self._make_json_response(json_text)

    def post(self, path):
        # Handle both json and form data transparently
        req_data = request.get_json() if request.is_json else request.form
        tohtml = req_data.get('toHTML', False)
        if tohtml:
            final_convert = self._to_html
        else:
            final_convert = self._identity

        conll_comments = self._get_checked_bool('conll_comments', self._conll_comments, req_data)
        output_header = self._get_checked_bool('output_header', self._output_header, req_data)
        input_text = req_data.get('text')
        if 'file' in request.files and input_text is None:
            inp_data = codecs.getreader('UTF-8')(request.files['file'])
        elif 'file' not in request.files and input_text is not None:
            inp_data = input_text
        else:
            abort(400, 'ERROR: input text or file (mutually exclusive) not found in request!')
            inp_data = None  # Silence dummy IDE

        required_tools = path.split('/')

        try:
            last_prog = build_pipeline(inp_data, required_tools, self._internal_apps, self._presets, conll_comments,
                                       self._singleton_store, output_header)
        except (HeaderError, ModuleError) as e:
            abort(400, e)
            last_prog = ()  # Silence, dummy IDE

        response = Response(stream_with_context(final_convert((line.encode('UTF-8') for line in last_prog))),
                            direct_passthrough=True, content_type='text/plain; charset=utf-8')
        if not tohtml:
            response.headers.set('Content-Disposition', 'attachment', filename='output.txt')
        return response

    @staticmethod
    def _get_checked_bool(input_param_name, default, req_data):
        try:
            return boolean(req_data.get(input_param_name, default))
        except ValueError:
            abort(400, 'ERROR: argument {0} should be True/False!'.format(input_param_name))

    @staticmethod
    def _make_json_response(json_text, status=200):
        """
         https://stackoverflow.com/questions/16908943/display-json-returned-from-flask-in-a-neat-way/23320628#23320628
        """
        response = make_response(json_text)
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['mimetype'] = 'application/json'
        response.status_code = status
        return response

    @staticmethod
    def _identity(x):
        return x

    @staticmethod
    def _to_html(input_iterator):
        for line in input_iterator:
            yield line.rstrip(b'\n').replace(b'&', b'&amp;').replace(b'<', b'&lt;').replace(b'>', b'&gt;').\
                replace(b'"', b'&quot;').replace(b'\'', b'&#x27;')
            yield b'<br/>\n'
