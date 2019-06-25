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

from .tsvhandler import process
from .jnius_wrapper import jnius_config, import_pyjnius


def make_json_response(json_text, status=200):
    """https://stackoverflow.com/questions/16908943/display-json-returned-from-flask-in-a-neat-way/23320628#23320628 """
    response = make_response(json_text)
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    response.headers['mimetype'] = 'application/json'
    response.status_code = status
    return response


def init_everything(available_tools, init_singleton=None):  # Init everything properly
    # Here we must challenge if any classpath or JAVA VM options are set to be able to throw the exception if needed
    if jnius_config.classpath is not None or len(jnius_config.options) > 0:
        import_pyjnius()
    if init_singleton is None:
        current_initialised_tools = {}
        currrent_alias_store = defaultdict(list)
    elif not isinstance(init_singleton, tuple) or len(init_singleton) != 2 or (
            isinstance(init_singleton[0], dict) and isinstance(init_singleton[1], defaultdict) and
            isinstance(init_singleton[1].default_factory, list)):
        current_initialised_tools = init_singleton[0]   # The singleton store
        currrent_alias_store = init_singleton[0]
    else:
        raise TypeError('init_singleton is expected to be (dict, defaultdict(list) instead of {0}'.
                        format(type(init_singleton)))

    for prog_name, prog_params in available_tools.items():
        prog, prog_args, prog_kwargs = prog_params
        # Dealias aliases to find the initialized versions
        for inited_prog_name, curr_prog_params in currrent_alias_store[prog]:
            if curr_prog_params == prog_params:
                current_initialised_tools[prog_name] = current_initialised_tools[inited_prog_name]
                break
        else:  # No initialized alias found... Initialize and store as initialized alias!
            current_initialised_tools[prog_name] = prog(*prog_args, **prog_kwargs)  # Inint programs...
            currrent_alias_store[prog].append((prog_name, prog_params))
    return current_initialised_tools


def build_pipeline(inp_stream, used_tools, available_tools, presets, conll_comments=False):
    # Resolve presets to module names to enable shorter URLs...
    if len(used_tools) == 1 and used_tools[0] in presets:
        used_tools = presets[used_tools[0]]

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
                raise NameError('ERROR: {0} program requires {1} columns but the previous program {2}'
                                ' has only {3} columns'.format(program, pr.source_fields, pipeline_prod,
                                                               pipeline_end_friendly))
            pipeline_end = process(pipeline_end, pr, conll_comments)
            pipeline_prod |= set(pr.target_fields)
        else:
            raise NameError('ERROR: \'{0}\' program not found. Available programs: {1}'.
                            format(program, sorted(available_tools.keys())))

    return pipeline_end


def add_params(restapi, resource_class, internal_apps, presets, conll_comments):
    if internal_apps is None:
        raise ValueError('No internal_app is given!')

    kwargs = {'internal_apps': internal_apps, 'presets': presets, 'conll_comments': conll_comments}
    # To bypass using self and @route together, default values are at the function declarations
    restapi.add_resource(resource_class, '/', '/<path:path>', resource_class_kwargs=kwargs)


class RESTapp(Resource):
    def get(self, path=''):
        # fun/token
        fun = None
        token = ''
        if '/' in path:
            fun, token = path.split('/', maxsplit=1)

        if len(path) == 0 or len(token) == 0 or fun not in self._internal_apps or not hasattr(self._internal_apps[fun],
                                                                                              'process_token'):
            abort(400, 'Usage: HTTP POST /tool1/tool2/tool3 e.g: \'{0}\' but suplied \'{1}\' a file' \
                       ' mamed as \'file\' in the apropriate TSV format or HTTP GET {2} ' \
                       'Further info: https://github.com/ppke-nlpg/emmorphpy'.
                  format(' or '.join(self._internal_apps.keys()), ' and '.join(path.split('/')),
                         '/stem/word, /analyze/word, /dstem/word'))  # TODO

        json_text = json_dumps({token: self._internal_apps[fun].process_token(token)},
                               indent=2, sort_keys=True, ensure_ascii=False)

        return make_json_response(json_text)

    def post(self, path):
        conll_comments = request.form.get('conll_comments', self._conll_comments)
        if 'file' not in request.files:
            abort(400, 'ERROR: input file not found in request!')

        inp_file = codecs.getreader('UTF-8')(request.files['file'])
        last_prog = ()  # Silence, dummy IDE

        try:
            last_prog = build_pipeline(inp_file, path.split('/'), self._internal_apps, self._presets, conll_comments)
        except NameError as e:
            abort(400, e)

        return Response(stream_with_context((line.encode('UTF-8') for line in last_prog)),
                        direct_passthrough=True)

    def __init__(self, internal_apps=None, presets=(), conll_comments=False):
        """
        Init REST API class
        :param internal_apps: pre-inicialised applications
        :param presets: pre-defined chains eg. from tokenisation to dependency parsing'
        :param conll_comments: CoNLL-U-style comments (lines beginning with '#') before sentences
        """
        self._internal_apps = internal_apps
        self._presets = presets
        self._conll_comments = conll_comments
        # atexit.register(self._internal_apps.__del__)  # For clean exit...


def pipeline_rest_api(name, available_tools, presets, conll_comments):
    app = Flask(name)
    api = Api(app)
    add_params(api, RESTapp, available_tools, presets, conll_comments)

    return app
