#!/usr/bin/python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import codecs
from itertools import chain
from collections import defaultdict

# import atexit

from json import dumps as json_dumps

from flask import Flask, request, Response, stream_with_context, make_response
from flask_restful import Api, Resource
from werkzeug.exceptions import abort

from .tsvhandler import process, HeaderError
from .jnius_wrapper import jnius_config, import_pyjnius


class ModuleError(ValueError):
    pass


def init_everything(available_tools, singleton_store=None):  # Init everything properly
    # Here we must challenge if any classpath or JAVA VM options are set to be able to throw the exception if needed
    if jnius_config.classpath is not None or len(jnius_config.options) > 0:
        import_pyjnius()
    if singleton_store is None:
        current_initialised_tools = {}
        currrent_alias_store = defaultdict(list)
    elif not isinstance(singleton_store, tuple) or len(singleton_store) != 2 or \
            not isinstance(singleton_store[0], dict) or not isinstance(singleton_store[1], defaultdict) or \
            not isinstance(singleton_store[1].default_factory, list):
        current_initialised_tools = singleton_store[0]   # The singleton store
        currrent_alias_store = singleton_store[1]
    else:
        raise TypeError('singleton_store is expected to be (dict, defaultdict(list) instead of {0}'.
                        format(type(singleton_store)))

    for prog_name, prog_params in available_tools.items():  # prog_names are individual, prog_params can be the same!
        prog, friendly_name, prog_args, prog_kwargs = prog_params
        # Dealias aliases to find the initialized versions
        for inited_prog_name, curr_prog_params in currrent_alias_store[prog]:
            if curr_prog_params == prog_params:  # If prog_params match prog_name is an alias for inited_prog_name
                current_initialised_tools[prog_name] = current_initialised_tools[inited_prog_name]
                break
        else:  # No initialized alias found... Initialize and store as initialized alias!
            current_initialised_tools[prog_name] = prog(*prog_args, **prog_kwargs)  # Inint programs...
            currrent_alias_store[prog].append((prog_name, prog_params))  # For lookup we need prog_name as well!
    return current_initialised_tools


def build_pipeline(inp_stream, used_tools, available_tools, presets, conll_comments=False):
    used_tools = resolve_presets(presets, used_tools)

    # Peek header...
    header = next(inp_stream)
    # ...and restore iterator...
    inp_stream = chain([header], inp_stream)

    pipeline_begin = inp_stream
    pipeline_begin_friendly = 'HTTP POST/STDIN file'
    pipeline_begin_prod = set(header.strip().split('\t'))

    pipeline_end = pipeline_begin
    pipeline_end_friendly = pipeline_begin_friendly
    pipeline_prod = pipeline_begin_prod

    for program in used_tools:
        pr = available_tools.get(program)
        if pr is not None:
            if not pr.source_fields.issubset(pipeline_prod):
                raise ModuleError('ERROR: {0} module requires {1} columns but the previous module {2}'
                                  ' has only {3} columns'.format(program, pr.source_fields, pipeline_prod,
                                                                 pipeline_end_friendly))
            pipeline_end = process(pipeline_end, pr, conll_comments)
            pipeline_prod |= set(pr.target_fields)
        else:
            raise ModuleError('ERROR: \'{0}\' module not found. Available modules: {1}'.
                              format(program, sorted(available_tools.keys())))

    return pipeline_end


def pipeline_rest_api(name, available_tools, presets, conll_comments, singleton_store=None):
    if available_tools is None:
        raise ValueError('No internal_app is given!')

    kwargs = {'internal_apps': available_tools, 'presets': presets, 'conll_comments': conll_comments,
              'singleton_store': singleton_store}

    app = Flask(name)
    api = Api(app)
    api.add_resource(RESTapp, '/', '/<path:path>', resource_class_kwargs=kwargs)  # Catch-all with self

    return app


def singleton_store_factory():
    """ Store already initialized tools for reuse without reinitialization (singleton store)
         must explicitly pass it to init_everything() or pipeline_rest_api()
    """
    return {}, defaultdict(list)


def resolve_presets(presets, used_tools):  # Resolve presets to module names to enable shorter URLs/task definitions...
    if len(used_tools) == 1 and used_tools[0] in presets:
        used_tools = presets[used_tools[0]]
    return used_tools


class RESTapp(Resource):
    def __init__(self, internal_apps=None, presets=(), conll_comments=False, singleton_store=None):
        """
        Init REST API class
        :param internal_apps: pre-inicialised applications
        :param presets: pre-defined chains eg. from tokenisation to dependency parsing'
        :param conll_comments: CoNLL-U-style comments (lines beginning with '#') before sentences
        """
        self._internal_apps = internal_apps
        self._presets = presets
        self._conll_comments = conll_comments

        if singleton_store is not None:
            for app in internal_apps.values():  # Sanity check params!
                if not isinstance(app, tuple):
                    raise TypeError('When using lazy initialisation internal_apps should be'
                                    ' the dict of the uninitialised tools!')
            self._singleton_store = singleton_store
            self._init_tools = self._lazy_init
        else:
            self._init_tools = lambda _: self._internal_apps
        # atexit.register(self._internal_apps.__del__)  # For clean exit...

    def _lazy_init(self, tools):
        """ Resolve presets and initialise what is needed if it were not initialised before or not available """
        tools = set(resolve_presets(self._presets, tools))
        currently_used_tools = init_everything({k: v for k, v in self._internal_apps.items() if k in tools},
                                               self._singleton_store)
        return currently_used_tools

    def get(self, path=''):
        # fun/token
        fun, token = None, ''
        if '/' in path:
            fun, token = path.split('/', maxsplit=1)

        curr_tools = self._init_tools([fun])  # Lazy or not...
        prog = getattr(curr_tools.get(fun), 'process_token', None)

        if len(path) == 0 or len(token) == 0 or prog is None:
            abort(400,
                  'Usage: '
                  'In Batch mode: HTTP POST /tool1/tool2/tool3 '
                  'and input supplied as a file named as \'file\' in the appropriate format '
                  '(see the documentation for details), '
                  'In \'one word\' mode: HTTP GET /tool/word for processing the word \'word\' by tool individually '
                  '(when the selected tool supports it). '
                  'The following tool names are available: {0}. '
                  'Further info: https://github.com/dlt-rilmta/xtsv'.
                  format(', '.join(self._internal_apps.keys())))

        json_text = json_dumps({token: prog(token)}, indent=2, sort_keys=True, ensure_ascii=False)

        return RESTapp._make_json_response(json_text)

    def post(self, path):
        conll_comments = request.form.get('conll_comments', self._conll_comments)
        if 'file' not in request.files:
            abort(400, 'ERROR: input file not found in request!')

        inp_file = codecs.getreader('UTF-8')(request.files['file'])
        required_tools = path.split('/')
        available_tools = self._init_tools(required_tools)  # Lazy or not...

        try:
            last_prog = build_pipeline(inp_file, required_tools, available_tools, self._presets, conll_comments)
        except (HeaderError, ModuleError) as e:
            abort(400, e)
            last_prog = ()  # Silence, dummy IDE

        return Response(stream_with_context((line.encode('UTF-8') for line in last_prog)), direct_passthrough=True)

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
